"""Thin HTTP client for the engine (master section 9). The bot talks to the engine only through this file."""
import httpx

from .redact import redact


class EngineError(Exception):
    """status 0 means the engine could not be reached. `detail` is the engine's own text and is safe to show once redacted."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, redact(detail)


class Engine:
    def __init__(self, base_url: str, token: str, client: httpx.Client | None = None, timeout: float = 15):
        """`client` is for tests (a Starlette TestClient is an httpx.Client). Its base URL then wins."""
        self.token, self.timeout = token, timeout
        self.http = client or httpx.Client(base_url=base_url)

    def _call(self, method: str, path: str, *, body=None, params=None, write=False, timeout=None):
        headers = {"X-DPDP-Token": self.token} if write else {}
        try:
            r = self.http.request(method, path, json=body, params=params, headers=headers, timeout=timeout or self.timeout)
        except httpx.HTTPError as e:
            raise EngineError(0, f"engine unreachable ({type(e).__name__})") from None
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except (ValueError, AttributeError):
                detail = r.text
            raise EngineError(r.status_code, detail if isinstance(detail, str) else str(detail))
        return r.json()

    # reads
    def repos(self): return self._call("GET", "/repos")
    def health(self, repo_id): return self._call("GET", f"/repos/{repo_id}/health")
    def diff(self, repo_id): return self._call("GET", f"/repos/{repo_id}/diff")  # the latest scan against the baseline
    def delta(self, scan_id): return self._call("GET", f"/scans/{scan_id}/delta")
    def scan_result(self, scan_id): return self._call("GET", f"/scan/{scan_id}")  # 200 while running or done, 500 when the scan failed
    def finding(self, human_id): return self._call("GET", f"/findings/{human_id}")
    def outbox(self, after: int): return self._call("GET", "/outbox", params={"after": after})

    # writes
    def connect(self, full_name, branch, channel, actor):
        return self._call("POST", "/repos", body={"full_name": full_name, "branch": branch or "", "slack_channel": channel, "actor": actor}, write=True)

    def scan(self, repo_id, actor):
        return self._call("POST", f"/repos/{repo_id}/scan", body={"mode": "static", "actor": actor}, write=True)

    def set_status(self, human_id, status, reason, actor):
        return self._call("PATCH", f"/findings/{human_id}/status", body={"status": status, "reason": reason, "actor": actor}, write=True)

    def link(self, human_id, channel, ts):
        return self._call("PUT", f"/findings/{human_id}/slack", body={"channel": channel, "ts": ts}, write=True)

    def fix(self, human_id, actor):
        return self._call("POST", f"/findings/{human_id}/fix", params={"mode": "live"}, body={"actor": actor}, write=True, timeout=90)

    def baseline(self, repo_id, actor): return self._call("POST", f"/repos/{repo_id}/baseline", body={"actor": actor}, write=True)

    def watch(self, repo_id, minutes, actor):
        return self._call("POST", f"/repos/{repo_id}/watch", body={"minutes": minutes, "actor": actor}, write=True)
