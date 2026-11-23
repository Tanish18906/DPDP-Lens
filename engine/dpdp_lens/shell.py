"""Interactive shell (phase C1). Inline output, no full screen: "●" action lines, "⎿" result lines, a spinner,
a slash command menu, a coloured diff. It only calls what the engine already has: run_scan, apply_fix, render_report.

Security: finding text can come from the scanned app. Every such string goes through clean() (ANSI and OSC
escapes, control characters and bidi marks removed) and is then put in a rich Text object, which never parses
markup. That is why rich.markup.escape is not applied: on a Text it would only add visible backslashes."""
import argparse
import re
import shlex
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import checks_doc
from .api import FixError, apply_fix, default_repo_root
from .fixer.verify import GOLDEN_DIR, verify_fix
from .models import ScanResult
from .netutil import is_local
from .report import render_report
from .runner import run_scan

ACCENT = "#14b8a6"
SEV_STYLE = {"critical": "bold red", "high": "red", "medium": "yellow", "low": "blue"}
SEV_ORDER = list(SEV_STYLE)
DEFAULT_TARGET = "http://localhost:8000"  # TutorNest demo values
DEFAULT_REPO = "target-app/backend"
DEFAULT_DB = "target-app/backend/demo.db"
REPORT_PATH = "reports/last-scan.html"
FOOTER = "Readiness report, not a compliance certificate."

# scanner step -> (label shown, verb shown while it runs)
STEPS = {
    "api_scan": ("API", "Probing the API"), "idor_probe": ("IDOR", "Probing the API"),
    "db_scan": ("DATABASE", "Reading the database"), "log_scan": ("CODE", "Tracing the code"),
    "erasure_scan": ("ERASURE", "Probing the API"), "children_scan": ("CHILDREN", "Probing the API"),
    "contact_scan": ("CONTACT", "Comparing the notice"), "browser_scan": ("BROWSER", "Driving the browser"),
    "notice_drift": ("NOTICE", "Comparing the notice"), "config_scan": ("CONFIG", "Checking config"),
    "frontend_scan": ("FRONT END", "Reading the front end"), "consent_scan": ("CONSENT", "Looking for consent"),
}

COMMANDS = {
    "/scan": "scan the target [--target URL] [--repo PATH] [--db PATH]",
    "/findings": "list the findings of the last scan",
    "/show": "show one finding: /show F-001",
    "/fix": "verified fix on a copy: /fix F-001 [--cached]",
    "/report": "write the HTML report [path]",
    "/checks": "list every check and its clauses",
    "/status": "show target, last scan and score",
    "/help": "list the commands",
    "/clear": "clear the screen",
    "/exit": "leave the shell",
}

# ---------------------------------------------------------------- safe text

_ESCAPES = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-Z\\-_]?")
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


def clean(value, nl: bool = False) -> str:
    """Printable text only. Newlines stay only when nl is True (the /show view), tabs become spaces."""
    s = _ESCAPES.sub("", str(value)).replace("\t", "    ")  # _CONTROLS keeps \n, so only the no-newline case needs a step
    return _CONTROLS.sub("", s if nl else s.replace("\n", " "))


def t(value, style: str = "", nl: bool = False) -> Text:
    return Text(clean(value, nl), style=style)


# ---------------------------------------------------------------- layout helpers

def _grid(*widths):
    g = Table.grid(expand=True, padding=0)
    for w in widths:
        g.add_column(width=w, no_wrap=True) if w else g.add_column(ratio=1, overflow="fold")
    return g


def bullet(dot: Text, body: Text) -> Table:
    g = _grid(2, 0)
    g.add_row(dot, body)
    return g


def rline(*parts, label: str = "") -> Table:
    """A result line: 2 space indent, "⎿", then the text. Long text wraps under the text, not under the ⎿."""
    body = Text.assemble(*parts) if parts else Text()
    if label:
        g = _grid(4, 10, 0)
        g.add_row(Text("  ⎿ ", style="dim"), Text(label, style="dim"), body)
    else:
        g = _grid(4, 0)
        g.add_row(Text("  ⎿ ", style="dim"), body)
    return g


def sev_text(sev: str) -> Text:
    return Text(sev, style=SEV_STYLE.get(sev, ""))


