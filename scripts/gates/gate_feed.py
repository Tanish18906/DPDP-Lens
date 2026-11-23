"""The Feed view (block 04): findings of connected repositories, status tabs with counts, a status change in the UI and one
made "in Slack" (the same API call), the incomplete-scan banner from a real forced failure, health pills, empty, error and
loading states, sample mode, and no raw personal data on the page.

Needs the stack that scripts/run_gates.sh starts: it sets DPDP_API_TOKEN, VITE_DPDP_TOKEN, DPDP_ALLOWED_REPOS (gate/ok,gate/big) and
DPDP_STATE_DIR. The gate makes two local git repos, connects them through the API, scans them with the engine's own code
(repo_scan, static mode) and ingests the scans into the engine's database file. No network is used."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

import common as c

g = c.Gate("feed")
TOKEN, STATE = os.environ.get("DPDP_API_TOKEN", ""), os.environ.get("DPDP_STATE_DIR", "")
if not (TOKEN and STATE and "gate/ok" in os.environ.get("DPDP_ALLOWED_REPOS", "")):
    g.check("stack started by scripts/run_gates.sh (DPDP_API_TOKEN, DPDP_STATE_DIR, DPDP_ALLOWED_REPOS)", False,
            "this gate needs the environment that run_gates.sh gives the engine, it cannot reuse a stack started by hand")
    g.done()

sys.path.insert(0, str(c.ROOT / "engine"))
from dpdp_lens import repo_scan  # noqa: E402
from dpdp_lens.ingest import ingest_scan  # noqa: E402
from dpdp_lens.store import Store  # noqa: E402

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "gate", "GIT_AUTHOR_EMAIL": "gate@example.test",
           "GIT_COMMITTER_NAME": "gate", "GIT_COMMITTER_EMAIL": "gate@example.test"}
AUTH = {"X-DPDP-Token": TOKEN}
PII = [re.compile(r"\b[2-9]\d{3} ?\d{4} ?\d{4}\b"), re.compile(r"\b(?!X{5})[A-Z]{5}\d{4}[A-Z]\b"), re.compile(r"\b[6-9]\d{9}\b")]


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True)


def make_remote(base: Path, name: str, source: Path):
    work = base / "_work" / name.replace("/", "_")
    shutil.copytree(source, work, ignore=shutil.ignore_patterns("node_modules", "dist", "*.db", "__pycache__", ".pytest_cache", "*.log"))
    git(work, "init", "-q", "-b", "main")
    git(work, "add", "-A", "-f")
    git(work, "commit", "-q", "-m", "gate")
    bare = base / f"{name}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    git(base, "clone", "-q", "--bare", str(work), str(bare))


def engine(method, path, **kw):
    r = httpx.request(method, f"{c.ENGINE}{path}", headers=AUTH, timeout=20, **kw)
    r.raise_for_status()
    return r.json()


def seed():
    """Two repos: gate/ok (TutorNest, a complete static scan) and gate/big (one file over 1 MB, so its scan is incomplete)."""
    base = Path(tempfile.mkdtemp(prefix="dpdp-gate-feed-"))
    make_remote(base, "gate/ok", c.ROOT / "target-app")
    small = base / "_src" / "big"
    (small / "backend" / "app").mkdir(parents=True)
    (small / "backend" / "app" / "main.py").write_text('import logging\nlog = logging.getLogger("x")\n\ndef signup(email):\n    log.info("signup %s", email)\n')
    (small / "backend" / "blob.py").write_text("# " + "x" * 1_200_000 + "\n")
    make_remote(base, "gate/big", small)
    repo_scan.GIT_BASE, repo_scan.ALLOW_FILE = f"file://{base}", True
    ids = {name: engine("POST", "/repos", json={"full_name": name, "actor": "gate"})["id"] for name in ("gate/ok", "gate/big")}
    store = Store(Path(STATE) / "dpdp.db")
    for n, name in enumerate(ids, 1):
        with repo_scan.checkout(name, "main") as path:
            result = repo_scan.scan_checkout(path, f"G-{n:03d}", "static", name, "main")
        ingest_scan(store, ids[name], result, "gate", "gate")
    store.close()
    shutil.rmtree(base, ignore_errors=True)
    return ids


def api_counts(repo_id=None):
    return engine("GET", "/findings", params={"limit": 1, **({"repo_id": repo_id} if repo_id else {})})["counts_by_status"]


def tab_counts(page):
    """tab label -> count, read from the tab text ("False Positive 2")."""
    return {m.group(1): int(m.group(2)) for t in page.get_by_role("tab").all() if (m := re.match(r"(.*?)\s*(\d+)\s*$", t.inner_text().strip()))}


def rail_count(page):
    m = re.search(r"(\d+)", page.locator('nav[aria-label="Views"] button', has_text="Feed").inner_text())
    return int(m.group(1)) if m else 0


def rows(page):
    return page.locator("tbody tr:not([aria-hidden])")


def feed(page):
    page.locator('nav[aria-label="Views"] button', has_text="Feed").click()
    page.get_by_role("heading", name="Feed").wait_for()


ids = seed()
before = api_counts()
g.check("seed: two repos connected and ingested through the API and the store", before["open"] > 10 and len(ids) == 2, str(before))

with sync_playwright() as p:
    b, errs = c.launch(p), []
    page = c.new_page(b, errs)
    c.open_live(page)

    # ---- rail, tabs, rows
    page.locator('nav[aria-label="Views"] button', has_text="Feed").wait_for()
    page.wait_for_function("() => /Feed\\s*\\d+/.test(document.querySelector('nav[aria-label=\"Views\"]').innerText)", timeout=10000)
    g.check("rail: Feed item shows the open count", rail_count(page) == before["open"], f"{rail_count(page)} vs {before['open']}")
    feed(page)
    rows(page).first.wait_for(timeout=10000)
    names = list(tab_counts(page))
    g.check("tabs: Open, In Progress, Fixed, False Positive, Won't Fix", names == ["Open", "In Progress", "Fixed", "False Positive", "Won't Fix"], str(names))
    shown = list(tab_counts(page).values())
    expect = [before[k] for k in ("open", "in_progress", "fixed", "false_positive", "wont_fix")]
    g.check("tabs: counts come from the engine", shown == expect, f"{shown} vs {expect}")
    g.check("table: Finding, Location, Status columns", [h.inner_text().strip().lower() for h in page.locator("thead th").all()] == ["finding", "location", "status"])
    sev = [r.locator("td").first.inner_text().split("\n")[0].strip().lower() for r in rows(page).all()]
    rank = {"critical": 1, "high": 2, "medium": 3, "low": 4}
    g.check("rows: critical first", [rank[s] for s in sev] == sorted(rank[s] for s in sev) and sev[0] in ("critical", "high"), str(sev[:6]))
    g.check("rows: IDs read DPDP-014 and every row has a one line explanation",
            all(re.search(r"DPDP-\d{3}", r.inner_text()) for r in rows(page).all()) and all(len(r.locator("td").first.inner_text().split("\n")) >= 4 for r in rows(page).all()))
    g.check("rows: repo@branch under the location", "gate/ok@main" in rows(page).first.inner_text() or "gate/big@main" in rows(page).first.inner_text())

    # ---- health, incomplete banner, static label
    pills = page.locator('ul[aria-label="Repository health"] > li')
    ok_pill, big_pill = pills.filter(has_text="gate/ok"), pills.filter(has_text="gate/big")
    g.check("health: gate/ok At Risk, gate/big Unknown", "At Risk" in ok_pill.inner_text() and "Unknown" in big_pill.inner_text(), pills.all_inner_texts().__str__())
    g.check("health: reasons are on hover (title) and in screen reader text",
            "blocking finding" in (ok_pill.locator("[title]").first.get_attribute("title") or "")
            and "incomplete" in (big_pill.locator("[title]").first.get_attribute("title") or "")
            and "Health reasons" in big_pill.locator(".sr-only").first.inner_text(), ok_pill.locator("[title]").first.get_attribute("title"))
    g.check("health: static scans say Static checks only (n of 19)", re.search(r"Static checks only \(\d+ of 19\)", ok_pill.inner_text()) is not None, ok_pill.inner_text())
    banner = page.get_by_role("alert").filter(has_text="Scan incomplete: results are partial")
    g.check("banner: Scan incomplete, names the repo and the scanner that hit the 1 MB cap",
            banner.count() == 1 and "gate/big" in banner.inner_text() and "log_scan (capped)" in banner.inner_text(), banner.all_inner_texts().__str__())
    c.shot(page, "feed-incomplete")
    page.locator("#feed-repo").select_option(label="gate/ok")
    page.wait_for_timeout(300)
    g.check("repo filter: choosing gate/ok hides gate/big's banner and rows", banner.count() == 0 and all("gate/big" not in r.inner_text() for r in rows(page).all()))
    page.locator("#feed-repo").select_option(label="All repositories")

    # ---- search
    page.locator("#feed-search").fill("Dockerfile")
    page.wait_for_timeout(900)
    g.check("search: Dockerfile leaves only matching rows", 0 < rows(page).count() < before["open"] and all("Dockerfile" in r.inner_text() for r in rows(page).all()), str(rows(page).count()))
    page.locator("#feed-search").fill("")
    page.wait_for_timeout(900)

    # ---- detail drawer and a status change through the UI
    rows(page).first.get_by_role("button").first.click()
    dlg = page.get_by_role("dialog")
    dlg.wait_for()
    first_id = re.search(r"DPDP-\d{3}", dlg.get_attribute("aria-label")).group(0)
    dlg.get_by_text("Found by a scan").wait_for(timeout=8000)  # the timeline arrives with the finding's detail
    text = dlg.inner_text().lower()  # headings are upper case through CSS, and inner_text follows it
    g.check("drawer: why, what, law, evidence, recommended fix, timeline", all(x.lower() in text for x in ("Why this severity", "What we found", "Law", "Evidence", "Recommended fix", "Timeline", "Found by a scan")), text[:200])
    g.check("drawer: proof tag", any(w in text for w in ("probed", "observed", "static")))
    dlg.locator("#feed-status").select_option(label="Won't Fix")
    dlg.get_by_role("button", name="Update status").click()
    g.check("drawer: Won't Fix needs a reason, and the status did not change", dlg.get_by_text("needs a reason").is_visible() and engine("GET", f"/findings/{first_id}")["status"] == "open")
    dlg.locator("#feed-status").select_option(label="False Positive")
    dlg.locator("#feed-reason").fill("test data only")
    dlg.get_by_role("button", name="Update status").click()
    dlg.get_by_text("Status is now False Positive.").wait_for(timeout=8000)
    now = api_counts()
    g.check("UI status change: engine says false_positive, set by dashboard", engine("GET", f"/findings/{first_id}")["status"] == "false_positive" and engine("GET", f"/findings/{first_id}")["status_by"] == "dashboard")
    g.check("UI status change: the Open count fell by 1 and False Positive rose by 1 in the API",
            now["open"] == before["open"] - 1 and now["false_positive"] == before["false_positive"] + 1, str(now))
    page.wait_for_function("(n) => [...document.querySelectorAll('[role=tab]')].some(t => /^Open\\s+(\\d+)/.test(t.innerText) && +t.innerText.match(/(\\d+)\\s*$/)[1] === n)", arg=before["open"] - 1, timeout=8000)
    page.wait_for_function("(n) => /Feed\\s*(\\d+)/.exec(document.querySelector('nav[aria-label=\"Views\"]').innerText)?.[1] == n", arg=str(before["open"] - 1), timeout=3000)
    g.check("UI status change: tabs and the rail show the new counts", tab_counts(page)["False Positive"] == before["false_positive"] + 1 and rail_count(page) == before["open"] - 1, str(tab_counts(page)))
    g.check("timeline lists the status change with its actor", "Status changed" in dlg.inner_text() and "dashboard" in dlg.inner_text())
    page.keyboard.press("Escape")
    g.check("drawer closes on Escape", dlg.count() == 0)

    # ---- a change made "in Slack" shows up without a reload (polling every 5 s)
    other = [r for r in engine("GET", "/findings", params={"status": "open", "limit": 5})["items"]][0]["human_id"]
    engine("PATCH", f"/findings/{other}/status", json={"status": "in_progress", "reason": "", "actor": "U-slack"})
    page.wait_for_function("() => [...document.querySelectorAll('[role=tab]')].some(t => /^In Progress\\s+1\\s*$/.test(t.innerText.trim()))", timeout=9000)
    g.check("slack-side status change appears in the Feed within one poll, no reload", tab_counts(page)["In Progress"] == 1 and rail_count(page) == before["open"] - 2, str(tab_counts(page)))
    page.get_by_role("tab", name=re.compile("^In Progress")).click()
    rows(page).filter(has_text=other).first.wait_for(timeout=8000)  # the old list stays up until the new answer arrives
    g.check("In Progress tab lists that finding", rows(page).count() == 1 and other in rows(page).first.inner_text())
    page.get_by_role("tab", name=re.compile("^Open")).click()

    # ---- fix button only where a fix exists and is allowed
    with_fix = [i for i in engine("GET", "/findings", params={"status": "open", "limit": 500})["items"] if i["fix_available"]]
    without = [i for i in engine("GET", "/findings", params={"status": "open", "limit": 500})["items"] if not i["fix_available"]]
    page.locator("#feed-search").fill(with_fix[0]["human_id"])
    page.wait_for_timeout(900)
    rows(page).first.get_by_role("button").first.click()
    g.check("fix: the Fix and verify button is there when the finding has a fix", page.get_by_role("button", name="Fix and verify").is_visible())
    page.keyboard.press("Escape")
    page.locator("#feed-search").fill(without[0]["human_id"])
    page.wait_for_timeout(900)
    rows(page).first.get_by_role("button").first.click()
    g.check("fix: no button for a finding without a fix template", page.get_by_role("button", name="Fix and verify").count() == 0)
    page.keyboard.press("Escape")
    page.locator("#feed-search").fill("")
    page.wait_for_timeout(900)

    # ---- no raw personal data on the page, in the list or in any drawer opened above
    page.get_by_role("tab", name=re.compile("^Open")).click()
    pages_text = c.body(page)
    g.check("no raw Aadhaar, PAN or phone number on the page", not any(rx.search(pages_text) for rx in PII))
    g.check("no console errors on the Feed", c.real_errors(errs) == [], str(c.real_errors(errs)[:3]))
    c.shot(page, "feed-open")

    # ---- the existing Findings view: banner for a scan that is not complete (forced failure of one scanner)
    def force_incomplete(route):
        resp = route.fetch()
        body = resp.json() if "json" in (resp.headers.get("content-type") or "") else None
        if isinstance(body, dict) and "findings" in body:
            body["complete"], body["scan_errors"] = False, [{"scanner": "browser_scan", "kind": "failed", "message": "forced by the gate"}]
            return route.fulfill(response=resp, json=body)
        return route.fulfill(response=resp)

    page.route(re.compile(r".*/scan/S-\d+$"), force_incomplete)
    page.get_by_role("button", name=re.compile(r"^Findings")).click()
    page.get_by_role("button", name="Run scan").first.click()
    page.get_by_text(re.compile(r"Findings \(\d+\)")).wait_for(timeout=60000)
    ban = page.get_by_role("alert").filter(has_text="Scan incomplete: results are partial")
    g.check("Findings view: red banner with the scanner that failed", ban.count() == 1 and "browser_scan (failed)" in ban.inner_text(), ban.all_inner_texts().__str__())
    page.unroute(re.compile(r".*/scan/S-\d+$"))

    # ---- states: empty, error, loading
    for name, handler in (
        ("empty", lambda r: r.fulfill(json={"total": 0, "counts_by_status": {}, "items": []}) if "/findings" in r.request.url else r.fulfill(json=[])),
        ("error", lambda r: r.fulfill(status=500, json={"error": "Internal Server Error", "detail": "database is locked"}) if "/findings" in r.request.url else r.fulfill(json=[]))):
        pg = c.new_page(b, [])
        pg.route(re.compile(rf"{re.escape(c.ENGINE)}/(findings|repos).*"), handler)
        c.open_live(pg)
        feed(pg)
        if name == "empty":
            pg.get_by_text("No findings yet.").wait_for(timeout=8000)
            g.check("empty state: invites /dpdp connect", pg.get_by_text("/dpdp connect").is_visible())
            c.shot(pg, "feed-empty")
        else:
            pg.get_by_text("The Feed could not load findings").wait_for(timeout=8000)
            g.check("error state: shows the engine's own text and a retry button", pg.get_by_text("database is locked").is_visible() and pg.get_by_role("button", name="Try again").is_visible())
        pg.close()
    pg = c.new_page(b, [])
    held = []
    pg.route(re.compile(rf"{re.escape(c.ENGINE)}/findings.*"), lambda r: held.append(r))
    c.open_live(pg)
    feed(pg)
    pg.locator('tbody tr[aria-hidden="true"]').first.wait_for(timeout=8000)
    g.check("loading state: skeleton rows while the engine has not answered", pg.locator('tbody tr[aria-hidden="true"]').count() == 5)
    for r in held:
        r.continue_()
    rows(pg).first.wait_for(timeout=10000)
    pg.close()

    # ---- sample mode keeps working, labelled SAMPLE, read only
    sp = c.new_page(b, [])
    c.use_sample_mode(sp)
    sp.get_by_role("button", name="Use sample data").click()
    feed(sp)
    rows(sp).first.wait_for()
    g.check("sample mode: Feed works from the sample scan and is labelled SAMPLE", sp.get_by_text("SAMPLE", exact=True).is_visible() and rows(sp).count() == 5, str(rows(sp).count()))
    rows(sp).first.get_by_role("button").first.click()
    g.check("sample mode: drawer is read only", sp.get_by_role("dialog").get_by_text("statuses cannot be changed").is_visible() and sp.locator("#feed-status").count() == 0)
    b.close()

g.done()
