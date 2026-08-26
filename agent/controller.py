#!/usr/bin/env python3
"""Autonomous OpenCode Agent Controller.

Orchestrates autonomous software engineering iterations using OpenCode:
PLAN -> IMPLEMENT -> TEST -> DEBUG -> REVIEW -> VERIFY -> COMPLETE
"""

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Default Configuration Constants
DEFAULT_MAX_ITERATIONS = 30
DEFAULT_MAX_RUNTIME_SECONDS = 4 * 60 * 60  # 14400 seconds (4 hours)
DEFAULT_MAX_STUCK_ITERATIONS = 3
DEFAULT_TEST_TIMEOUT_SECONDS = 30 * 60     # 1800 seconds (30 minutes)

PROMPT_AUTONOMOUS_ITERATION = """You are operating inside an autonomous development loop.

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
2. determine the next unfinished requirement
3. implement the next useful change
4. run appropriate tests/verification
5. diagnose and fix failures
6. update PLAN.md if the implementation plan changes
7. update STATE.md

Do not repeat a failed approach without investigating why it failed.

If the task is not complete, leave the repository in a usable state and record the next action.

If all requirements are genuinely satisfied:
- verify them
- update STATE.md
- set:

STATUS: COMPLETE
"""

PROMPT_FAILURE_RECOVERY = """Automated verification failed.

Do not merely explain the failure.

Inspect the repository and fix the underlying cause.

Failure output:

{test_output}

After fixing:

1. run the failing verification again
2. run related tests
3. update STATE.md
4. continue toward the remaining requirements
"""

PROMPT_STUCK_RECOVERY = """The autonomous loop appears stuck.

Recent iterations have not produced meaningful progress.

Do not repeat the same approach.

Re-read TASK.md, STATE.md, and the actual failure logs.

Re-evaluate the architecture.

Choose a materially different approach where appropriate.

Make concrete changes and verify them.
"""

DEFAULT_TASK_TEMPLATE = """# Autonomous Task

## Objective

Describe the desired end result.

## Requirements

- Requirement 1
- Requirement 2
- Requirement 3

## Definition of Done

- [ ] Requirement 1 implemented
- [ ] Requirement 2 implemented
- [ ] Requirement 3 implemented
- [ ] Relevant tests pass
- [ ] Existing functionality still works
- [ ] No obvious regressions remain

## Constraints

Add project-specific constraints here.
"""

DEFAULT_PLAN_TEMPLATE = """# Implementation Plan

Status: NOT_STARTED

## Steps

1. Inspect the repository and existing architecture.
2. Identify affected files and components.
3. Implement the requirements incrementally.
4. Run relevant tests.
5. Diagnose and fix failures.
6. Review the implementation.
7. Verify every Definition of Done item.

## Notes

Update this plan whenever implementation discoveries materially change the approach.
"""

DEFAULT_STATE_TEMPLATE = """# Autonomous Agent State

Status: NOT_STARTED

Iteration: 0

Current Objective:
Read TASK.md and begin implementation.

Completed:
- Nothing yet.

Current Work:
None.

Last Test Result:
Not run.

Current Problem:
None.

Next Action:
Inspect the repository.

Last Updated:
Not set.
"""


def load_dotenv(repo_root: Path) -> None:
    """Load environment variables from .env if present without external dependencies."""
    env_file = repo_root / ".env"
    if not env_file.is_file():
        return
    try:
        content = env_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            # Strip outer quotes if present
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if key not in os.environ:
                os.environ[key] = val
    except Exception as e:
        print(f"[WARN] Failed to read .env: {e}", file=sys.stderr)


def sanitize_secrets(text: str) -> str:
    """Mask potential secrets, tokens, and keys in logs."""
    if not text:
        return ""
    patterns = [
        (r"(sk-[a-zA-Z0-9_\-]{20,})", "sk-***REDACTED***"),
        (r"(gh[pousr]-[a-zA-Z0-9]{20,})", "gh*-***REDACTED***"),
        (r"(Bearer\s+)[a-zA-Z0-9_\-\.]{20,}", r"\1***REDACTED***"),
        (r"(password\s*[:=]\s*)[^\s,]+", r"\1***REDACTED***", re.IGNORECASE),
        (r"(api[_-]?key\s*[:=]\s*)[^\s,]+", r"\1***REDACTED***", re.IGNORECASE),
        (r"(token\s*[:=]\s*)[^\s,]+", r"\1***REDACTED***", re.IGNORECASE),
    ]
    sanitized = text
    for item in patterns:
        if len(item) == 2:
            pat, repl = item
            sanitized = re.sub(pat, repl, sanitized)
        else:
            pat, repl, flags = item
            sanitized = re.sub(pat, repl, sanitized, flags=flags)
    return sanitized


