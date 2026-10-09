#!/usr/bin/env python3
"""Autonomous Coding-Agent Controller for Antigravity CLI (agy).

Workflow:
PLAN -> IMPLEMENT -> TEST -> DEBUG -> REVIEW -> VERIFY -> REPEAT -> COMPLETE

The controller handles orchestration, safety limits, logging, verification,
stuck detection, and recovery. Antigravity handles software engineering tasks.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


# =====================================================================
# Configuration Defaults
# =====================================================================
DEFAULT_MAX_ITERATIONS = 30
DEFAULT_MAX_RUNTIME_SECONDS = 14400  # 4 hours
DEFAULT_MAX_STUCK_ITERATIONS = 3
DEFAULT_TEST_TIMEOUT_SECONDS = 1800  # 30 minutes
DEFAULT_ANTIGRAVITY_CMD = "agy"

STATUS_NOT_STARTED = "NOT_STARTED"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_VERIFYING = "VERIFYING"
STATUS_BLOCKED = "BLOCKED"
STATUS_COMPLETE = "COMPLETE"
STATUS_FAILED = "FAILED"

VALID_STATUSES = {
    STATUS_NOT_STARTED,
    STATUS_IN_PROGRESS,
    STATUS_VERIFYING,
    STATUS_BLOCKED,
    STATUS_COMPLETE,
    STATUS_FAILED,
}


# =====================================================================
# Configuration & Environment
# =====================================================================
@dataclass
class Config:
    repo_root: Path
    antigravity_command: str = DEFAULT_ANTIGRAVITY_CMD
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS
    max_stuck_iterations: int = DEFAULT_MAX_STUCK_ITERATIONS
    test_timeout_seconds: int = DEFAULT_TEST_TIMEOUT_SECONDS
    dry_run: bool = False
    status_only: bool = False
    resume: bool = False
    use_session: bool = True
    skip_permissions: bool = True
    git_checkpoints: bool = True
    custom_verify_cmd: Optional[str] = None
    task_file: Path = Path("TASK.md")
    plan_file: Path = Path("PLAN.md")
    state_file: Path = Path("STATE.md")
    agents_file: Path = Path("AGENTS.md")
    logs_dir: Path = Path("logs")

    @classmethod
    def load(cls, repo_root: Path, args: Optional[argparse.Namespace] = None) -> "Config":
        env_path = repo_root / ".env"
        file_env: Dict[str, str] = {}
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        file_env[k.strip()] = v.strip().strip("'\"")
            except Exception:
                pass

        def get_val(key: str, default: Any) -> Any:
            # Precedence: CLI args > Environment variable > .env file > Default
            cli_val = None
            if args is not None:
                cli_val = getattr(args, key.lower(), None)
            if cli_val is not None:
                return cli_val

            env_val = os.environ.get(key, file_env.get(key))
            if env_val is not None:
                if isinstance(default, int):
                    try:
                        return int(env_val)
                    except ValueError:
                        return default
                if isinstance(default, bool):
                    return env_val.lower() in ("true", "1", "yes", "y")
                return env_val
            return default

        cmd = get_val("ANTIGRAVITY_COMMAND", DEFAULT_ANTIGRAVITY_CMD)
        max_iter = int(get_val("MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS))
        max_run = int(get_val("MAX_RUNTIME_SECONDS", DEFAULT_MAX_RUNTIME_SECONDS))
        max_stuck = int(get_val("MAX_STUCK_ITERATIONS", DEFAULT_MAX_STUCK_ITERATIONS))
        test_to = int(get_val("TEST_TIMEOUT_SECONDS", DEFAULT_TEST_TIMEOUT_SECONDS))
        use_session = bool(get_val("USE_SESSION_CONTINUATION", True))
        custom_verify = os.environ.get("VERIFICATION_COMMAND", file_env.get("VERIFICATION_COMMAND"))
        if args and getattr(args, "verify_cmd", None):
            custom_verify = args.verify_cmd

        return cls(
            repo_root=repo_root,
            antigravity_command=cmd,
            max_iterations=max_iter,
            max_runtime_seconds=max_run,
            max_stuck_iterations=max_stuck,
            test_timeout_seconds=test_to,
            dry_run=bool(args.dry_run) if args else False,
            status_only=bool(args.status) if args else False,
            resume=bool(args.resume) if args else False,
            use_session=use_session,
            custom_verify_cmd=custom_verify,
            task_file=repo_root / "TASK.md",
            plan_file=repo_root / "PLAN.md",
            state_file=repo_root / "STATE.md",
            agents_file=repo_root / "AGENTS.md",
            logs_dir=repo_root / "logs",
        )


# =====================================================================
# Redaction & Safety
# =====================================================================
KEY_VALUE_PATTERN = re.compile(
    r"(?i)\b(api[-_]?key|access[-_]?token|secret[-_]?key|auth[-_]?token|password)\s*([:=])\s*['\"]?([A-Za-z0-9_\-\.]{8,})['\"]?"
)
BEARER_PATTERN = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9_\-\.]{12,})")
BARE_TOKEN_PATTERN = re.compile(r"\b(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z-_]{35})\b")


def redact_secrets(text: str) -> str:
    """Redact sensitive tokens, passwords, and keys from logs and console."""
    if not text:
        return ""
    result = KEY_VALUE_PATTERN.sub(r"\1\2[REDACTED]", text)
    result = BEARER_PATTERN.sub(r"\1[REDACTED]", result)
    result = BARE_TOKEN_PATTERN.sub(r"[REDACTED]", result)
    return result


# =====================================================================
# State & Task Management
# =====================================================================
@dataclass
class AgentState:
    status: str
    iteration: int
    current_objective: str
    completed: str
    current_work: str
    last_test_result: str
    current_problem: str
    next_action: str
    last_updated: str

    @classmethod
    def load(cls, state_path: Path) -> "AgentState":
        if not state_path.is_file():
            return cls(
                status=STATUS_NOT_STARTED,
                iteration=0,
                current_objective="Read TASK.md and begin implementation.",
                completed="- Nothing yet.",
                current_work="None.",
                last_test_result="Not run.",
                current_problem="None.",
                next_action="Inspect the repository.",
                last_updated="Not set.",
            )

        content = state_path.read_text(encoding="utf-8", errors="ignore")
        return cls.parse(content)

    @classmethod
    def parse(cls, content: str) -> "AgentState":
        def extract_field(label: str, default: str = "") -> str:
            pattern = re.compile(rf"^{label}\s*:\s*(.*?)(?=\n[A-Z][A-Za-z0-9 ]+\s*:|\Z)", re.MULTILINE | re.DOTALL)
            m = pattern.search(content)
            if m:
                return m.group(1).strip()
            return default

        # Extract status
        status_match = re.search(r"(?i)^status\s*:\s*([A-Za-z_]+)", content, re.MULTILINE)
        raw_status = status_match.group(1).upper() if status_match else STATUS_NOT_STARTED
        status = raw_status if raw_status in VALID_STATUSES else STATUS_IN_PROGRESS

        # Extract iteration
        iter_match = re.search(r"(?i)^iteration\s*:\s*(\d+)", content, re.MULTILINE)
        iteration = int(iter_match.group(1)) if iter_match else 0

        obj = extract_field("Current Objective", "Read TASK.md and begin implementation.")
        comp = extract_field("Completed", "- Nothing yet.")
        work = extract_field("Current Work", "None.")
        tests = extract_field("Last Test Result", "Not run.")
        prob = extract_field("Current Problem", "None.")
        action = extract_field("Next Action", "Inspect the repository.")
        updated = extract_field("Last Updated", "Not set.")

        return cls(
            status=status,
            iteration=iteration,
            current_objective=obj,
            completed=comp,
            current_work=work,
            last_test_result=tests,
            current_problem=prob,
            next_action=action,
            last_updated=updated,
        )

    def save(self, state_path: Path) -> None:
        self.last_updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
        text = f"""# Autonomous Agent State

