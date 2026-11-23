"""HTML report for one scan. One self-contained page: inline CSS, no scripts, no external resources, printable.
Every dynamic value goes through html.escape. The output depends only on the scan, so it is deterministic."""
from html import escape

from .models import Finding, ScanResult

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
TAGLINE = "Does your app do what its privacy notice says?"
# Same mark as the dashboard (LogoMark in dashboard/src/App.jsx). Inline SVG, so the CSP needs nothing extra.
MARK = ('<svg class="mark" viewBox="0 0 32 32" fill="none" aria-hidden="true"><circle cx="16" cy="16" r="11" stroke="#0e5a55" '
        'stroke-width="3.5" stroke-dasharray="56 13.1" transform="rotate(-12 16 16)"/><circle cx="16" cy="16" r="3.5" fill="#0e5a55"/></svg>')
FOOTER = "DPDP Lens is a readiness report, not a compliance certificate. Main duties apply from 13 May 2027."

CSS = """
:root { --ink:#1b1d22; --muted:#5b6270; --line:#ddd8cc; --panel:#f6f4ef; --ok:#0e5a55; --bad:#b42318; --warn:#b04a0a;
  --critical:#b42318; --high:#b04a0a; --medium:#8a6308; --low:#5b6270;
  --serif: Newsreader, Georgia, "Times New Roman", serif; --mono: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace; }
/* Same tokens as the dashboard (dashboard/src/index.css). No font files: the CSP allows nothing external, so the
   named fonts are used only where installed, otherwise the system fallbacks. */
* { box-sizing: border-box; }
body { font: 16px/1.5 "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--ink); background: var(--panel);
  max-width: 920px; margin: 0 auto; padding: 24px 20px 40px; }
h1, h2, h3, .score b, .brand { font-family: var(--serif); }
.brand { display: flex; align-items: center; gap: 10px; font-size: 22px; font-weight: 600; margin-bottom: 18px; } .mark { width: 28px; height: 28px; }
.tagline { font-family: var(--serif); font-size: 18px; margin: 2px 0 6px; }
h1 { font-size: 28px; margin: 0 0 4px; } h2 { font-size: 20px; margin: 32px 0 10px; padding-bottom: 6px; border-bottom: 2px solid var(--line); }
h3 { font-size: 16px; margin: 0 0 6px; } p { margin: 6px 0; } .muted { color: var(--muted); }
.notice { border: 1px solid var(--line); background: #fff; border-radius: 6px; padding: 10px 14px; margin: 14px 0; }
.summary { display: flex; flex-wrap: wrap; gap: 10px; align-items: stretch; margin: 14px 0; font-variant-numeric: tabular-nums; }
.score { border: 1px solid var(--line); background: #fff; border-radius: 6px; padding: 8px 18px; text-align: center; }
.score b { font-size: 44px; display: block; line-height: 1.1; }
.count { border: 1px solid var(--line); background: #fff; border-radius: 6px; padding: 8px 14px; text-align: center; min-width: 90px; }
.count b { font-size: 24px; display: block; font-family: var(--mono); }
.finding { border: 1px solid var(--line); border-left: 4px solid var(--line); background: #fff; border-radius: 6px; padding: 12px 14px; margin: 12px 0; break-inside: avoid; }
.sev-critical { border-left-color: var(--critical); } .sev-high { border-left-color: var(--high); }
.sev-medium { border-left-color: var(--medium); } .sev-low { border-left-color: var(--low); }
.pill, .layer, .chip, .badge, .tag { display: inline-block; border: 1px solid var(--line); border-radius: 4px; padding: 0 7px; font-size: 13px; margin-right: 4px; }
.pill { font-weight: 700; text-transform: uppercase; } .layer { text-transform: uppercase; color: var(--muted); }
.pill.critical { color: var(--critical); border-color: var(--critical); } .pill.high { color: var(--high); border-color: var(--high); }
.pill.medium { color: var(--medium); border-color: var(--medium); } .pill.low { color: var(--low); border-color: var(--low); }
.id, code, pre, .tag { font-family: var(--mono); }
.chip b { font-family: var(--mono); } .chip span { color: var(--muted); }
dl { display: grid; grid-template-columns: 130px 1fr; gap: 3px 12px; margin: 8px 0; } dt { color: var(--muted); } dd { margin: 0; word-break: break-word; }
pre { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; margin: 8px 0; font-size: 13px;
  white-space: pre-wrap; word-break: break-word; }
.add { color: var(--ok); background: #e3f0ec; } .del { color: var(--bad); background: #fbe9e7; } .hunk { color: var(--muted); }
.fix { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--line); }
.badge.yes { color: var(--ok); border-color: var(--ok); } .badge.no { color: var(--bad); border-color: var(--bad); } .badge.unknown { color: var(--muted); }
.label-cached { display: inline-block; color: var(--warn); border: 1px solid var(--warn); border-radius: 4px; padding: 1px 8px; font-weight: 600; }
.ok { color: var(--ok); font-weight: 600; } .bad { color: var(--bad); font-weight: 600; }
table { border-collapse: collapse; width: 100%; } th, td { border: 1px solid var(--line); padding: 6px 9px; text-align: left; vertical-align: top; }
th { background: var(--panel); } td { background: #fff; } tr.undeclared td { background: #fbf3f1; } .not-in-notice { color: var(--bad); font-weight: 700; }
footer { margin-top: 36px; padding-top: 12px; border-top: 1px solid var(--line); color: var(--muted); font-size: 14px; }
@media print { body { padding: 0; max-width: none; background: #fff; } h2 { break-after: avoid; } .finding, tr { break-inside: avoid; } }
"""