def score_style(score: int) -> str:
    return "red" if score < 40 else "yellow" if score < 70 else "green"


def where(f) -> str:
    loc = f.evidence.location
    if loc.file:
        return f"{loc.file}:{loc.line}" if loc.line else loc.file
    if loc.table:
        return f"{loc.table}.{loc.column}" if loc.column else loc.table
    return loc.url


class Task:
    """One "●" action with its "⎿" lines and a spinner line while a step runs. On a terminal it is a rich Live
    region (the dot turns green or red when done). Piped, it is plain lines and nothing is redrawn."""

    def __init__(self, console: Console, label: str, detail: str = "", note: str = "", live: bool = True):
        self.console, self.label, self.detail, self.note = console, label, detail, note
        self.rows: list = []
        self.state = "running"  # running | ok | error
        self.verb, self.since = None, 0.0
        self.live = Live(self, console=console, refresh_per_second=8, vertical_overflow="visible") \
            if live and console.is_terminal else None

    def _header(self):
        dot = Text("●", style={"running": ACCENT, "ok": "green", "error": "red"}[self.state])
        return bullet(dot, Text.assemble((self.label, "bold"), ("  " if self.detail else "", ""), t(self.detail), ("  " + self.note if self.note else "", "dim")))

    def __rich_console__(self, console, options):
        yield self._header()
        yield from self.rows
        if self.verb:
            yield bullet(Text("✻", style=ACCENT), Text.assemble(
                (f"{self.verb}… ", ""), (f"({int(time.monotonic() - self.since)}s)", "dim")))

    def __enter__(self):
        self.live.start() if self.live else self.console.print(self._header())
        return self

    def __exit__(self, exc_type, exc, tb):
        self.verb = None
        self.state = "error" if exc_type or self.state == "error" else "ok"
        if self.live:
            self.live.stop()
        return False

    def add(self, row):
        self.rows.append(row)
        if not self.live:
            self.console.print(row)

    def spin(self, verb: str | None):
        self.verb, self.since = verb, time.monotonic()

    def fail(self, text: str):
        self.state = "error"
        self.add(rline((clean(text), "red")))


# ---------------------------------------------------------------- printing a scan

def print_findings(console: Console, scan: ScanResult):
    for f in sorted(scan.findings, key=lambda f: (SEV_ORDER.index(f.severity), f.id)):
        fixed = f.status == "verified_fixed"
        console.print(bullet(Text("●", style="green" if fixed else SEV_STYLE[f.severity]), Text.assemble(
            t(f.id), "  ", (f.severity, "dim" if fixed else SEV_STYLE[f.severity]), "  ", t(f.title),
            ("  ✓ fixed", "green") if fixed else "")))
        parts = [p for p in (f.layer, where(f), ", ".join(c.ref for c in f.clauses)) if p]
        console.print(rline((clean(" · ".join(parts)), "dim")))
    print_summary(console, scan)


def print_summary(console: Console, scan: ScanResult):
    c = scan.counts
    console.print(Text.assemble("Score ", (f"{scan.score}/100", f"bold {score_style(scan.score)}"),
                                f" · {c.critical} critical · {c.high} high · {c.medium} medium · {c.low} low"))
    console.print(Text(FOOTER, style="dim"))


def print_diff(console: Console, diff: str):
    lines = diff.splitlines()
    old = new = 0
    in_hunk = False
    for i, line in enumerate(lines):
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            in_hunk = False
        if not in_hunk and (line.startswith(("--- ", "+++ ", "diff ", "index "))):
            console.print(t(line, "dim"))
        elif line.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line)
            old, new = (int(m[1]), int(m[2])) if m else (0, 0)
            in_hunk = True
            console.print(t(line, "dim"))
        elif line.startswith("-"):
            console.print(_diff_row(old, "-", line[1:], "on #4a1218"))
            old += 1
        elif line.startswith("+"):
            console.print(_diff_row(new, "+", line[1:], "on #12351f"))
            new += 1
        elif line.startswith(" "):
            console.print(_diff_row(new, " ", line[1:], "dim"))
            old, new = old + 1, new + 1
        else:
            console.print(t(line, "dim"))