Status: {self.status}

Iteration: {self.iteration}

Current Objective:
{self.current_objective}

Completed:
{self.completed}

Current Work:
{self.current_work}

Last Test Result:
{self.last_test_result}

Current Problem:
{self.current_problem}

Next Action:
{self.next_action}

Last Updated:
{self.last_updated}
"""
        state_path.write_text(text, encoding="utf-8")


class TaskChecker:
    @staticmethod
    def inspect(task_path: Path) -> Tuple[bool, List[str], List[str]]:
        """Inspect TASK.md and return (has_requirements, checked_dod, unchecked_dod)."""
        if not task_path.is_file():
            return False, [], []

        content = task_path.read_text(encoding="utf-8", errors="ignore")
        checked: List[str] = []
        unchecked: List[str] = []

        in_dod = False
        for line in content.splitlines():
            line_str = line.strip()
            if line_str.lower().startswith("## definition of done"):
                in_dod = True
                continue
            if in_dod and line_str.startswith("## "):
                in_dod = False
                continue

            if in_dod:
                if re.match(r"^-\s*\[[xX]\]\s+", line_str):
                    item = re.sub(r"^-\s*\[[xX]\]\s+", "", line_str)
                    checked.append(item)
                elif re.match(r"^-\s*\[\s*\]\s+", line_str):
                    item = re.sub(r"^-\s*\[\s*\]\s+", "", line_str)
                    unchecked.append(item)

        has_requirements = bool(checked or unchecked)
        return has_requirements, checked, unchecked


# =====================================================================
# Verification Detector & Runner
# =====================================================================
class VerificationRunner:
    def __init__(self, config: Config):
        self.config = config

    def detect_command(self) -> Optional[str]:
        if self.config.custom_verify_cmd:
            return self.config.custom_verify_cmd

        root = self.config.repo_root

        # Python projects
        if (root / "uv.lock").is_file():
            return "uv run pytest"
        if (root / "pyproject.toml").is_file():
            # Check if pytest is mentioned or tests exist
            pyproject = (root / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
            if "pytest" in pyproject or (root / "tests").is_dir():
                return "python -m pytest"
        if (root / "requirements.txt").is_file() and ((root / "tests").is_dir() or list(root.glob("test_*.py"))):
            return "python -m pytest"

        # Node / JS / TS projects
        pkg_json = root / "package.json"
        if pkg_json.is_file():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                scripts = data.get("scripts", {})
                has_test = "test" in scripts and "no test specified" not in scripts.get("test", "")
                has_build = "build" in scripts

                if (root / "pnpm-lock.yaml").is_file():
                    if has_test:
                        return "pnpm test"
                    if has_build:
                        return "pnpm build"
                if (root / "yarn.lock").is_file():
                    if has_test:
                        return "yarn test"
                    if has_build:
                        return "yarn build"
                if has_test:
                    return "npm test"
                if has_build:
                    return "npm run build"
            except Exception:
                pass

        # Rust
        if (root / "Cargo.toml").is_file():
            return "cargo test"

        # Go
        if (root / "go.mod").is_file():
            return "go test ./..."

        # Python unittest fallback if test files or tests folder exist
        if (root / "tests").is_dir() or list(root.glob("test_*.py")):
            return "python -m unittest discover"

        return None

    def run(self, command: str) -> Tuple[int, str, float]:
        """Execute verification command with timeout and return (exit_code, output, duration)."""
        start_time = time.time()
        try:
            res = subprocess.run(
                command,
                shell=True,
                cwd=str(self.config.repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.test_timeout_seconds,
            )
            duration = time.time() - start_time
            return res.returncode, redact_secrets(res.stdout), duration
        except subprocess.TimeoutExpired as e:
            duration = time.time() - start_time
            out = f"Verification command timed out after {self.config.test_timeout_seconds}s.\nPartial output:\n"
            out += (e.stdout or "") if isinstance(e.stdout, str) else ""
            return -1, redact_secrets(out), duration
        except Exception as e:
            duration = time.time() - start_time
            return -1, f"Failed to execute verification command '{command}': {e}", duration


# =====================================================================
# Git Safety & Checkpointing
# =====================================================================
class GitManager:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.is_git = self._check_is_git()

    def _check_is_git(self) -> bool:
        if not (self.repo_root / ".git").is_dir():
            return False
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=str(self.repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return res.returncode == 0 and res.stdout.strip() == "true"
        except Exception:
            return False

    def status_short(self) -> str:
        if not self.is_git:
            return "Not a git repository."
        try:
            res = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(self.repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return res.stdout.strip()
        except Exception as e:
            return f"git status error: {e}"

    def create_checkpoint(self, iteration: int, message: str) -> bool:
        """Create a safe checkpoint commit without using destructive commands."""
        if not self.is_git:
            return False
        try:
            status = self.status_short()
            if not status:
                return False  # No changes to checkpoint

            # Stage modified and new files, excluding sensitive/log files
            # Note: We do NOT use git clean or git reset --hard!
            subprocess.run(["git", "add", "."], cwd=str(self.repo_root), check=True)
            commit_msg = f"[autonomous checkpoint] Iteration {iteration}: {message}"
            res = subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=str(self.repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return res.returncode == 0
        except Exception:
            return False


# =====================================================================
# Snapshot & Stuck Detection
# =====================================================================
class RepoSnapshot:
    @staticmethod
    def capture(repo_root: Path, git_mgr: GitManager) -> Dict[str, Any]:
        """Capture signature of repo state to detect lack of progress."""
        state_file = repo_root / "STATE.md"
        plan_file = repo_root / "PLAN.md"

        state_content = state_file.read_text(encoding="utf-8", errors="ignore") if state_file.is_file() else ""
        plan_content = plan_file.read_text(encoding="utf-8", errors="ignore") if plan_file.is_file() else ""

        # Collect hashes of tracked/modified files excluding logs and .git
        file_signatures: Dict[str, float] = {}
        for p in repo_root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(repo_root)
                parts = rel.parts
                if ".git" in parts or "logs" in parts or "__pycache__" in parts:
                    continue
                try:
                    file_signatures[str(rel)] = p.stat().st_mtime
                except Exception:
                    pass

        return {
            "git_status": git_mgr.status_short() if git_mgr.is_git else "",
            "file_count": len(file_signatures),
            "files": file_signatures,
            "state_hash": hashlib.sha256(state_content.encode("utf-8")).hexdigest(),
            "plan_hash": hashlib.sha256(plan_content.encode("utf-8")).hexdigest(),
        }


# =====================================================================
# Prompts
# =====================================================================
STANDARD_AUTONOMOUS_PROMPT = """You are operating inside an autonomous software-development loop.