def h(value) -> str:
    return escape(str(value), quote=True)


def _location(f: Finding) -> str:
    loc = f.evidence.location
    if loc.file:
        return f"{loc.file}:{loc.line}" if loc.line else loc.file
    if loc.url:
        return loc.url
    if loc.table:
        return f"{loc.table}.{loc.column}" if loc.column else loc.table
    return ""


def _badge(label: str, value) -> str:
    cls, text = ("yes", "yes") if value is True else ("no", "no") if value is False else ("unknown", "unknown")
    return f'<span class="badge {cls}">{h(label)}: {text}</span>'


def _diff(text: str) -> str:
    def line(raw: str) -> str:
        cls = ("hunk" if raw.startswith("@@") else "add" if raw.startswith("+") and not raw.startswith("+++")
               else "del" if raw.startswith("-") and not raw.startswith("---") else "")
        return f'<span class="{cls}">{h(raw)}</span>' if cls else h(raw)

    return "<pre>" + "\n".join(line(raw) for raw in text.splitlines()) + "</pre>"


def _fix_block(f: Finding, mode: dict | None) -> str:
    fix = f.fix
    if f.status != "verified_fixed" and fix.rescan_passed is None and fix.tests_passed is None:
        return ""
    parts = ['<div class="fix">', _badge("Re-scan passed", fix.rescan_passed), _badge("Tests passed", fix.tests_passed),
             _badge("Verified", fix.verified)]
    if fix.score_before is not None and fix.score_after is not None:
        parts.append(f'<span class="muted"> Score {h(fix.score_before)} to {h(fix.score_after)}</span>')
    cached = bool(mode) and mode.get("mode") == "cached_golden"
    if cached:
        reason = mode.get("fallback_reason")
        parts.append('<p><span class="label-cached">Cached golden patch mode</span> '
                     + (f"Live run could not finish: {h(reason)}" if reason else "Replayed from a saved verified run, not run just now.")
                     + "</p>")
    if fix.verified:
        parts.append('<p class="ok">'
                     + ("Verified in a saved run on a sandbox copy. It was not run just now." if cached
                        else "Verified on a sandbox copy. Re-scan passed and the app's tests still pass.")
                     + " Your original code is unchanged.</p>")
    else:
        parts.append('<p class="bad">Not verified. The finding stays open.</p>')
    if fix.diff:
        parts.append(_diff(fix.diff))
    parts.append("</div>")
    return "".join(parts)