def _diff_row(number: int, sign: str, text: str, style: str) -> Table:
    g = _grid(5, 2, 0)
    g.add_row(Text(str(number).rjust(4) + " ", style="dim"), Text(sign), t(text), style=style)
    return g


def patched_files(diff: str) -> list[str]:
    return [m[1] for line in (diff or "").splitlines() if (m := re.match(r"\+\+\+ (?:b/)?(\S+)", line))]


# ---------------------------------------------------------------- the shell

class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


@dataclass
class Shell:
    console: Console
    root: Path = field(default_factory=default_repo_root)
    scan_fn: object = run_scan
    fix_fn: object = verify_fix
    golden_dir: object = GOLDEN_DIR
    scan: ScanResult | None = None
    inputs: tuple | None = None  # (repo_path, db_path) of the last /scan
    target: str = DEFAULT_TARGET
    fix_modes: dict = field(default_factory=dict)
    n_scans: int = 0

    # -- state
    def load(self, scan: ScanResult, inputs: tuple | None = None):
        self.scan, self.inputs, self.target, self.fix_modes = scan, inputs, scan.target, {}

    def toolbar(self) -> str:
        host = urlparse(self.target).netloc or self.target
        if self.scan is None:
            return clean(f"{host} · no scan yet")
        open_n = sum(f.status == "open" for f in self.scan.findings)
        return clean(f"{host} · {self.scan.scan_id} · score {self.scan.score} · {open_n} open")

    def _path(self, p: str) -> Path:
        p = Path(p).expanduser()
        return p if p.is_absolute() else self.root / p

    # -- dispatch
    def handle(self, line: str) -> bool:
        """Run one input line. Returns False when the shell should exit."""
        line = line.strip()
        if not line:
            return True
        if not line.startswith("/"):
            self.err("Commands start with /. try /help")
            return True
        try:
            parts = shlex.split(line)
        except ValueError as e:
            self.err(f"Cannot read that line: {e}")
            return True
        name, args = parts[0].lower(), parts[1:]
        if name in ("/exit", "/quit"):
            return False
        fn = getattr(self, "cmd_" + name[1:], None) if name in COMMANDS else None
        if fn is None:
            self.err(f"Unknown command: {name}. try /help")
            return True
        try:
            fn(args)
        except KeyboardInterrupt:
            self.console.print(Text("Interrupted", style="yellow"))
        except UsageError as e:
            self.err(f"{name}: {e}")
        except Exception as e:  # never a traceback in the shell
            msg = (str(e).splitlines() or [""])[0][:200]
            self.err(f"{type(e).__name__}: {msg}" if msg else type(e).__name__)
        return True

    def err(self, msg: str):
        self.console.print(t(msg, "red"))

    def _need_scan(self) -> bool:
        if self.scan is None:
            self.err("No scan yet. Run /scan first.")
        return self.scan is not None

    def _finding(self, args):
        if not self._need_scan():
            return None
        if not args:
            raise UsageError("give a finding id, for example F-001")
        fid = args[0].upper()
        f = next((f for f in self.scan.findings if f.id == fid), None)
        if f is None:
            self.err(f"No finding {clean(args[0])} in {self.scan.scan_id}. try /findings")
        return f

    # -- commands
    def cmd_help(self, args):
        for name, desc in COMMANDS.items():
            g = _grid(11, 0)
            g.add_row(Text(name, style=f"bold {ACCENT}"), Text(desc, style="dim"))
            self.console.print(g)
        self.console.print(Text("also /quit. Ctrl+C twice exits.", style="dim"))

    def cmd_clear(self, args):
        self.console.clear()

    def cmd_status(self, args):
        repo, db = self.inputs or (str(self._path(DEFAULT_REPO)), str(self._path(DEFAULT_DB)))
        self.console.print(bullet(Text("●", style=ACCENT), Text("Status", style="bold")))
        self.console.print(rline(t(self.target), label="Target"))
        self.console.print(rline(t(repo), label="Repo"))
        self.console.print(rline(t(db), label="Database"))
        if self.scan:
            open_n = sum(f.status == "open" for f in self.scan.findings)
            self.console.print(rline(t(f"{self.scan.scan_id} · score {self.scan.score} · {open_n} open of {len(self.scan.findings)}"), label="Last scan"))
        else:
            self.console.print(rline("no scan yet", label="Last scan"))
        self.console.print(rline("off", label="ML hints"))

    def cmd_checks(self, args):
        for d in checks_doc.as_dicts():
            self.console.print(bullet(Text("●", style=SEV_STYLE[d["severity"]]), Text.assemble(
                t(d["id"]), "  ", sev_text(d["severity"]))))
            self.console.print(rline((clean(", ".join(d["clauses"])), "dim")))

    def cmd_findings(self, args):
        if self._need_scan():
            print_findings(self.console, self.scan)

    def cmd_show(self, args):
        f = self._finding(args)
        if f is None:
            return
        c = self.console
        c.print(bullet(Text("●", style=SEV_STYLE[f.severity]), Text.assemble(
            t(f.id), "  ", sev_text(f.severity), "  ", t(f.title))))
        e = f.evidence
        rows = [("Why", f.severity_reason), ("What", f.explanation), ("Where", " · ".join(p for p in (where(f), e.location.url) if p)),
                ("Clauses", "; ".join(f"{x.ref} ({x.note})" for x in f.clauses)),
                ("Evidence", " · ".join(p for p in (e.summary, e.masked_sample) if p)), ("Fix", f.recommendation)]
        for label, value in rows:
            if value:
                c.print(rline(t(value, nl=True), label=label))
        c.print(rline(f"Verified fix available: {'yes' if f.fix.available else 'no'}"))

    def cmd_report(self, args):
        if not self._need_scan():
            return
        path = self._path(args[0] if args else REPORT_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_report(self.scan, self.fix_modes))
        self.console.print(bullet(Text("●", style="green"), Text.assemble(("Report", "bold"), "  ", t(path))))

    def cmd_scan(self, args):
        p = _Parser(prog="/scan", add_help=False)
        p.add_argument("--target", default=DEFAULT_TARGET)
        p.add_argument("--repo", default=DEFAULT_REPO)
        p.add_argument("--db", default=DEFAULT_DB)
        a = p.parse_args(args)
        repo, db = self._path(a.repo), self._path(a.db)
        c = self.console
        c.print(Text.assemble(("Using ", "dim"), ("target ", "dim"), t(a.target), (" · repo ", "dim"), t(a.repo), (" · db ", "dim"), t(a.db)), soft_wrap=False)
        if not is_local(a.target):
            return self.err("target must be http(s) on localhost or a private address")
        if not repo.is_dir():
            return self.err(f"repo is not a folder: {clean(a.repo)}")
        if not db.is_file():
            return self.err(f"db is not a file: {clean(a.db)}")
        self.n_scans += 1
        with Task(c, "Scan", a.target) as task:
            def progress(step, i, total):
                task.spin(STEPS.get(step, (step, step))[1])

            def found(step, n):
                task.spin(None)
                label = STEPS.get(step, (step.upper(), ""))[0]
                if n is None:
                    task.fail(f"{label.ljust(9)}  did not finish")
                else:
                    task.add(rline((label.ljust(9) + "  found ", "dim"), str(n)))

            try:
                result = self.scan_fn(a.target, str(repo), str(db), scan_id=f"S-{self.n_scans:03d}", progress=progress, found=found)
            except BaseException:
                task.state = "error"
                raise
        self.load(result, (str(repo), str(db)))
        self.target = a.target
        print_summary(c, result)

    def cmd_fix(self, args):
        p = _Parser(prog="/fix", add_help=False)
        p.add_argument("id", nargs="?")
        p.add_argument("--cached", action="store_true")
        a = p.parse_args(args)
        f = self._finding([a.id] if a.id else [])
        if f is None:
            return
        c = self.console
        repo, db = self.inputs or (str(self._path(DEFAULT_REPO)), str(self._path(DEFAULT_DB)))
        before = self.scan.score
        with Task(c, f"Fix {f.id}", note="(runs on a copy, your code is not touched)") as task:
            task.spin("Replaying the saved result" if a.cached else "Patching a copy and re-scanning")
            try:
                fixed, updated, used, reason, vlog = apply_fix(
                    self.scan, f.id, repo, db, mode="cached" if a.cached else "live", fix_fn=self.fix_fn, golden_dir=self.golden_dir)
            except FixError as e:
                task.verb = None
                if e.status == 400:  # no template: not an error, tell the owner what to do by hand
                    task.add(rline("No automated fix for this check.", label="Fix"))
                    task.add(rline(t(f.recommendation or "See /show for the clauses."), label="Do this"))
                    return
                task.fail(e.detail)
                return
            except BaseException:
                task.state = "error"
                raise
            fx = fixed.fix
            verdict = lambda ok: Text("passed", "green") if ok else Text("failed", "red") if ok is False else Text("n/a", "dim")  # noqa: E731
            task.verb = None
            task.add(rline((", ".join(patched_files(fx.diff or "")) or "(no diff)"), label="Patched"))
            task.add(rline(verdict(fx.rescan_passed), label="Re-scan"))
            task.add(rline(verdict(fx.tests_passed), label="Tests"))
            ms = (vlog or {}).get("total_ms")
            task.add(rline(Text("✓", "green") if fx.verified else Text("✗ not verified", "red"),
                           (f"  {ms / 1000:.1f}s", "dim") if ms else "", label="Verified"))
            if not fx.verified:
                task.state = "error"
        if used == "cached_golden":
            c.print(Text("Cached golden patch mode: " + clean(reason or "saved result replayed on request"), style="yellow"))
        if fx.diff:
            c.print()
            print_diff(c, fx.diff)
            c.print()
        self.scan = updated
        self.fix_modes[f.id] = {"mode": used, "fallback_reason": reason}  # what render_report reads for one scan
        if fx.verified:
            c.print(Text.assemble("Score ", (f"{before} → {updated.score}", f"bold {score_style(updated.score)}"), f" ({updated.score - before:+d})"))
        else:
            c.print(Text(f"Not verified. Score stays {before}.", style="red"))