Read:

- TASK.md
- AGENTS.md
- PLAN.md
- STATE.md

Inspect the repository before making assumptions.

Your job is to make concrete progress toward TASK.md.

Do not merely explain what should be done.

For this iteration:

1. inspect the current repository state
2. identify the next unfinished requirement
3. implement the next useful change
4. run appropriate tests or verification
5. diagnose and fix failures
6. update PLAN.md if needed
7. update STATE.md

Do not repeat a failed approach without investigating why it failed.

If the task is not complete:
- leave the repository in a usable state
- document what was completed
- document the current problem
- document the next action

If everything is genuinely complete:
- verify every Definition of Done item
- update STATE.md
- set:

STATUS: COMPLETE
"""

RECOVERY_VERIFICATION_PROMPT_TEMPLATE = """Automated verification failed.

Do not merely explain the error.

Inspect the repository and fix the underlying problem.

Failure output:

{test_output}

After fixing:

1. run the failing verification again
2. run related tests
3. update STATE.md
4. continue toward the remaining requirements
"""

STUCK_RECOVERY_PROMPT = """The autonomous loop appears stuck.

Recent iterations have not produced meaningful progress.

Do not repeat the same approach.

Re-read TASK.md, STATE.md, and the actual logs/errors.

Re-evaluate the architecture.