@dataclass
class ControllerConfig:
    repo_root: Path
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS
    max_stuck_iterations: int = DEFAULT_MAX_STUCK_ITERATIONS
    test_timeout_seconds: int = DEFAULT_TEST_TIMEOUT_SECONDS
    opencode_model: Optional[str] = None
    opencode_variant: Optional[str] = None
    test_command: Optional[str] = None
    use_persistent_server: bool = False
    server_url: Optional[str] = None
    auto_approve: bool = True
    dry_run: bool = False
    status_only: bool = False
    resume: bool = False

    @classmethod
    def from_args(cls, repo_root: Path, args: argparse.Namespace) -> "ControllerConfig":
        load_dotenv(repo_root)

        max_iter = int(
            args.max_iterations
            or os.environ.get("MAX_ITERATIONS")
            or DEFAULT_MAX_ITERATIONS
        )
        max_runtime = int(
            args.max_runtime
            or os.environ.get("MAX_RUNTIME_SECONDS")
            or DEFAULT_MAX_RUNTIME_SECONDS
        )
        max_stuck = int(
            os.environ.get("MAX_STUCK_ITERATIONS")
            or DEFAULT_MAX_STUCK_ITERATIONS
        )
        test_timeout = int(
            os.environ.get("TEST_TIMEOUT_SECONDS")
            or DEFAULT_TEST_TIMEOUT_SECONDS
        )

        model = args.model or os.environ.get("OPENCODE_MODEL") or None
        variant = args.variant or os.environ.get("OPENCODE_VARIANT") or None
        test_cmd = args.test_cmd or os.environ.get("TEST_COMMAND") or None

        use_server = False
        if args.persistent_server:
            use_server = True
        elif os.environ.get("USE_PERSISTENT_SERVER", "").lower() in ("true", "1", "yes"):
            use_server = True

        server_url = os.environ.get("OPENCODE_SERVER_URL") or "http://127.0.0.1:4096"
        auto_approve_env = os.environ.get("OPENCODE_AUTO_APPROVE", "true").lower()
        auto_approve = auto_approve_env in ("true", "1", "yes")

        return cls(
            repo_root=repo_root,
            max_iterations=max_iter,
            max_runtime_seconds=max_runtime,
            max_stuck_iterations=max_stuck,
            test_timeout_seconds=test_timeout,
            opencode_model=model,
            opencode_variant=variant,
            test_command=test_cmd,
            use_persistent_server=use_server,
            server_url=server_url,
            auto_approve=auto_approve,
            dry_run=args.dry_run,
            status_only=args.status,
            resume=args.resume,
        )


