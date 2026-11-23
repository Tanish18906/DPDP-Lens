"""Policy as code (EVOLVE block 02): a versioned file decides pass, warn or fail per finding. Pure and deterministic.
The policy only names check ids. Clauses stay in contract/clauses.json, wording in checks.py."""
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, field_validator

from .checks import CHECKS
from .models import Layer, ScanResult, Severity

Action = Literal["block", "warn", "info"]
Decision = Literal["pass", "warn", "fail", "incomplete"]
DEFAULT_POLICY = Path(__file__).resolve().parent / "policies" / "default.yaml"
DEFAULT_ACTION: dict[str, str] = {"critical": "block", "high": "block", "medium": "warn", "low": "info"}
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
FP = re.compile(r"^[0-9a-f]{16}$")


class PolicyError(ValueError):
    """A policy, project config or baseline file that cannot be used. Never silently ignored: the CLI exits 2."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a misspelt key is an error, not a rule that quietly does nothing


class Rule(_Strict):
    action: Action
    severity_override: Optional[Severity] = None


class Policy(_Strict):
    policy_id: str = Field(min_length=1)
    version: str
    effective_date: date
    description: str = ""
    source: str = ""
    rules: dict[str, Rule]
    _sha256: str = PrivateAttr("")  # of the file the policy was loaded from

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not SEMVER.fullmatch(v):
            raise ValueError("version must look like 1.0.0")
        return v

    @field_validator("rules")
    @classmethod
    def _known_checks(cls, rules: dict[str, Rule]) -> dict[str, Rule]:
        unknown = sorted(set(rules) - set(CHECKS))
        if unknown:
            raise ValueError(f"unknown check id: {', '.join(unknown)}")
        return rules

    @property
    def sha256(self) -> str:
        return self._sha256


class Suppression(_Strict):
    fingerprint: str
    reason: str = Field(min_length=1, max_length=300)
    by: str = Field(min_length=1, max_length=100)

    @field_validator("fingerprint")
    @classmethod
    def _fp(cls, v: str) -> str:
        if not FP.fullmatch(v):
            raise ValueError("fingerprint must be 16 hex characters")
        return v


class ProjectConfig(_Strict):
    """.dpdp-lens.yml in the scanned repo. Relative paths are relative to the folder of the config file."""
    policy: str = "default"
    block_on: list[Severity] = []  # these severities block, whatever the policy says
    warn_on: list[Severity] = []  # these warn (block_on wins when a severity is in both)
    categories: list[Layer] = ["code", "config", "frontend"]
    new_only: bool = False
    baseline: str = ".dpdp-baseline.json"
    suppress: list[Suppression] = []


class EvalItem(BaseModel):
    fingerprint: str
    check: str
    severity: Severity  # after the policy's severity_override
    action: Action
    is_new: bool
    suppressed: bool


class Evaluation(BaseModel):
    decision: Decision
    policy_id: str
    policy_version: str
    policy_sha256: str
    new_only: bool
    items: list[EvalItem]
    excluded: int = 0  # open findings left out because their layer is not in categories

    def blocking(self) -> list[EvalItem]:
        """Items that made the decision fail: with new_only, only the new ones count."""
        return [i for i in self.items if i.action == "block" and not i.suppressed and (i.is_new or not self.new_only)]


def _load_yaml(path: Path) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
        data = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as e:
        raise PolicyError(f"{path}: {e}") from None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise PolicyError(f"{path}: expected a mapping at the top level")
    return data, hashlib.sha256(raw).hexdigest()


def _problem(path: Path, e: ValidationError) -> PolicyError:
    first = e.errors()[0]
    where = ".".join(str(p) for p in first["loc"])
    return PolicyError(f"{path}: {where}: {first['msg']}" if where else f"{path}: {first['msg']}")


def load_policy(path: Path | str = DEFAULT_POLICY) -> Policy:
    path = Path(path)
    data, digest = _load_yaml(path)
    try:
        policy = Policy.model_validate(data)
    except ValidationError as e:
        raise _problem(path, e) from None
    policy._sha256 = digest
    return policy


def load_config(path: Path | str | None) -> ProjectConfig:
    """path None: defaults. A missing file is the caller's decision (the CLI only passes a path that exists or was asked for)."""
    if path is None:
        return ProjectConfig()
    path = Path(path)
    data, _ = _load_yaml(path)
    try:
        return ProjectConfig.model_validate(data)
    except ValidationError as e:
        raise _problem(path, e) from None


def load_baseline(path: Path | str) -> set[str]:
    path = Path(path)
    try:
        data = json.loads(path.read_text())
        return {e["fp"] for e in data["fingerprints"]}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise PolicyError(f"{path}: not a baseline file ({type(e).__name__}); create one with --write-baseline") from None


def resolve(finding_check: str, finding_severity: str, policy: Policy, cfg: ProjectConfig) -> tuple[str, str]:
    """(severity, action) of one finding. Order: policy rule (and its severity_override), then the project's block_on and warn_on."""
    rule = policy.rules.get(finding_check)
    severity = rule.severity_override if rule and rule.severity_override else finding_severity
    action = rule.action if rule else DEFAULT_ACTION[severity]  # a custom policy may leave a check out: severity default
    if severity in cfg.block_on:
        action = "block"
    elif severity in cfg.warn_on:
        action = "warn"
    return severity, action


def evaluate(scan: ScanResult, policy: Policy, project_cfg: Optional[ProjectConfig] = None, suppressed_fps=(),
             baseline_fps=None, new_only: bool = False) -> Evaluation:
    """baseline_fps None: every finding is new. new_only: findings in the baseline do not change the decision.
    An incomplete scan is always "incomplete", never pass, whatever it found."""
    cfg = project_cfg or ProjectConfig()
    suppressed = set(suppressed_fps)
    items, excluded = [], 0
    for f in scan.findings:
        if f.status != "open":
            continue
        if f.layer not in cfg.categories:
            excluded += 1
            continue
        severity, action = resolve(f.check, f.severity, policy, cfg)
        items.append(EvalItem(fingerprint=f.fingerprint, check=f.check, severity=severity, action=action,
                              is_new=baseline_fps is None or f.fingerprint not in baseline_fps, suppressed=f.fingerprint in suppressed))
    live = [i for i in items if not i.suppressed and (i.is_new or not new_only)]
    decision = ("incomplete" if not scan.complete else "fail" if any(i.action == "block" for i in live)
                else "warn" if any(i.action == "warn" for i in live) else "pass")
    return Evaluation(decision=decision, policy_id=policy.policy_id, policy_version=policy.version, policy_sha256=policy.sha256,
                      new_only=new_only, items=items, excluded=excluded)
