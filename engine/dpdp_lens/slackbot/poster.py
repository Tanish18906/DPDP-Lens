"""Every Slack write goes through here: about one new message per second per channel, and a retry after Retry-After on a 429."""
import threading
import time

from slack_sdk.errors import SlackApiError


class Poster:
    def __init__(self, client, interval: float = 1.0, sleep=time.sleep, clock=time.monotonic, retries: int = 5):
        self.client, self.interval, self.sleep, self.clock, self.retries = client, interval, sleep, clock, retries
        self._locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}
        self._guard = threading.Lock()

    def _call(self, fn, **kw):
        for attempt in range(self.retries + 1):
            try:
                return fn(**kw)
            except SlackApiError as e:
                r = e.response
                if getattr(r, "status_code", None) != 429 or attempt == self.retries:
                    raise
                headers = {str(k).lower(): v for k, v in (getattr(r, "headers", None) or {}).items()}
                try:
                    wait = float(headers.get("retry-after", 1))
                except (TypeError, ValueError):
                    wait = 1.0
                self.sleep(max(wait, 1.0))

    def post(self, channel: str, text: str, blocks=None, thread_ts: str | None = None) -> str:
        """Returns the message ts."""
        with self._guard:
            lock = self._locks.setdefault(channel, threading.Lock())
        with lock:  # one sender per channel at a time, so the spacing below holds
            wait = self._last.get(channel, float("-inf")) + self.interval - self.clock()
            if wait > 0:
                self.sleep(wait)
            try:
                res = self._call(self.client.chat_postMessage, channel=channel, text=text, blocks=blocks, thread_ts=thread_ts)
            finally:
                self._last[channel] = self.clock()
        return res["ts"]

    def update(self, channel: str, ts: str, text: str, blocks=None) -> None:
        self._call(self.client.chat_update, channel=channel, ts=ts, text=text, blocks=blocks)

    def ephemeral(self, channel: str, user: str, text: str, blocks=None) -> None:
        self._call(self.client.chat_postEphemeral, channel=channel, user=user, text=text, blocks=blocks)