class StateFile:
    """Manages parsing and updating STATE.md."""

    def __init__(self, path: Path):
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file()

    def read_text(self) -> str:
        if not self.exists():
            return ""
        return self.path.read_text(encoding="utf-8")

    def parse(self) -> Dict[str, str]:
        """Extract key fields from STATE.md."""
        data = {
            "status": "NOT_STARTED",
            "iteration": "0",
            "objective": "",
            "completed": "",
            "work": "",
            "last_test": "",
            "problem": "",
            "next_action": "",
            "last_updated": "",
        }
        content = self.read_text()
        if not content:
            return data

        status_m = re.search(r"^Status:\s*([A-Za-z_]+)", content, re.MULTILINE | re.IGNORECASE)
        if status_m:
            data["status"] = status_m.group(1).strip().upper()

        iter_m = re.search(r"^Iteration:\s*(\d+)", content, re.MULTILINE | re.IGNORECASE)
        if iter_m:
            data["iteration"] = iter_m.group(1).strip()

        # Parse sections
        def extract_section(title: str, next_titles: List[str]) -> str:
            escaped_title = re.escape(title)
            escaped_next = "|".join(re.escape(t) for t in next_titles)
            pat = rf"^{escaped_title}:\s*\n(.*?)(?=^(?:{escaped_next}):|\Z)"
            m = re.search(pat, content, re.MULTILINE | re.DOTALL)
            if m:
                return m.group(1).strip()
            return ""

        data["objective"] = extract_section("Current Objective", ["Completed", "Current Work"])
        data["completed"] = extract_section("Completed", ["Current Work", "Last Test Result"])
        data["work"] = extract_section("Current Work", ["Last Test Result", "Current Problem"])
        data["last_test"] = extract_section("Last Test Result", ["Current Problem", "Next Action"])
        data["problem"] = extract_section("Current Problem", ["Next Action", "Last Updated"])
        data["next_action"] = extract_section("Next Action", ["Last Updated"])

        updated_m = re.search(r"^Last Updated:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
        if updated_m:
            data["last_updated"] = updated_m.group(1).strip()

        return data

    def update(
        self,
        status: Optional[str] = None,
        iteration: Optional[int] = None,
        completed: Optional[str] = None,
        work: Optional[str] = None,
        last_test: Optional[str] = None,
        problem: Optional[str] = None,
        next_action: Optional[str] = None,
    ) -> None:
        """Update fields in STATE.md while preserving structure."""
        current = self.parse()
        new_status = (status or current.get("status") or "IN_PROGRESS").upper()
        new_iter = iteration if iteration is not None else int(current.get("iteration") or "0")
        new_obj = current.get("objective") or "Read TASK.md and implement requirements."
        new_comp = completed if completed is not None else (current.get("completed") or "- In progress.")
        new_work = work if work is not None else (current.get("work") or "Executing autonomous iteration.")
        new_test = last_test if last_test is not None else (current.get("last_test") or "Not run.")
        new_prob = problem if problem is not None else (current.get("problem") or "None.")
        new_next = next_action if next_action is not None else (current.get("next_action") or "Continue implementation.")
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        content = f"""# Autonomous Agent State

Status: {new_status}

Iteration: {new_iter}

Current Objective:
{new_obj}

Completed:
{new_comp}

Current Work:
{new_work}

Last Test Result:
{new_test}

Current Problem:
{new_prob}

Next Action:
{new_next}

Last Updated:
{timestamp}
"""
        self.path.write_text(content, encoding="utf-8")


class GitManager:
    """Safe Git helper that preserves user work and never executes destructive recovery."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.is_git = self._check_git()

    def _check_git(self) -> bool:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            return r.returncode == 0 and "true" in r.stdout.lower()
        except Exception:
            return False

    def status_short(self) -> str:
        if not self.is_git:
            return "Not a git repository."
        try:
            r = subprocess.run(
                ["git", "status", "--short"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            lines = []
            for line in r.stdout.splitlines():
                # Filter out logs/ so log files don't pollute git status
                clean = line.strip()
                if "logs/" in clean or ".env" in clean:
                    continue
                lines.append(line)
            return "\n".join(lines).strip()
        except Exception as e:
            return f"Error querying git status: {e}"

    def get_modified_files(self) -> Set[str]:
        """Return relative paths of modified or untracked files excluding logs/."""
        if not self.is_git:
            return set()
        status = self.status_short()
        files = set()
        for line in status.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                file_path = parts[1].strip().strip('"')
                if not file_path.startswith("logs"):
                    files.add(file_path)
        return files

    def create_checkpoint(self, iteration: int, message: str) -> bool:
        """Safely create a milestone checkpoint commit for modified project files."""
        if not self.is_git:
            return False
        try:
            # Check if there are changes to commit
            status = self.status_short()
            if not status:
                return False

            # Add modified files (excluding logs and .env)
            subprocess.run(["git", "add", "."], cwd=self.repo_root, capture_output=True)
            # Unstage logs if staged
            subprocess.run(["git", "reset", "HEAD", "logs/"], cwd=self.repo_root, capture_output=True)
            subprocess.run(["git", "reset", "HEAD", ".env"], cwd=self.repo_root, capture_output=True)

            commit_msg = f"checkpoint: iteration {iteration:03d} - {message}"
            r = subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            return r.returncode == 0
        except Exception as e:
            print(f"[WARN] Failed to create git checkpoint: {e}", file=sys.stderr)
            return False


class TestDetector:
    """Discovers and executes verification and test suites."""

    def __init__(self, repo_root: Path, custom_cmd: Optional[str] = None):
        self.repo_root = repo_root
        self.custom_cmd = custom_cmd

    def detect_command(self) -> Optional[str]:
        """Detect standard verification commands based on repository contents."""
        if self.custom_cmd:
            return self.custom_cmd

        # Python projects
        has_pyproject = (self.repo_root / "pyproject.toml").is_file()
        has_uv_lock = (self.repo_root / "uv.lock").is_file()
        has_reqs = (self.repo_root / "requirements.txt").is_file()
        has_pytest_ini = (
            (self.repo_root / "pytest.ini").is_file()
            or (self.repo_root / "setup.cfg").is_file()
            or (self.repo_root / "tests").is_dir()
            or (self.repo_root / "test").is_dir()
        )

        if has_uv_lock and shutil.which("uv"):
            return "uv run pytest"
        if has_pyproject or has_reqs or has_pytest_ini:
            if shutil.which("pytest"):
                return "pytest"
            return f'"{sys.executable}" -m unittest discover'

        # Node.js projects
        pkg_json = self.repo_root / "package.json"
        if pkg_json.is_file():
            try:
                import json
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                test_script = scripts.get("test", "")
                has_valid_test = test_script and "no test specified" not in test_script.lower()

                if (self.repo_root / "pnpm-lock.yaml").is_file() and shutil.which("pnpm"):
                    return "pnpm test" if has_valid_test else ("pnpm run build" if "build" in scripts else None)
                if (self.repo_root / "yarn.lock").is_file() and shutil.which("yarn"):
                    return "yarn test" if has_valid_test else ("yarn build" if "build" in scripts else None)
                if shutil.which("npm"):
                    return "npm test" if has_valid_test else ("npm run build" if "build" in scripts else None)
            except Exception:
                pass

        # Rust / Cargo
        if (self.repo_root / "Cargo.toml").is_file() and shutil.which("cargo"):
            return "cargo test"

        # Go
        if (self.repo_root / "go.mod").is_file() and shutil.which("go"):
            return "go test ./..."

        return None

    def run_verification(self, timeout_seconds: int) -> Tuple[int, str]:
        """Execute verification command and return (exit_code, output)."""
        cmd = self.detect_command()
        if not cmd:
            return 0, "No automated test suite detected. OpenCode responsible for verification."

        try:
            r = subprocess.run(
                cmd,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                shell=True,
                timeout=timeout_seconds,
            )
            output = (r.stdout + "\n" + r.stderr).strip()
            return r.returncode, sanitize_secrets(output)
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or "") + "\n" + (e.stderr or "") + f"\n[TIMEOUT] Verification timed out after {timeout_seconds}s."
            return 124, sanitize_secrets(out)
        except Exception as e:
            return 1, f"Error running verification command ({cmd}): {e}"


class StuckDetector:
    """Tracks repository progress across iterations to detect lack of progress."""

    def __init__(self, max_stuck: int = DEFAULT_MAX_STUCK_ITERATIONS):
        self.max_stuck = max_stuck
        self.consecutive_stuck = 0
        self.history: List[Dict] = []

    def record_and_evaluate(
        self,
        git_status_before: str,
        git_status_after: str,
        state_data: Dict[str, str],
        test_code: int,
        opencode_code: int,
    ) -> Tuple[bool, int]:
        """Evaluate whether this iteration made meaningful progress.

        Returns (is_stuck, consecutive_stuck_count).
        """
        snapshot = {
            "git_after": git_status_after,
            "completed": state_data.get("completed", ""),
            "work": state_data.get("work", ""),
            "next_action": state_data.get("next_action", ""),
            "status": state_data.get("status", ""),
            "test_code": test_code,
            "opencode_code": opencode_code,
        }

        progress_made = False

        if not self.history:
            # First iteration always counts as establishing baseline
            progress_made = True
        else:
            prev = self.history[-1]
            # Signals of progress:
            # 1. Git status changed from before to after
            git_changed = git_status_before != git_status_after
            # 2. STATE.md completed items updated
            completed_changed = snapshot["completed"] != prev["completed"]
            # 3. STATE.md next action progressed
            action_changed = snapshot["next_action"] != prev["next_action"]
            # 4. Status transitioned (e.g. to VERIFYING or COMPLETE)
            status_changed = snapshot["status"] != prev["status"]
            # 5. Tests went from failing to passing
            test_improved = prev["test_code"] != 0 and test_code == 0

            if git_changed or completed_changed or status_changed or test_improved:
                progress_made = True
            elif action_changed and opencode_code == 0:
                progress_made = True

        self.history.append(snapshot)

        if progress_made:
            self.consecutive_stuck = 0
        else:
            self.consecutive_stuck += 1

        is_stuck = self.consecutive_stuck >= self.max_stuck
        return is_stuck, self.consecutive_stuck


class OpenCodeRunner:
    """Manages execution of OpenCode CLI commands."""

    def __init__(self, config: ControllerConfig):
        self.config = config
        self.executable = self._find_opencode()
        self.session_id: Optional[str] = None
        self.server_process: Optional[subprocess.Popen] = None

    def _find_opencode(self) -> Optional[str]:
        exe = shutil.which("opencode")
        if exe:
            return exe
        # On Windows, try opencode.cmd explicitly
        if sys.platform == "win32":
            exe_cmd = shutil.which("opencode.cmd") or shutil.which("opencode.CMD")
            if exe_cmd:
                return exe_cmd
            exe_ps = shutil.which("opencode.ps1")
            if exe_ps:
                return exe_ps
        return None

    def verify_available(self) -> Tuple[bool, str]:
        if not self.executable:
            return False, "OpenCode executable not found in PATH."
        try:
            r = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                text=True,
                shell=True,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )
            if r.returncode == 0:
                return True, r.stdout.strip()
            return False, f"OpenCode returned exit code {r.returncode}: {r.stderr.strip()}"
        except Exception as e:
            return False, f"Failed to execute OpenCode: {e}"

    def ensure_server(self) -> Optional[str]:
        """Ensure persistent server is running if configured. Return server URL or None."""
        if not self.config.use_persistent_server:
            return None
        url = self.config.server_url or "http://127.0.0.1:4096"

        # Check if already running
        try:
            req = urllib.request.Request(f"{url}/global/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return url
        except Exception:
            pass

        # Try to launch server
        print(f"[INFO] Launching persistent OpenCode server at {url}...")
        port = "4096"
        host = "127.0.0.1"
        if ":" in url:
            port_match = re.search(r":(\d+)", url)
            if port_match:
                port = port_match.group(1)

        try:
            self.server_process = subprocess.Popen(
                [self.executable, "serve", "--port", port, "--hostname", host],
                cwd=self.config.repo_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=True,
            )
            # Wait for healthcheck
            for _ in range(15):
                time.sleep(0.5)
                try:
                    req = urllib.request.Request(f"{url}/global/health")
                    with urllib.request.urlopen(req, timeout=1) as resp:
                        if resp.status == 200:
                            print(f"[INFO] Persistent OpenCode server healthy at {url}.")
                            return url
                except Exception:
                    continue
        except Exception as e:
            print(f"[WARN] Failed to start OpenCode server: {e}. Falling back to standard mode.", file=sys.stderr)

        return None

    def shutdown_server(self) -> None:
        """Safely terminate server process if launched by controller."""
        if self.server_process:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.server_process.pid)], capture_output=True)
                else:
                    self.server_process.terminate()
            except Exception:
                pass
            self.server_process = None

    def execute_iteration(self, prompt: str, is_first: bool) -> Tuple[int, str, str, List[str], float]:
        """Run one non-interactive iteration of OpenCode with prompt.

        Returns (exit_code, stdout, stderr, cmd_list, duration_seconds).
        """
        assert self.executable is not None, "OpenCode executable is missing"
        server_url = self.ensure_server()

        cmd = [self.executable, "run"]

        if server_url:
            cmd.extend(["--attach", server_url])
        else:
            # Continue previous session across iterations if available
            if not is_first:
                cmd.append("-c")

        if self.config.opencode_model:
            cmd.extend(["-m", self.config.opencode_model])
        if self.config.opencode_variant:
            cmd.extend(["--variant", self.config.opencode_variant])
        if self.config.auto_approve:
            cmd.append("--auto")

        cmd.append(prompt)

        start_time = time.time()
        try:
            # Always pass stdin=subprocess.DEVNULL to prevent OpenCode waiting on stdin in non-interactive mode
            r = subprocess.run(
                cmd,
                cwd=self.config.repo_root,
                capture_output=True,
                text=True,
                shell=True,
                stdin=subprocess.DEVNULL,
                timeout=1800,  # 30 min iteration timeout
            )
            duration = time.time() - start_time
            stdout = sanitize_secrets(r.stdout)
            stderr = sanitize_secrets(r.stderr)
            return r.returncode, stdout, stderr, cmd, duration
        except subprocess.TimeoutExpired as e:
            duration = time.time() - start_time
            stdout = sanitize_secrets(e.stdout or "")
            stderr = sanitize_secrets((e.stderr or "") + "\n[TIMEOUT] OpenCode iteration timed out.")
            return 124, stdout, stderr, cmd, duration
        except Exception as e:
            duration = time.time() - start_time
            return 1, "", f"Execution failed: {e}", cmd, duration


class AutonomousController:
    """Main orchestration controller for autonomous OpenCode loops."""

    def __init__(self, config: ControllerConfig):
        self.config = config
        self.state_file = StateFile(config.repo_root / "STATE.md")
        self.git = GitManager(config.repo_root)
        self.test_detector = TestDetector(config.repo_root, config.test_command)
        self.stuck_detector = StuckDetector(config.max_stuck_iterations)
        self.runner = OpenCodeRunner(config)
        self.logs_dir = config.repo_root / "logs"

    def preflight_setup(self) -> bool:
        """Verify environment and scaffold missing standard files if needed."""
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        task_path = self.config.repo_root / "TASK.md"
        if not task_path.is_file():
            print("[ERROR] TASK.md is missing. Please define your task in TASK.md.", file=sys.stderr)
            return False

        plan_path = self.config.repo_root / "PLAN.md"
        if not plan_path.is_file():
            plan_path.write_text(DEFAULT_PLAN_TEMPLATE, encoding="utf-8")
            print("[INFO] Created default PLAN.md.")

        state_path = self.config.repo_root / "STATE.md"
        if not state_path.is_file():
            state_path.write_text(DEFAULT_STATE_TEMPLATE, encoding="utf-8")
            print("[INFO] Created default STATE.md.")

        agents_path = self.config.repo_root / "AGENTS.md"
        if not agents_path.is_file():
            print("[WARN] AGENTS.md not found. Agent instructions should be present for optimal performance.")

        # Verify OpenCode CLI
        ok, version = self.runner.verify_available()
        if not ok:
            print(f"[ERROR] OpenCode is not available: {version}", file=sys.stderr)
            print("Please ensure OpenCode is installed and added to PATH (e.g. npm install -g opencode-ai).", file=sys.stderr)
            return False
        print(f"[OK] OpenCode detected: {version}")

        # Detect tests
        test_cmd = self.test_detector.detect_command()
        if test_cmd:
            print(f"[OK] Automated test command detected: {test_cmd}")
        else:
            print("[INFO] No automated test suite detected. OpenCode will determine validation steps.")

        return True

    def show_status(self) -> None:
        """Display current agent status and state."""
        print("=" * 60)
        print("AUTONOMOUS AGENT STATUS")
        print("=" * 60)
        state_data = self.state_file.parse()
        print(f"Status:         {state_data.get('status')}")
        print(f"Iteration:      {state_data.get('iteration')}")
        print(f"Current Obj:    {state_data.get('objective')}")
        print(f"Next Action:    {state_data.get('next_action')}")
        print(f"Last Test:      {state_data.get('last_test')}")
        print(f"Current Prob:   {state_data.get('problem')}")
        print(f"Last Updated:   {state_data.get('last_updated')}")
        print("-" * 60)
        print("Git Status:")
        print(self.git.status_short() or "Clean working directory.")
        print("=" * 60)

    def write_iteration_log(
        self,
        iteration: int,
        timestamp: str,
        status_before: str,
        git_before: str,
        cmd_list: List[str],
        opencode_code: int,
        duration: float,
        stdout: str,
        stderr: str,
        test_cmd: Optional[str],
        test_code: int,
        test_output: str,
        git_after: str,
        state_after: str,
    ) -> Path:
        """Write structured log file for the iteration."""
        log_path = self.logs_dir / f"iteration-{iteration:03d}.log"
        cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd_list)

        content = f"""================================================================================
AUTONOMOUS AGENT ITERATION LOG
================================================================================
Iteration:             {iteration:03d}
Timestamp:             {timestamp}
Status Before:         {status_before}
Duration:              {duration:.2f}s

GIT STATUS BEFORE:
{git_before or 'Clean.'}

================================================================================
OPENCODE EXECUTION
================================================================================
Command:               {cmd_str}
Exit Code:             {opencode_code}

STDOUT:
{stdout or '(None)'}

STDERR:
{stderr or '(None)'}

================================================================================
AUTOMATED VERIFICATION
================================================================================
Command:               {test_cmd or 'None (discretionary)'}
Exit Code:             {test_code}

OUTPUT:
{test_output or '(None)'}

================================================================================
REPOSITORY STATE AFTER
================================================================================
GIT STATUS AFTER:
{git_after or 'Clean.'}

STATE.MD AFTER:
{state_after}
================================================================================
"""
        log_path.write_text(content, encoding="utf-8")
        return log_path

    def run(self) -> int:
        """Execute autonomous loop until complete, blocked, or limits reached."""
        if not self.preflight_setup():
            return 1

        if self.config.status_only:
            self.show_status()
            return 0

        state_data = self.state_file.parse()
        current_status = state_data.get("status", "NOT_STARTED")

        if current_status == "COMPLETE" and not self.config.resume:
            print("[INFO] Task is already marked COMPLETE in STATE.md. Use --resume to continue or reset STATE.md to start anew.")
            return 0

        if current_status == "BLOCKED" and not self.config.resume:
            print(f"[WARN] Task is currently marked BLOCKED: {state_data.get('problem')}. Use --resume to continue after resolving.")
            return 1

        start_iter = int(state_data.get("iteration") or "0") + 1
        if not self.config.resume and start_iter > 1:
            print(f"[INFO] Resuming from iteration {start_iter} based on STATE.md.")

        start_time = time.time()
        last_test_failed = False
        last_test_output = ""
        stuck_in_recovery = False

        print("=" * 60)
        print("STARTING AUTONOMOUS OPENCODE LOOP")
        print(f"Repository Root: {self.config.repo_root}")
        print(f"Max Iterations:  {self.config.max_iterations}")
        print(f"Max Runtime:     {self.config.max_runtime_seconds}s ({self.config.max_runtime_seconds // 60}m)")
        print(f"Max Stuck:       {self.config.max_stuck_iterations} iterations")
        print("=" * 60)

        if self.config.dry_run:
            print("[DRY-RUN] Preflight checks passed.")
            print(f"[DRY-RUN] Next iteration would be #{start_iter}.")
            test_cmd = self.test_detector.detect_command()
            print(f"[DRY-RUN] Test command: {test_cmd or 'Discretionary'}")
            print(f"[DRY-RUN] Initial Git state:\n{self.git.status_short() or 'Clean.'}")
            print("[DRY-RUN] Dry run complete. No modifications made.")
            return 0

        try:
            for iteration in range(start_iter, self.config.max_iterations + 1):
                elapsed = time.time() - start_time
                if elapsed >= self.config.max_runtime_seconds:
                    print(f"\n[STOP] Reached maximum runtime limit ({self.config.max_runtime_seconds}s). Stopping safely.")
                    self.state_file.update(
                        status="IN_PROGRESS",
                        iteration=iteration - 1,
                        problem=f"Reached maximum runtime limit of {self.config.max_runtime_seconds}s.",
                        next_action="Resume with --resume and extended runtime if desired.",
                    )
                    return 0

                iter_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
                state_before = self.state_file.parse()
                status_before = state_before.get("status", "IN_PROGRESS")
                git_before = self.git.status_short()

                print(f"\n>>> ITERATION {iteration:03d}/{self.config.max_iterations} (Elapsed: {int(elapsed)}s)")

                # Select Prompt
                if stuck_in_recovery:
                    prompt = PROMPT_STUCK_RECOVERY
                    print("[INFO] Sending STUCK RECOVERY prompt to OpenCode...")
                elif last_test_failed:
                    prompt = PROMPT_FAILURE_RECOVERY.format(test_output=last_test_output)
                    print("[INFO] Sending FAILURE RECOVERY prompt to OpenCode...")
                else:
                    prompt = PROMPT_AUTONOMOUS_ITERATION
                    print("[INFO] Sending STANDARD AUTONOMOUS prompt to OpenCode...")

                # Update State to IN_PROGRESS or VERIFYING
                self.state_file.update(
                    status="IN_PROGRESS",
                    iteration=iteration,
                    work="Executing OpenCode iteration.",
                )

                # Execute OpenCode
                is_first = (iteration == start_iter)
                opencode_code, stdout, stderr, cmd_list, duration = self.runner.execute_iteration(
                    prompt=prompt,
                    is_first=is_first,
                )

                print(f"[INFO] OpenCode iteration finished in {duration:.1f}s (Exit code: {opencode_code})")
                if stdout:
                    print(f"[OUTPUT] {stdout.strip()[:300]}...")

                # Run Automated Verification
                test_cmd = self.test_detector.detect_command()
                test_code, test_output = self.test_detector.run_verification(self.config.test_timeout_seconds)

                if test_code == 0:
                    test_summary = "PASSED" if test_cmd else "Discretionary (no test suite)"
                    last_test_failed = False
                    last_test_output = ""
                else:
                    test_summary = f"FAILED (Exit code {test_code})"
                    last_test_failed = True
                    last_test_output = test_output
                    print(f"[WARN] Automated tests failed:\n{test_output[:400]}")

                # Check Git & Repository state after iteration
                git_after = self.git.status_short()
                state_after_data = self.state_file.parse()
                current_state_status = state_after_data.get("status", "IN_PROGRESS")

                # Update STATE.md test results if OpenCode didn't set them
                self.state_file.update(
                    iteration=iteration,
                    last_test=test_summary,
                )

                # Stuck Detection
                is_stuck, stuck_count = self.stuck_detector.record_and_evaluate(
                    git_status_before=git_before,
                    git_status_after=git_after,
                    state_data=state_after_data,
                    test_code=test_code,
                    opencode_code=opencode_code,
                )

                if is_stuck:
                    if not stuck_in_recovery:
                        print(f"[WARN] Loop appears stuck ({stuck_count} iterations without meaningful progress). Triggering recovery iteration.")
                        stuck_in_recovery = True
                    else:
                        print(f"[ERROR] Loop remains stuck after recovery attempt ({stuck_count} iterations). Halting safely.")
                        self.state_file.update(
                            status="BLOCKED",
                            iteration=iteration,
                            problem=f"Stuck after {stuck_count} consecutive iterations without progress.",
                            next_action="Human intervention required to inspect blockers.",
                        )
                        # Log iteration before returning
                        self.write_iteration_log(
                            iteration=iteration,
                            timestamp=iter_timestamp,
                            status_before=status_before,
                            git_before=git_before,
                            cmd_list=cmd_list,
                            opencode_code=opencode_code,
                            duration=duration,
                            stdout=stdout,
                            stderr=stderr,
                            test_cmd=test_cmd,
                            test_code=test_code,
                            test_output=test_output,
                            git_after=git_after,
                            state_after=self.state_file.read_text(),
                        )
                        return 1
                else:
                    stuck_in_recovery = False

                # Write Iteration Log
                log_path = self.write_iteration_log(
                    iteration=iteration,
                    timestamp=iter_timestamp,
                    status_before=status_before,
                    git_before=git_before,
                    cmd_list=cmd_list,
                    opencode_code=opencode_code,
                    duration=duration,
                    stdout=stdout,
                    stderr=stderr,
                    test_cmd=test_cmd,
                    test_code=test_code,
                    test_output=test_output,
                    git_after=git_after,
                    state_after=self.state_file.read_text(),
                )
                print(f"[INFO] Log saved to {log_path.name}")

                # Milestone Checkpoint
                if test_code == 0 and git_after:
                    if self.git.create_checkpoint(iteration, f"milestone tests passing"):
                        print(f"[INFO] Git checkpoint commit created for iteration {iteration:03d}.")

                # Check if Agent declared COMPLETE
                if current_state_status == "COMPLETE":
                    if test_code == 0:
                        print("\n" + "=" * 60)
                        print("🎉 TASK COMPLETE! All verification checks passed.")
                        print("=" * 60)
                        return 0
                    else:
                        print("[WARN] Agent set Status: COMPLETE, but automated verification failed. Continuing to verify.")
                        self.state_file.update(status="VERIFYING")

                # Check if Agent declared BLOCKED
                if current_state_status == "BLOCKED":
                    print(f"\n[STOP] Agent requested human intervention (BLOCKED): {state_after_data.get('problem')}")
                    return 1

            print(f"\n[STOP] Reached maximum iterations ({self.config.max_iterations}). Stopping safely.")
            return 0

        finally:
            self.runner.shutdown_server()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous OpenCode Agent Controller")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without executing iterations")
    parser.add_argument("--status", action="store_true", help="Display current agent status from STATE.md and git")
    parser.add_argument("--resume", action="store_true", help="Resume from current STATE.md instead of starting fresh")
    parser.add_argument("--max-iterations", type=int, help=f"Max autonomous iterations (default: {DEFAULT_MAX_ITERATIONS})")
    parser.add_argument("--max-runtime", type=int, help=f"Max runtime in seconds (default: {DEFAULT_MAX_RUNTIME_SECONDS})")
    parser.add_argument("--test-cmd", type=str, help="Override automated test command")
    parser.add_argument("--model", type=str, help="Override OpenCode model (provider/model)")
    parser.add_argument("--variant", type=str, help="Override OpenCode model variant (e.g. high, max)")
    parser.add_argument("--persistent-server", action="store_true", help="Use or start persistent OpenCode server")
    return parser.parse_args()


def resolve_repo_root() -> Path:
    """Resolve repository root by looking for TASK.md or .git upwards from this script."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "TASK.md").is_file() or (parent / ".git").is_dir():
            return parent
    return Path.cwd().resolve()


def main() -> None:
    args = parse_arguments()
    repo_root = resolve_repo_root()
    config = ControllerConfig.from_args(repo_root, args)
    controller = AutonomousController(config)
    exit_code = controller.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