Choose a materially different approach where appropriate.

Make concrete changes and verify them.
"""

INCOMPLETE_DOD_PROMPT_TEMPLATE = """The task was reported as complete, but Definition of Done items in TASK.md remain unchecked or unverified:

{unchecked_items}

Please inspect these requirements, complete any remaining work or verification, check the items in TASK.md (- [x]), and update STATE.md.
"""


# =====================================================================
# Logger
# =====================================================================
class IterationLogger:
    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def write_iteration_log(
        self,
        iteration: int,
        start_time: datetime,
        end_time: datetime,
        command_line: List[str],
        stdout: str,
        stderr: str,
        exit_code: int,
        test_command: Optional[str],
        test_output: Optional[str],
        test_exit_code: Optional[int],
        snapshot_before: Dict[str, Any],
        snapshot_after: Dict[str, Any],
    ) -> Path:
        log_file = self.logs_dir / f"iteration-{iteration:03d}.log"
        lines = [
            f"=== Iteration {iteration:03d} ===",
            f"Start Time: {start_time.isoformat()}",
            f"End Time:   {end_time.isoformat()}",
            f"Duration:   {(end_time - start_time).total_seconds():.2f}s",
            "",
            "--- Antigravity Command ---",
            " ".join(command_line),
            f"Exit Code: {exit_code}",
            "",
            "--- STDOUT ---",
            stdout or "(empty)",
            "",
            "--- STDERR ---",
            stderr or "(empty)",
            "",
            "--- Verification Test ---",
            f"Command:   {test_command or 'None'}",
            f"Exit Code: {test_exit_code if test_exit_code is not None else 'N/A'}",
            f"Output:\n{test_output or '(none)'}",
            "",
            "--- Repository State Before ---",
            f"Git Status: {snapshot_before.get('git_status', 'N/A')}",
            f"Files Count: {snapshot_before.get('file_count', 0)}",
            "",
            "--- Repository State After ---",
            f"Git Status: {snapshot_after.get('git_status', 'N/A')}",
            f"Files Count: {snapshot_after.get('file_count', 0)}",
            "",
        ]
        log_file.write_text("\n".join(lines), encoding="utf-8")
        return log_file


# =====================================================================
# Controller
# =====================================================================
class AutonomousController:
    def __init__(self, config: Config):
        self.config = config
        self.git_mgr = GitManager(config.repo_root)
        self.verifier = VerificationRunner(config)
        self.logger = IterationLogger(config.logs_dir)
        self.interrupted = False
        self._register_signals()

    def _register_signals(self) -> None:
        def handler(signum, frame):
            print("\n[!] Interrupt received. Safely stopping controller...")
            self.interrupted = True

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def verify_prerequisites(self) -> None:
        """Verify repository root, required files, and Antigravity CLI."""
        if not (self.config.repo_root / "TASK.md").is_file():
            print("[!] TASK.md not found. Creating template...")
            self.config.task_file.write_text(
                "# Autonomous Task\n\n## Objective\n\nDescribe the desired end result here.\n\n## Requirements\n\n- Requirement 1\n\n## Definition of Done\n\n- [ ] Requirement 1 implemented\n- [ ] Relevant tests pass\n",
                encoding="utf-8",
            )

        if not self.config.plan_file.is_file():
            print("[!] PLAN.md not found. Creating template...")
            self.config.plan_file.write_text(
                "# Implementation Plan\n\nStatus: NOT_STARTED\n\n## Steps\n1. Inspect repository.\n",
                encoding="utf-8",
            )

        if not self.config.state_file.is_file():
            print("[!] STATE.md not found. Creating initial state...")
            AgentState(
                status=STATUS_NOT_STARTED,
                iteration=0,
                current_objective="Read TASK.md and begin implementation.",
                completed="- Nothing yet.",
                current_work="None.",
                last_test_result="Not run.",
                current_problem="None.",
                next_action="Inspect the repository.",
                last_updated=datetime.now(timezone.utc).isoformat(),
            ).save(self.config.state_file)

        if not self.config.agents_file.is_file():
            print("[!] AGENTS.md not found. Please ensure AGENTS.md exists.")

        self.config.logs_dir.mkdir(parents=True, exist_ok=True)

        # Check Antigravity CLI executable
        agy_cmd = self.config.antigravity_command
        # If it's a simple command name, check shutil.which
        if not shutil.which(agy_cmd):
            # Check if agy or agy.exe is in PATH
            if not shutil.which("agy") and not shutil.which("agy.exe"):
                raise RuntimeError(
                    f"Antigravity CLI executable '{agy_cmd}' not found on PATH. Please ensure Antigravity is installed."
                )

    def print_status(self) -> None:
        """Print current STATE.md and latest progress."""
        state = AgentState.load(self.config.state_file)
        has_reqs, checked, unchecked = TaskChecker.inspect(self.config.task_file)
        print("\n=======================================================")
        print("          AUTONOMOUS AGENT CONTROLLER STATUS           ")
        print("=======================================================")
        print(f"Status:            {state.status}")
        print(f"Iteration:         {state.iteration} / {self.config.max_iterations}")
        print(f"Current Objective: {state.current_objective}")
        print(f"Next Action:       {state.next_action}")
        print(f"Current Problem:   {state.current_problem}")
        print(f"Last Test Result:  {state.last_test_result}")
        print(f"Last Updated:      {state.last_updated}")
        print("-------------------------------------------------------")
        print(f"Definition of Done: {len(checked)} complete, {len(unchecked)} remaining")
        for u in unchecked[:5]:
            print(f"  [ ] {u}")
        if len(unchecked) > 5:
            print(f"  ... and {len(unchecked) - 5} more")
        print("=======================================================\n")

    def run_dry_run(self) -> None:
        """Simulate controller run and display commands/prompts."""
        print("\n=== DRY RUN MODE ===")
        print(f"Repository root:      {self.config.repo_root}")
        print(f"Antigravity command:  {self.config.antigravity_command}")
        print(f"Max iterations:       {self.config.max_iterations}")
        print(f"Max runtime:          {self.config.max_runtime_seconds}s")
        print(f"Max stuck iterations: {self.config.max_stuck_iterations}")
        print(f"Test timeout:         {self.config.test_timeout_seconds}s")
        print(f"Session continuation: {self.config.use_session}")
        print(f"Git repo detected:    {self.git_mgr.is_git}")

        detected_test = self.verifier.detect_command()
        print(f"Detected test cmd:    {detected_test or 'None (smoke test / agent responsibility)'}")

        has_reqs, checked, unchecked = TaskChecker.inspect(self.config.task_file)
        print(f"Task definition:      {len(checked)} checked DoD items, {len(unchecked)} unchecked DoD items")

        cmd = [self.config.antigravity_command, "-p", "<prompt>"]
        if self.config.skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        print(f"Sample invocation:    {' '.join(cmd)}")
        print("\nSample Standard Prompt:\n" + STANDARD_AUTONOMOUS_PROMPT)
        print("\nDry run completed successfully. No changes made.")

    def run(self) -> int:
        """Main autonomous loop."""
        self.verify_prerequisites()

        if self.config.status_only:
            self.print_status()
            return 0

        if self.config.dry_run:
            self.run_dry_run()
            return 0

        # Load initial state
        state = AgentState.load(self.config.state_file)

        # Handle resume vs new run
        if self.config.resume or state.iteration > 0:
            start_iteration = state.iteration + 1
            print(f"[*] Resuming autonomous workflow from iteration {start_iteration} (Status: {state.status})...")
        else:
            start_iteration = 1
            state.status = STATUS_IN_PROGRESS
            state.iteration = 0
            state.save(self.config.state_file)
            print("[*] Starting new autonomous workflow from iteration 1...")

        start_time = time.time()
        stuck_counter = 0
        last_snapshot: Optional[Dict[str, Any]] = None
        recovery_prompt_override: Optional[str] = None

        for iteration in range(start_iteration, self.config.max_iterations + 1):
            if self.interrupted:
                state.status = STATUS_BLOCKED
                state.current_problem = "Interrupted by user signal."
                state.save(self.config.state_file)
                print("\n[!] Execution stopped safely due to user interrupt.")
                return 130

            # Check runtime limit
            elapsed = time.time() - start_time
            if elapsed > self.config.max_runtime_seconds:
                print(f"\n[!] Maximum runtime exceeded ({elapsed:.1f}s > {self.config.max_runtime_seconds}s).")
                state.status = STATUS_BLOCKED
                state.current_problem = f"Runtime limit exceeded ({self.config.max_runtime_seconds}s)."
                state.save(self.config.state_file)
                return 1

            print(f"\n=======================================================")
            print(f"       AUTONOMOUS ITERATION {iteration:03d} / {self.config.max_iterations}")
            print(f"=======================================================")
            iter_start = datetime.now(timezone.utc)

            # Snapshot before iteration
            snapshot_before = RepoSnapshot.capture(self.config.repo_root, self.git_mgr)

            # Construct Prompt
            if recovery_prompt_override:
                prompt_to_send = recovery_prompt_override
                recovery_prompt_override = None
            elif stuck_counter >= self.config.max_stuck_iterations:
                print("[!] Stuck counter reached threshold. Feeding stuck recovery prompt.")
                prompt_to_send = STUCK_RECOVERY_PROMPT
            else:
                prompt_to_send = STANDARD_AUTONOMOUS_PROMPT

            # Prepare Antigravity Command
            cmd = [self.config.antigravity_command]
            if self.config.use_session and iteration > 1:
                # Add continuation flag
                cmd.append("-c")
            if self.config.skip_permissions:
                cmd.append("--dangerously-skip-permissions")
            cmd.extend(["-p", prompt_to_send])

            print(f"[*] Launching Antigravity iteration {iteration}...")
            stdout_text = ""
            stderr_text = ""
            exit_code = 0

            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.config.repo_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                stdout_text, stderr_text = proc.communicate()
                exit_code = proc.returncode
            except Exception as e:
                stderr_text = f"Subprocess execution error: {e}"
                exit_code = 1

            stdout_clean = redact_secrets(stdout_text)
            stderr_clean = redact_secrets(stderr_text)

            print(f"[*] Antigravity iteration {iteration} completed with exit code {exit_code}.")
            if stdout_clean:
                # Print a brief summary of stdout
                preview = stdout_clean.strip().splitlines()
                print("--- Agent Response Preview ---")
                for line in preview[-8:]:
                    print(f"  {line}")

            # Reload updated state from STATE.md
            state = AgentState.load(self.config.state_file)
            state.iteration = iteration

            # Run automated verification
            verify_cmd = self.verifier.detect_command()
            test_exit_code = None
            test_output = None
            test_passed = True

            if verify_cmd:
                print(f"[*] Running automated verification: {verify_cmd}")
                state.status = STATUS_VERIFYING
                state.save(self.config.state_file)

                t_code, t_out, t_dur = self.verifier.run(verify_cmd)
                test_exit_code = t_code
                test_output = t_out
                print(f"[*] Verification finished in {t_dur:.2f}s (Exit code: {t_code})")

                if t_code != 0:
                    test_passed = False
                    print(f"[!] Verification FAILED (exit code {t_code}).")
                    state.last_test_result = f"FAILED: {verify_cmd} (code {t_code})"
                    state.current_problem = f"Automated verification failed:\n{t_out[:300]}"
                    recovery_prompt_override = RECOVERY_VERIFICATION_PROMPT_TEMPLATE.format(
                        test_output=t_out[:4000]
                    )
                else:
                    print("[+] Verification PASSED.")
                    state.last_test_result = f"PASSED: {verify_cmd}"
                    if state.current_problem.startswith("Automated verification failed"):
                        state.current_problem = "None."

            # Snapshot after iteration
            snapshot_after = RepoSnapshot.capture(self.config.repo_root, self.git_mgr)

            # Stuck Detection: Check if repository state changed
            meaningful_progress = False
            if snapshot_before["git_status"] != snapshot_after["git_status"]:
                meaningful_progress = True
            elif snapshot_before["files"] != snapshot_after["files"]:
                meaningful_progress = True
            elif snapshot_before["state_hash"] != snapshot_after["state_hash"]:
                meaningful_progress = True
            elif test_passed and test_exit_code is not None:
                meaningful_progress = True

            if meaningful_progress:
                stuck_counter = 0
            else:
                stuck_counter += 1
                print(f"[!] Warning: No meaningful progress detected in iteration {iteration} (stuck count: {stuck_counter}/{self.config.max_stuck_iterations}).")

            # Check if stuck limit reached and recovery failed
            if stuck_counter > self.config.max_stuck_iterations:
                print(f"[!] Agent is stuck after {stuck_counter} iterations. Marking as BLOCKED.")
                state.status = STATUS_BLOCKED
                state.current_problem = "Agent stuck: no meaningful progress made across consecutive iterations."
                state.save(self.config.state_file)
                self.logger.write_iteration_log(
                    iteration,
                    iter_start,
                    datetime.now(timezone.utc),
                    cmd,
                    stdout_clean,
                    stderr_clean,
                    exit_code,
                    verify_cmd,
                    test_output,
                    test_exit_code,
                    snapshot_before,
                    snapshot_after,
                )
                return 2

            # Check Definition of Done
            has_reqs, checked_dod, unchecked_dod = TaskChecker.inspect(self.config.task_file)

            # Completion Verification (Section 16)
            is_complete = False
            completion_reasons = []

            agent_claimed_complete = (
                "STATUS: COMPLETE" in stdout_clean.upper()
                or "STATUS: COMPLETE" in state.status.upper()
                or state.status == STATUS_COMPLETE
            )

            if agent_claimed_complete:
                if unchecked_dod:
                    print(f"[!] Agent reported completion, but {len(unchecked_dod)} Definition of Done items remain unchecked.")
                    recovery_prompt_override = INCOMPLETE_DOD_PROMPT_TEMPLATE.format(
                        unchecked_items="\n".join(f"- [ ] {item}" for item in unchecked_dod)
                    )
                    state.status = STATUS_IN_PROGRESS
                elif not test_passed:
                    print("[!] Agent reported completion, but automated verification failed.")
                    state.status = STATUS_IN_PROGRESS
                elif state.current_problem and state.current_problem.lower() not in ("none", "none.", ""):
                    print(f"[!] Agent reported completion, but active problem documented: {state.current_problem}")
                    state.status = STATUS_IN_PROGRESS
                else:
                    is_complete = True
                    state.status = STATUS_COMPLETE
                    print("\n[+] =================================================")
                    print("[+] SUCCESS: Task is verified and COMPLETE!")
                    print("[+] =================================================\n")

            # Safe Git Checkpoint
            if self.config.git_checkpoints and self.git_mgr.is_git:
                if meaningful_progress:
                    msg = state.current_work if state.current_work and state.current_work != "None." else "Progress milestone"
                    if self.git_mgr.create_checkpoint(iteration, msg):
                        print(f"[*] Safe Git checkpoint created for iteration {iteration}.")

            # Save state
            state.save(self.config.state_file)

            # Write Iteration Log
            iter_end = datetime.now(timezone.utc)
            log_path = self.logger.write_iteration_log(
                iteration,
                iter_start,
                iter_end,
                cmd,
                stdout_clean,
                stderr_clean,
                exit_code,
                verify_cmd,
                test_output,
                test_exit_code,
                snapshot_before,
                snapshot_after,
            )
            print(f"[*] Iteration log saved to {log_path.name}")

            if is_complete:
                return 0

        # Loop finished without completion
        print(f"\n[!] Reached maximum iterations ({self.config.max_iterations}) without task completion.")
        state.status = STATUS_BLOCKED
        state.current_problem = f"Reached maximum iterations ({self.config.max_iterations})."
        state.save(self.config.state_file)
        return 1


# =====================================================================
# CLI Entrypoint
# =====================================================================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomous Coding-Agent Controller for Antigravity CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="Show commands and prompts without executing")
    parser.add_argument("--status", action="store_true", help="Display current STATE.md and progress")
    parser.add_argument("--resume", action="store_true", help="Resume from existing STATE.md")
    parser.add_argument("--max-iterations", type=int, help="Maximum autonomous iterations to run")
    parser.add_argument("--max-runtime", type=int, dest="max_runtime_seconds", help="Maximum runtime in seconds")
    parser.add_argument("--test-timeout", type=int, dest="test_timeout_seconds", help="Test timeout in seconds")
    parser.add_argument("--max-stuck", type=int, dest="max_stuck_iterations", help="Max consecutive stuck iterations")
    parser.add_argument("--verify-cmd", type=str, help="Custom verification command to run")
    parser.add_argument("--no-session", action="store_false", dest="use_session", help="Disable Antigravity session continuation (-c)")
    parser.add_argument("--no-git-checkpoints", action="store_false", dest="git_checkpoints", help="Disable automatic git checkpoints")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Resolve repo root: find ancestor containing TASK.md or .git or fallback to current working directory
    cwd = Path.cwd().resolve()
    repo_root = cwd
    for parent in [cwd] + list(cwd.parents):
        if (parent / "TASK.md").is_file() or (parent / ".git").is_dir():
            repo_root = parent
            break

    config = Config.load(repo_root=repo_root, args=args)
    controller = AutonomousController(config)
    return controller.run()


if __name__ == "__main__":
    sys.exit(main())
