"""Bot settings. Everything comes from the environment (docs/dpdp-evolve master section 11), never from argv or a file."""
import os
from dataclasses import dataclass


def _set(raw: str, lower: bool = False) -> frozenset:
    return frozenset((x.strip().lower() if lower else x.strip()) for x in raw.split(",") if x.strip())


@dataclass(frozen=True)
class Config:
    engine_url: str = "http://127.0.0.1:8100"
    dashboard_url: str = "http://localhost:5174"
    api_token: str = ""
    bot_token: str = ""
    app_token: str = ""
    channel: str = ""
    allowed_channels: frozenset = frozenset()  # SLACK_ALLOWED_CHANNELS, or just SLACK_CHANNEL when that is not set
    approvers: frozenset = frozenset()
    fix_repos: frozenset = frozenset()  # lower case full names: only these get a Fix and verify button (the engine checks too)

    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        channel = env.get("SLACK_CHANNEL", "").strip()
        return cls(
            engine_url=env.get("ENGINE_URL", "http://127.0.0.1:8100").rstrip("/"),
            dashboard_url=env.get("DASHBOARD_URL", "http://localhost:5174").rstrip("/"),
            api_token=env.get("DPDP_API_TOKEN", ""), bot_token=env.get("SLACK_BOT_TOKEN", ""), app_token=env.get("SLACK_APP_TOKEN", ""),
            channel=channel, allowed_channels=_set(env.get("SLACK_ALLOWED_CHANNELS", "")) or _set(channel),
            approvers=_set(env.get("SLACK_APPROVERS", "")), fix_repos=_set(env.get("DPDP_FIX_REPOS", ""), lower=True))

    def missing(self) -> list[str]:
        """Names (never values) of the settings the bot cannot start without."""
        need = {"SLACK_BOT_TOKEN": self.bot_token, "SLACK_APP_TOKEN": self.app_token, "DPDP_API_TOKEN": self.api_token,
                "SLACK_CHANNEL": self.allowed_channels}
        return [name for name, value in need.items() if not value]