def _finding(f: Finding, mode: dict | None) -> str:
    chips = "".join(f'<span class="chip"><b>{h(c.ref)}</b> <span>{h(c.note)}</span></span>' for c in f.clauses)
    ev = f.evidence
    rows = [("Evidence", f"{h(ev.summary)} ({h(ev.kind)})")]
    if ev.masked_sample:
        rows.append(("Masked sample", f"<code>{h(ev.masked_sample)}</code>"))
    if _location(f):
        rows.append(("Location", f"<code>{h(_location(f))}</code>"))
    status = "Verified fixed" if f.status == "verified_fixed" else "Open"
    return (f'<section class="finding sev-{h(f.severity)}">'
            f'<h3><span class="id">{h(f.id)}</span> <span class="pill {h(f.severity)}">{h(f.severity)}</span> '
            f'<span class="layer">{h(f.layer)}</span> {h(f.title)}</h3>'
            f'<p class="muted">Status: {status}</p><p>{h(f.explanation)}</p><p>{chips}</p>'
            f'<dl>{"".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)}</dl>{_fix_block(f, mode)}</section>')


def _drift(scan: ScanResult) -> str:
    d = scan.notice_drift
    if d is None:
        return "<p>No drift data for this scan.</p>"
    fields = {o.field for o in d.observed} | set(d.declared)
    head = (f"<p><b>{len(d.undeclared)} of {len(fields)} data fields are collected but not disclosed.</b> "
            "Notice duties: Act s5, Rule 3.</p>")
    declared = ", ".join(h(x) for x in d.declared) or "none"
    rows = "".join(
        f'<tr class="{"undeclared" if o.field in d.undeclared else ""}"><td><code>{h(o.field)}</code></td>'
        f'<td>{"".join(f"<span class=tag>{h(w)}</span>" for w in o.where)}</td>'
        f'<td>{"<span class=not-in-notice>Not in the notice</span>" if o.field in d.undeclared else "Declared"}</td></tr>'
        for o in d.observed)
    return (f"{head}<p>The notice lists: {declared}.</p>"
            f"<table><tr><th>Field</th><th>Observed in</th><th>Notice</th></tr>{rows}</table>")


def render_report(scan: ScanResult, fix_modes: dict | None = None) -> str:
    fix_modes = fix_modes or {}
    findings = sorted(scan.findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.id))
    counts = "".join(f'<div class="count"><b>{getattr(scan.counts, sev)}</b>{sev}</div>' for sev in SEVERITY_ORDER)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DPDP Lens: readiness report - {h(scan.scan_id)}</title><style>{CSS}</style></head>
<body>
<div class="brand">{MARK}DPDP Lens</div>
<h1>Readiness report</h1>
<p class="tagline">{h(TAGLINE)}</p>
<p class="muted">Scan {h(scan.scan_id)} of <code>{h(scan.target)}</code>, scanned {h(scan.scanned_at)}</p>
<div class="notice"><b>{h(FOOTER)}</b></div>
<div class="summary"><div class="score"><b>{h(scan.score)}</b>readiness score</div>{counts}</div>
<p class="muted">Readiness score: 100 minus 20 per critical, 10 per high, 5 per medium and 2 per low open finding. Higher is better.</p>
<h2>Findings ({len(findings)})</h2>
{"".join(_finding(f, fix_modes.get(f.id)) for f in findings) or "<p>No findings from the checks we ran. The checks are limited, so this is not a compliance result.</p>"}
<h2>Notice vs Runtime</h2>
{_drift(scan)}
<h2>Limits</h2>
<ul>
<li>These checks are a subset of the duties in the DPDP Act 2023 and the DPDP Rules 2025. A clean report does not mean the app complies.</li>
<li>Findings say an app "likely does not meet" a safeguard. This is not legal advice.</li>
<li>If this app is a notified startup class, s8(7) may be exempt. s8(5) still applies.</li>
<li>Evidence is masked. The scan reads only the app it was pointed at, on this machine, with non-destructive requests.</li>
</ul>
<footer>{h(FOOTER)}</footer>
</body></html>
"""
