"""notice_drift fix: add a section to the privacy notice that lists every field the app handles but the notice leaves out.
It only makes the notice match what the app does. It never invents a purpose: each one is a placeholder the owner fills in.
It does not stop the collection, that stays a manual code change. Pure functions, no file access."""
from html import escape

from ..models import NoticeDrift
from .templates import Template

MARKER = "<!-- dpdp-lens:notice-align -->"
END_MARKER = "<!-- /dpdp-lens:notice-align -->"
PURPOSE_PLACEHOLDER = "[purpose: to be filled by you]"
LABELS = {"name": "Name", "email": "Email address", "phone": "Phone number", "dob": "Date of birth",
          "aadhaar": "Aadhaar number", "pan": "PAN (Permanent Account Number)",
          "parent_pan": "Parent's PAN (Permanent Account Number)"}
LAYERS = {"db": "Database", "api": "API responses"}  # request: entries are third parties, listed under "Shared with"

# Used for the cached golden result and the fix route. No edits: the patch is generated from the scan, not a fixed snippet.
NOTICE_ALIGN = Template(check="notice_drift", golden_id="NOTICE", scanner="notice_drift", edits=())


def label(field: str) -> str:
    return LABELS.get(field, field.replace("_", " ").capitalize())


def pending_inputs(drift: NoticeDrift) -> list[str]:
    return [f"purpose for {f}" for f in drift.undeclared]


def render_section(drift: NoticeDrift) -> str:
    where = {o.field: o.where for o in drift.observed}
    items, hosts = [], []
    for field in drift.undeclared:
        layers = list(dict.fromkeys(LAYERS[w.split(":", 1)[0]] for w in where.get(field, []) if w.split(":", 1)[0] in LAYERS))
        hosts += [w.split(":", 1)[1] for w in where.get(field, []) if w.startswith("request:")]
        items.append(f"      <li><strong>{escape(label(field))}</strong><br>"
                     f"Handled in: {escape(', '.join(layers) or 'not shown')}<br>"
                     f"Purpose: {escape(PURPOSE_PLACEHOLDER)}</li>")
    shared = ""
    if hosts:
        shared = ("    <h3>Shared with</h3>\n    <ul>\n"
                  + "\n".join(f"      <li>{escape(h)}</li>" for h in dict.fromkeys(hosts)) + "\n    </ul>\n")
    return (f'  {MARKER}\n  <div class="card">\n    <h2>Other personal data we handle</h2>\n'
            "    <p>Added by DPDP Lens for the owner to review. Every purpose below must be filled in before this notice is published.</p>\n"
            "    <ul>\n" + "\n".join(items) + "\n    </ul>\n" + shared + f"  </div>\n  {END_MARKER}\n")


def align_notice(html: str, drift: NoticeDrift) -> str:
    """The notice with the section added just before </body>. Unchanged if it has the section already or nothing is undeclared."""
    if MARKER in html or not drift.undeclared:
        return html
    section = render_section(drift)
    i = html.lower().rfind("</body>")
    return html + section if i < 0 else html[:i] + section + html[i:]
