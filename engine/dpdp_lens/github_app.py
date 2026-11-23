"""GitHub App access (block 08): the app JWT, installation tokens, the repositories an installation shares, and the signed
state that ties a GitHub install back to a link this engine handed out.

The private key is read from the file GITHUB_APP_PRIVATE_KEY_PATH when a JWT is built, never copied, logged or stored, and a
key file that group or others can read is refused. Installation tokens (ghs_) live in memory only. The HTTP client is injected,
so tests need no network. Read-only: the app has Contents and Metadata read permissions and no webhook."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives import serialization

API = "https://api.github.com"
INSTALL_BASE = "https://github.com/apps"
STATE_TTL = 15 * 60  # seconds a signed install link stays valid
JWT_BACK = 60  # iat is set this far in the past: GitHub allows for clock drift that way
JWT_TTL = 9 * 60  # GitHub's maximum is 10 minutes
REFRESH_MARGIN = 5 * 60  # a cached installation token is replaced this long before it expires
MAX_PAGES = 50  # 5000 repositories: more than any single-tenant demo needs


class GitHubAppError(Exception):
    """kind: config (not set up, bad key), notfound (installation gone), auth (GitHub refused the credentials), api, network.
    The message never holds a key, a JWT or a token."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def read_key(path: str) -> str:
    """The PEM text of the private key. Refuses a missing file, one that group or others can read, and one that is not a private key."""
    try:
        mode = Path(path).stat().st_mode
        pem = Path(path).read_text()
    except (OSError, ValueError):
        raise GitHubAppError("config", f"cannot read the private key file {path}") from None
    if mode & 0o077:
        raise GitHubAppError("config", f"{path} can be read by group or others: run chmod 600 on it")
    try:
        serialization.load_pem_private_key(pem.encode(), None)
    except Exception:  # the cryptography error text can quote nothing secret, but we say nothing about the content either
        raise GitHubAppError("config", f"{path} does not hold a PEM private key") from None
    return pem


def build_jwt(app_id: str, pem: str, now: float | None = None) -> str:
    now = int(time.time() if now is None else now)
    return jwt.encode({"iat": now - JWT_BACK, "exp": now + JWT_TTL, "iss": str(app_id)}, pem, algorithm="RS256")


def sign_state(secret: str, now: float | None = None, ttl: int = STATE_TTL) -> str:
    """payload.signature. The payload is an expiry time and a random nonce, the signature is an HMAC with `secret`."""
    now = time.time() if now is None else now
    payload = base64.urlsafe_b64encode(json.dumps({"exp": int(now + ttl), "n": secrets.token_hex(8)}).encode()).decode().rstrip("=")
    return f"{payload}.{hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()}"


def check_state(secret: str, state: str, now: float | None = None) -> bool:
    """True for a state we signed that has not expired. Replay inside the 15 minutes is harmless: the installation itself is
    verified with the app JWT, so a state only proves the visitor came through a link we made."""
    payload, _, sig = (state or "").partition(".")
    if not secret or not payload or not sig:
        return False
    if not hmac.compare_digest(sig, hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()):
        return False
    try:
        exp = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"]
        return (time.time() if now is None else now) < int(exp)
    except (ValueError, KeyError, TypeError):
        return False


class GitHubApp:
    def __init__(self, app_id: str, key_path: str, slug: str, client: httpx.Client | None = None, api: str = API, clock=time.time):
        self.app_id, self.key_path, self.slug, self.api, self.clock = str(app_id), key_path, slug, api.rstrip("/"), clock
        self.http = client or httpx.Client()
        self._tokens: dict[int, tuple[str, float]] = {}  # installation id -> (token, expiry as epoch seconds)
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, env=None, **kw) -> "GitHubApp | None":
        """None unless all three settings are present, so an engine without the app behaves exactly as before."""
        env = os.environ if env is None else env
        app_id, key_path, slug = (env.get(n, "").strip() for n in ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH", "GITHUB_APP_SLUG"))
        return cls(app_id, key_path, slug, **kw) if app_id and key_path and slug else None

    def app_jwt(self) -> str:
        return build_jwt(self.app_id, read_key(self.key_path), self.clock())

    def install_url(self, state: str) -> str:
        return f"{INSTALL_BASE}/{self.slug}/installations/new?state={state}"

    def _req(self, method: str, path: str, bearer: str, params=None, json=None):
        try:
            r = self.http.request(method, f"{self.api}{path}", params=params, json=json, timeout=15, headers={
                "Authorization": f"Bearer {bearer}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        except httpx.HTTPError as e:
            raise GitHubAppError("network", f"cannot reach GitHub ({type(e).__name__})") from None
        if r.status_code >= 400:
            try:
                why = " ".join(str(r.json().get("message", "")).split())[:120]
            except (ValueError, AttributeError):
                why = ""
            kind = "notfound" if r.status_code == 404 else "auth" if r.status_code in (401, 403) else "api"
            raise GitHubAppError(kind, f"GitHub answered {r.status_code}" + (f": {why}" if why else ""))
        return r.json()

    def api_call(self, method: str, path: str, token: str, params=None, json=None):
        """One REST call with a token the caller holds (the downscoped pull request token). Raises GitHubAppError."""
        return self._req(method, path, token, params, json)

    def pr_token(self, installation_id: int, repo_name: str) -> str:
        """A fresh installation token for the pull request action only: limited to ONE repository (its name, without the owner) and to
        contents:write and pull_requests:write. Never cached and never used for a scan or a clone: the caller uses it once and drops it."""
        data = self._req("POST", f"/app/installations/{int(installation_id)}/access_tokens", self.app_jwt(),
                         json={"repositories": [repo_name], "permissions": {"contents": "write", "pull_requests": "write"}})
        return data["token"]

    def info(self) -> dict:
        """GET /app: the app this key belongs to (its slug, name, id)."""
        return self._req("GET", "/app", self.app_jwt())

    def installation(self, installation_id: int) -> dict:
        """GET /app/installations/{id}: {installation_id, account_login, account_type}. Raises notfound when it does not exist."""
        data = self._req("GET", f"/app/installations/{int(installation_id)}", self.app_jwt())
        account = data.get("account") or {}
        return {"installation_id": int(data["id"]), "account_login": str(account.get("login", "")), "account_type": str(account.get("type", ""))}

    def token(self, installation_id: int) -> str:
        """An installation access token (ghs_), cached until 5 minutes before it expires."""
        iid = int(installation_id)
        with self._lock:
            cached = self._tokens.get(iid)
            if cached and cached[1] - REFRESH_MARGIN > self.clock():
                return cached[0]
        data = self._req("POST", f"/app/installations/{iid}/access_tokens", self.app_jwt())
        expiry = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
        with self._lock:
            self._tokens[iid] = (data["token"], expiry)
        return data["token"]

    def repos(self, installation_id: int) -> list[dict]:
        """Every repository the installation shares: [{full_name, private, default_branch}], sorted by name. Live from GitHub."""
        token, out = self.token(installation_id), []
        for page in range(1, MAX_PAGES + 1):
            data = self._req("GET", "/installation/repositories", token, params={"per_page": 100, "page": page})
            batch = data.get("repositories", [])
            out += [{"full_name": r["full_name"], "private": bool(r.get("private")), "default_branch": r.get("default_branch", "")} for r in batch]
            if len(batch) < 100 or len(out) >= data.get("total_count", 0):
                break
        return sorted(out, key=lambda r: r["full_name"].lower())