# ---------------------------------------------------------------- entry

def welcome(console: Console, shell: Shell):
    body = Group(
        Text("Does your app do what its privacy notice says?", style="dim"),
        t(f"Folder  {Path.cwd()}", "dim"), t(f"Target  {shell.target}", "dim"), Text("ML hints: off", style="dim"))
    console.print(Panel(body, title=Text("◈ DPDP Lens", style=f"bold {ACCENT}"), title_align="left",
                        box=box.ROUNDED, border_style=ACCENT, padding=(0, 1)))
    console.print(Text("/help for commands · /scan to start · ctrl+c twice to exit", style="dim"))


def _session(shell: Shell):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.styles import Style

    class Slash(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if text.startswith("/") and " " not in text:
                for name, desc in COMMANDS.items():
                    if name.startswith(text.lower()):
                        yield Completion(name, start_position=-len(text), display_meta=desc)

    style = Style.from_dict({
        "bottom-toolbar": "noreverse bg:default fg:#808080", "bottom-toolbar.text": "noreverse bg:default fg:#808080",
        "completion-menu.completion": "bg:#262626 fg:#d0d0d0", "completion-menu.completion.current": f"bg:{ACCENT} fg:#000000",
        "completion-menu.meta.completion": "bg:#262626 fg:#808080", "completion-menu.meta.completion.current": f"bg:{ACCENT} fg:#000000"})
    return PromptSession(completer=Slash(), complete_while_typing=True, style=style,
                         message=FormattedText([(f"fg:{ACCENT}", "❯ ")]),
                         bottom_toolbar=lambda: FormattedText([("class:bottom-toolbar.text", " " + shell.toolbar())]))


def main(argv=None, console: Console | None = None) -> int:
    console = console or Console(highlight=False)
    shell = Shell(console)
    tty = console.is_terminal and sys.stdin.isatty()
    welcome(console, shell)
    session = _session(shell) if tty else None
    pressed = False  # ctrl+c at an empty prompt, once
    while True:
        try:
            if session:
                console.print(Text("─" * console.width, style="dim"))
                line = session.prompt()
            else:
                line = sys.stdin.readline()
                if not line:
                    return 0
                if line.strip():
                    console.print(Text("❯ " + clean(line.strip())))
        except KeyboardInterrupt:
            if pressed:
                return 0
            pressed = True
            console.print(Text("Press ctrl+c again to exit", style="dim"))
            continue
        except EOFError:
            return 0
        pressed = False
        if not shell.handle(line):
            return 0


if __name__ == "__main__":
    sys.exit(main())
