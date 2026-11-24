"""Open a pull request with a VERIFIED fix (block 13). Never merges, never touches the default branch, never force-pushes, never deletes.

The files that go on the branch are the verified sandbox result, not a recomputation: the verified unified diff (stored with the fix)
is applied to the exact blobs of the scanned commit, and the result must reproduce that diff character for character, or nothing is
pushed. The branch is created from the scanned commit with the git data API (blobs, tree, commit, then a NEW ref: creating a ref
that exists fails, so nothing can be overwritten). The token is a separate installation token limited to one repository and to
contents:write and pull_requests:write, kept in memory for this one call.

Nothing here reads the environment or the store: the caller (api_v2) decides whether the action is allowed."""
import base64
import difflib
import re

from .audit import clean, redact
from .github_app import GitHubApp, GitHubAppError

BRANCH = re.compile(r"^dpdp-lens/fix-DPDP-\d{3,6}-[0-9a-f]{7}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
VERIFIED_LINE = re.compile(r"^Verified: .+$", re.M)
NOT_VERIFIED_LINE = re.compile(r"^Not verified / you still must: .+$", re.M)
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PrError(Exception):
    """kind: refused (the fix cannot go on a branch), exists (branch is there with no open PR), github (a GitHub call failed)."""

    def __init__(self, kind: str, message: str):
        super().__init__(redact(message))
        self.kind = kind


def branch_name(human_id: str, commit: str) -> str:
    name = f"dpdp-lens/fix-{human_id}-{commit[:7]}"
    if not BRANCH.fullmatch(name):
        raise PrError("refused", f"{name!r} is not a valid branch name")
    return name


def split_diff(diff: str) -> tuple[str, str, str]:
    """(patch body, the "Verified: ..." line, the "Not verified / you still must: ..." line), exactly as the engine wrote them."""
    v, nv = VERIFIED_LINE.search(diff or ""), NOT_VERIFIED_LINE.search(diff or "")
    if not (v and nv):
        raise PrError("refused", "the stored fix has no verification lines, so it cannot be turned into a pull request")
    return diff[:v.start()].rstrip() + "\n", v.group(0), nv.group(0)


def file_sections(body: str) -> dict[str, str]:
    """label -> that file's part of the diff (from its '--- a/<label>' line)."""
    parts, current = {}, None
    for line in body.splitlines(True):
        if line.startswith("--- a/"):
            current = line[len("--- a/"):].strip()
            parts[current] = ""
        if current is not None:
            parts[current] += line
    if not parts:
        raise PrError("refused", "the stored fix has no file changes")
    return parts


def apply_section(original: str, section: str, label: str) -> str:
    """Apply one file's unified diff to `original`. Every context and removed line must match exactly, and the result must give back
    the same diff when diffed again: otherwise PrError and nothing is pushed."""
    old, out, pos = original.splitlines(True), [], 0
    lines = section.splitlines(True)
    i = 2  # after '--- a/' and '+++ b/'
    while i < len(lines):
        m = HUNK.match(lines[i])
        if not m:
            raise PrError("refused", f"{label}: the stored diff is not a unified diff")
        start = int(m.group(1)) - (1 if m.group(2) != "0" else 0)
        out += old[pos:start]
        pos = start
        i += 1
        while i < len(lines) and not lines[i].startswith("@@"):
            tag, text = lines[i][:1], lines[i][1:]
            if tag in (" ", "-"):
                if pos >= len(old) or old[pos] != text:
                    raise PrError("refused", f"{label}: the scanned commit's file does not match the verified diff (line {pos + 1})")
                pos += 1
                if tag == " ":
                    out.append(text)
            elif tag == "+":
                out.append(text)
            else:
                raise PrError("refused", f"{label}: unexpected line in the stored diff")
            i += 1
    out += old[pos:]
    patched = "".join(out)
    again = "".join(difflib.unified_diff(old, patched.splitlines(True), f"a/{label}", f"b/{label}"))
    if again != section:
        raise PrError("refused", f"{label}: applying the verified diff does not reproduce it exactly, so nothing was pushed")
    return patched


def _summary(sections: dict[str, str]) -> list[str]:
    out = []
    for label, sec in sections.items():
        lines = sec.splitlines()
        out.append(f"- `{label}`: +{sum(l.startswith('+') and not l.startswith('+++') for l in lines)} "
                   f"-{sum(l.startswith('-') and not l.startswith('---') for l in lines)}")
    return out


def pr_body(human_id: str, title: str, severity: str, clauses: list[dict], sections: dict[str, str], verified: str, not_verified: str,
            scanned: str, head: str, default_branch: str) -> str:
    lines = [f"## {human_id}: {title}", f"Severity: {severity}.", "", "### What was found"]
    lines += [f"- Likely does not meet {c['ref']}: {c['note']}" for c in clauses] or ["- (no clause recorded)"]
    lines += ["", "### What changes", *_summary(sections), "",
              "### Verification (from the DPDP Lens engine, unchanged)", verified, not_verified, "",
              f"Scanned and fixed at commit `{scanned[:7]}`. The pull request targets `{default_branch}`."]
    if head != scanned:
        lines.append(f"`{default_branch}` has moved on since then (head is now `{head[:7]}`): check the branch for conflicts before merging.")
    lines += ["", "_Generated by DPDP Lens. A person must review this before merging; nothing was merged for you. "
                  "This is a readiness fix, not a compliance certificate._"]
    return clean("\n".join(lines))


def open_pull_request(app: GitHubApp, installation_id: int, full_name: str, human_id: str, title: str, severity: str, clauses: list[dict],
                      diff: str, commit: str) -> dict:
    """Returns {pr_url, number, branch, reused, base}. `reused`: the branch already had an open pull request, which is returned instead."""
    if not NAME.fullmatch(full_name) or not SHA.fullmatch(commit or ""):
        raise PrError("refused", "bad repository name or commit")
    body_diff, verified, not_verified = split_diff(diff)
    sections = file_sections(body_diff)
    branch = branch_name(human_id, commit)
    owner, name = full_name.split("/")
    repo = f"/repos/{full_name}"
    try:
        token = app.pr_token(installation_id, name)  # downscoped, in memory, used for this call only
        call = lambda method, path, **kw: app.api_call(method, repo + path, token, **kw)  # noqa: E731
        default = call("GET", "")["default_branch"]
        head = call("GET", f"/git/ref/heads/{default}")["object"]["sha"]
        try:
            call("GET", f"/git/ref/heads/{branch}")
            exists = True
        except GitHubAppError as e:
            if e.kind != "notfound":
                raise
            exists = False
        if exists:  # never touched: report it, and hand back its open pull request if it has one
            open_prs = call("GET", "/pulls", params={"head": f"{owner}:{branch}", "state": "open"})
            if open_prs:
                return {"pr_url": open_prs[0]["html_url"], "number": open_prs[0]["number"], "branch": branch, "reused": True, "base": default}
            raise PrError("exists", f"the branch {branch} already exists and has no open pull request: delete it on GitHub or open the pull request by hand")
        tree_sha = call("GET", f"/git/commits/{commit}")["tree"]["sha"]
        tree = call("GET", f"/git/trees/{tree_sha}", params={"recursive": "1"})
        if tree.get("truncated"):
            raise PrError("refused", "the repository tree is too large to read through the API")
        entries = {e["path"]: e for e in tree["tree"] if e["type"] == "blob"}
        new_entries = []
        for label, section in sections.items():
            ok = {}
            for path in ([label] if label.startswith("frontend/") else [f"backend/{label}", label]):
                if path in entries:
                    blob = call("GET", f"/git/blobs/{entries[path]['sha']}")
                    try:
                        ok[path] = apply_section(base64.b64decode(blob["content"]).decode("utf-8"), section, label)
                    except (PrError, UnicodeDecodeError):
                        continue
            if len(ok) != 1:
                raise PrError("refused", f"{label}: found {len(ok)} files in the scanned commit that the verified diff applies to (need exactly one)")
            (path, patched), = ok.items()
            new_blob = call("POST", "/git/blobs", json={"content": patched, "encoding": "utf-8"})["sha"]
            new_entries.append({"path": path, "mode": entries[path]["mode"], "type": "blob", "sha": new_blob})
        new_tree = call("POST", "/git/trees", json={"base_tree": tree_sha, "tree": new_entries})["sha"]
        message = f"DPDP Lens: fix {human_id} {title}"[:200] + "\n\nVerified by DPDP Lens (readiness fix, not a compliance certificate). Review before merging."
        new_commit = call("POST", "/git/commits", json={"message": message, "tree": new_tree, "parents": [commit]})["sha"]
        call("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": new_commit})  # a NEW ref: fails if it exists, never a force update
        pr = call("POST", "/pulls", json={"title": f"DPDP Lens: fix {human_id} {title}"[:250], "head": branch, "base": default, "maintainer_can_modify": False,
                                          "body": pr_body(human_id, title, severity, clauses, sections, verified, not_verified, commit, head, default)})
        return {"pr_url": pr["html_url"], "number": pr["number"], "branch": branch, "reused": False, "base": default}
    except GitHubAppError as e:
        raise PrError("github", f"GitHub refused the pull request step: {e}") from None
