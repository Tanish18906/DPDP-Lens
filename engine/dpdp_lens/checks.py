"""One registry of every check: the source of truth for layer, severity, wording and fix text (docs/15 D2).
Clauses stay in contract/clauses.json. A test keeps both files on the same check ids."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    id: str
    layer: str
    severity: str
    title: str
    detection: str  # one sentence: what the scanner looks for
    recommendation: str  # static text, one to two sentences
    reason: str  # template for severity_reason, filled by reason() from facts the scanner already has
    fixable: bool  # True when the engine has a verified fix template


_CHECKS = [
    Check("api_pii_exposure", "api", "critical", "Public API endpoint exposes personal data",
          "A GET route answers without a login and returns personal data.",
          "Require authentication and authorisation on this route and return only the fields the caller needs.",
          "Critical: no login needed, {n} records returned with {fields}.", True),
    Check("api_idor", "api", "critical", "Any logged-in user can read other users' records",
          "A logged-in user can read another user's record by changing the id in the route.",
          "Check on the server that the logged in user owns the record, or is an admin, before returning it.",
          "Critical: a logged in user read another user's record.", True),
    Check("log_pii", "code", "high", "Personal data written to logs",
          "A logging call in the source includes personal data fields.",
          "Log an internal id instead of personal data, and mask any value that must be logged.",
          "High: {fields} written to a log in plain text.", True),
    Check("db_plaintext_pii", "db", "high", "Aadhaar or PAN stored in plaintext columns",
          "A table column holds Aadhaar or PAN values as readable text.",
          "Encrypt Aadhaar and PAN at rest, or store a token or masked form, and limit who can read the columns.",
          "High: {fields} stored unencrypted in {table}.", False),
    Check("tracker_before_consent", "browser", "high", "Tracking script loads before any consent",
          "The signup page requests a known tracker host before any click.",
          "Do not load third party trackers until the user gives clear consent. Load them only from the consent handler.",
          "High: {host} ({category}) is contacted before any consent click.", True),
    Check("consent_bundled", "browser", "medium", "Consent box is pre-ticked or bundled with marketing",
          "The consent checkbox is pre ticked, or one box covers terms and marketing.",
          "Use a separate, unticked consent box for each purpose and itemise the data and purposes in the notice.",
          "Medium: consent is pre ticked and bundled with the terms.", True),
    Check("erasure_incomplete", "db", "high", "Personal data is still stored after deletion",
          "After a delete request, a synthetic user's data is still in the database.",
          "On deletion, remove personal data from every table and backup copy, except logs you must keep by law.",
          "High: personal data remains in {tables} after delete.", True),
    Check("children_no_parental_consent", "api", "high", "Under-18 signup accepted with no parental consent",
          "A signup for a 14 year old is accepted with no parent data.",
          "Require verifiable parental consent before accepting an under 18 signup.",
          "High: a 14 year old signup was accepted with no parental step.", True),
    Check("missing_contact", "notice", "low", "No DPO or grievance contact published",
          "No page lists a data protection officer or grievance contact with an email or phone.",
          "Publish a contact for a data protection officer or other person, and the grievance process, on the site and in the notice.",
          "Low: no data protection contact or grievance process was found.", False),
    Check("notice_drift", "notice", "medium", "Collected personal data is not listed in the privacy notice",
          "The app handles personal data fields that the public notice does not list.",
          "Update the notice to list every personal data field collected and why, or stop collecting the extra fields.",
          "Medium: {n} collected fields are not in the notice.", False),
    Check("config_secret_committed", "config", "high", "Secret value written in a file in the repository",
          "A key named like a secret, password, token or API key has a literal value in a config file or source.",
          "Remove the secret from the repository, rotate it, and load secrets from the environment or a secret manager.",
          "High: {n} secret value(s) are written in plain text in {file}.", False),
    Check("config_env_in_image", "config", "high", "Secrets are baked into the container image",
          "A Dockerfile copies a .env file, or sets a secret with ENV or ARG.",
          "Do not copy .env or bake secrets into the image. Pass them at run time.",
          "High: the image build {what}.", False),
    Check("config_container_root", "config", "medium", "Container runs as root",
          "A Dockerfile has no USER instruction, or the last USER is root.",
          "Add a non root USER to the Dockerfile.",
          "Medium: the container runs as root.", False),
    Check("config_cors_wildcard", "config", "medium", "CORS allows every origin",
          "allow_origins holds \"*\", or the Access-Control-Allow-Origin header is *.",
          "Allow only the exact front end origins you need. Never combine a wildcard with credentials.",
          "Medium: any origin is allowed{creds}.", False),
    Check("config_debug_enabled", "config", "medium", "Debug mode is on",
          "DEBUG is true in an env file, debug=True is in app code, or a container command uses reload.",
          "Turn debug off outside local development.",
          "Medium: debug mode is on in {file}.", False),
    Check("config_db_exposed", "config", "high", "Database port is published to every network interface",
          "A compose file publishes a database port without binding it to 127.0.0.1.",
          "Do not publish the database port. Keep it on the internal network or bind to 127.0.0.1, and use strong credentials.",
          "High: {service} database port {port} is published on all interfaces{creds}.", False),
    Check("fe_pii_in_storage", "frontend", "medium", "Personal data kept in browser storage",
          "localStorage or sessionStorage setItem is called with a key or value that names personal data.",
          "Do not keep personal data in browser storage. Keep it on the server and use short lived session tokens.",
          "Medium: {fields} are kept in {storage}.", False),
]

CHECKS: dict[str, Check] = {c.id: c for c in _CHECKS}


def reason(check_id: str, **facts) -> str:
    return CHECKS[check_id].reason.format(**facts)
