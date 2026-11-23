"""Strip secrets from anything that is logged or shown in Slack: Slack and GitHub tokens (ghs_ installation tokens too), JWTs, and the exact values of the
token environment variables (so DPDP_API_TOKEN is removed even though it has no fixed prefix)."""
import logging
import os
import re

_TOKEN = re.compile(r"xox[a-zA-Z]-[\w-]+|xapp-[\w-]+|gh[pousr]_\w+|github_pat_\w+|eyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]{6,}")
_ENV = ("DPDP_API_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "GITHUB_TOKEN")
_extra: set[str] = set()


def add_secret(value: str) -> None:
    """Also strip this exact value (a token that was passed in code, not read from the environment)."""
    if value and len(value) >= 4:
        _extra.add(value)


def redact(text) -> str:
    out = str(text)
    for value in (*(os.environ.get(n, "") for n in _ENV), *_extra):
        if len(value) >= 4:
            out = out.replace(value, "[redacted]")
    return _TOKEN.sub("[redacted]", out)


class RedactFilter(logging.Filter):
    """Put on every log handler: the message is formatted, redacted and stored back, so no handler sees a token."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = redact(record.getMessage()), ()
        return True


def install_log_filter() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, RedactFilter) for f in handler.filters):
            handler.addFilter(RedactFilter())
