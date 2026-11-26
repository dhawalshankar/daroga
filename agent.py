#!/usr/bin/env python3
"""
Autonomous EC2 to AWS Lambda Migration Agent
============================================
An enterprise-grade, autonomous AI agent that analyzes legacy EC2-hosted applications,
evaluates serverless architectural suitability, generates AWS Lambda entrypoints and SAM infrastructure,
self-validates code through compiler/schema feedback loops, and publishes safe migration pull-requests
on an isolated remote git branch.

Zero Blast Radius:
- The base/main branch is NEVER modified or committed to directly.
- All modifications occur on an isolated feature branch (`lambda-migration-<timestamp>`).
- Feature branch is committed and pushed to remote for PR review.
- The working copy is safely restored to the original branch upon completion.

Usage:
    export GROQ_API_KEY="gsk_..."
    python agent.py /path/to/repo [--push] [--remote origin] [--model MODEL]
"""

import argparse
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from groq import BadRequestError, Groq, RateLimitError

# ==============================================================================
# OS-Agnostic Terminal UI & Formatting
# ==============================================================================
def init_terminal_colors():
    """Enables ANSI escape sequence processing on Windows 10/11 consoles."""
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            h_out = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_out, ctypes.byref(mode)):
                kernel32.SetConsoleMode(h_out, mode.value | 0x0004)
        except Exception:
            pass

init_terminal_colors()

class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def supports_color() -> bool:
    if os.environ.get("NO_COLOR") or not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


def log_step(category: str, message: str, color: str = Colors.CYAN):
    if supports_color():
        print(f"{color}{Colors.BOLD}[{category}]{Colors.RESET} {message}")
    else:
        print(f"[{category}] {message}")


def log_tool(tool_name: str, details: str):
    if supports_color():
        print(f"  {Colors.DIM}↳ {Colors.RESET}{Colors.YELLOW}{tool_name}{Colors.RESET} {Colors.DIM}{details}{Colors.RESET}")
    else:
        print(f"  -> {tool_name} {details}")


def log_success(message: str):
    if supports_color():
        print(f"{Colors.GREEN}{Colors.BOLD}✓ {message}{Colors.RESET}")
    else:
        print(f"[OK] {message}")


def log_warn(message: str):
    if supports_color():
        print(f"{Colors.YELLOW}{Colors.BOLD}⚠ {message}{Colors.RESET}")
    else:
        print(f"[WARN] {message}")


def log_error(message: str):
    if supports_color():
        print(f"{Colors.RED}{Colors.BOLD}✗ {message}{Colors.RESET}")
    else:
        print(f"[ERROR] {message}")


# ==============================================================================
# Configuration & Constants
# ==============================================================================
DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
DEFAULT_MAX_TURNS = 30
DEFAULT_TIMEOUT_SEC = 120

ALLOWED_COMMAND_PREFIXES = (
    "python -m py_compile",
    "python3 -m py_compile",
    "python -m pytest",
    "python3 -m pytest",
    "pytest",
    "sam validate",
    "node --check",
)

BLOCKED_COMMAND_KEYWORDS = (
    "push", "merge", "deploy", "aws", "apply", "sudo", "rm", "curl", "wget", "git",
)

# System Prompt guiding the Autonomous Migration Reasoning Loop
SYSTEM_PROMPT = """You are an Autonomous Cloud Migration Agent specializing in converting EC2-hosted services into production-ready AWS Lambda serverless architectures.

OPERATING CONTEXT:
You operate strictly within the provided repository on a dedicated migration git branch.
You have access to tools that let you inspect source code, write new artifacts, and run syntax/schema validations.

AUTONOMOUS DECISION-MAKING PROCEDURE:
1. EXPLORATION & ARCHITECTURAL DISCOVERY:
   - Use `list_files` to understand repository topology.
   - Use `read_file` to inspect dependency manifests (`requirements.txt`, `package.json`, etc.), entrypoint files (`app.py`, `server.py`, `main.py`), routing logic, and configuration.
   - Identify statefulness: inspect for local filesystem writes, SQLite/embedded databases, in-memory caches, persistent background threads/daemons, WebSockets, or tasks running > 15 minutes.

2. VERDICT DETERMINATION:
   Synthesize your findings and determine an objective verdict:
   - `migrate`: Application is stateless or easily decoupled; standard HTTP/API or event triggers fit well within Lambda concurrency & limits (<= 15 min).
   - `partial`: Application can run on Lambda with architectural adjustments (e.g., local state must move to DynamoDB/S3, background tasks to SQS/EventBridge).
   - `do_not_migrate`: Application violates Lambda fundamentals (e.g., permanent background daemon, hard WebSocket dependencies, heavy long-running continuous processing > 15 mins).

3. ARTIFACT GENERATION (When verdict is `migrate` or `partial`):
   - `lambda_function.py`: Production-ready Lambda entrypoint with standard WSGI/ASGI bridge (e.g. `apig_wsgi.make_lambda_handler(app)` for Flask, `Mangum(app)` for FastAPI). Include structured logging and cold-start optimization.
   - `requirements.txt`: Append required Lambda adapters (e.g., `apig-wsgi>=2.17.0` or `mangum>=0.17.0`) while preserving existing dependencies without duplicate definitions.
   - `template.yaml`: Complete AWS Serverless Application Model (SAM) template defining the `AWS::Serverless::Function`, runtime, memory size (default 512MB), timeout (30s), environment variables, and `HttpApi` / `Api` event triggers.
   - DO NOT delete or corrupt original application files. Keep existing logic intact and point the Lambda handler to the existing app instance.

4. CLOSED-LOOP VALIDATION & SELF-HEALING:
   - Execute `run_command` with `python -m py_compile lambda_function.py`.
   - If AWS SAM CLI is available in the environment, run `sam validate`.
   - CRITICAL: If any validation command fails, inspect the error output, determine the root cause, rewrite the faulty file using `write_file`, and re-run validation until it succeeds.

5. GENERATE COMPREHENSIVE DOCUMENTATION:
   - Generate `MIGRATION_REPORT.md` (Technical architectural report):
     * Executive Verdict & Technical Justification
     * Code & Infrastructure Delta (files created/modified)
     * Production Readiness Checklist (IAM policies, VPC subnets, AWS Secrets Manager / Parameter Store, S3/DynamoDB decoupling)
     * Workload Cost Comparison (Always-on EC2 instance vs Lambda Pay-per-Request model with estimated breakeven points)
   - Generate `USER.md` (Step-by-Step AWS Console / Dashboard Guide for the Developer/User):
     * This file is specifically written for the user so they know EXACTLY what buttons to click and configurations to make in their AWS Management Console (Dashboard) to bring the migrated Lambda live.
     * Section 1: "Quick Deployment via AWS SAM" (how to run `sam build && sam deploy --guided` from terminal).
     * Section 2: "Manual AWS Lambda Console Setup" (Step-by-step console clicks: Function Name, Runtime Python 3.11, Handler path `lambda_function.lambda_handler`, Memory 512MB, Timeout 30s).
     * Section 3: "Environment Variables Configuration" (Go to Configuration -> Environment Variables -> Edit, list all required keys found in the app with placeholder values).
     * Section 4: "IAM Execution Role & Permissions" (Go to Configuration -> Permissions -> attach AWSLambdaBasicExecutionRole and any needed DB/S3/VPC access policies).
     * Section 5: "API Gateway HTTP Ingress Trigger" (Go to Function Overview -> Add Trigger -> API Gateway -> Create HTTP API -> Open/JWT security -> Route /{proxy+}). Note that AWS Console displays the live HTTP URL.
     * Section 6: "Console Test Event" (Provide an exact JSON payload the user can paste into the AWS Lambda 'Test' tab to confirm HTTP 200 OK).
     * Section 7: "Logs & Monitoring" (How to view logs in CloudWatch under the Monitor tab).

6. COMPLETION:
   - Call the `finish` tool with the verdict and a structured executive summary.

If the verdict is `do_not_migrate`:
- Write `MIGRATION_REPORT.md` detailing the architectural blockers and recommended modernizations.
- Write `USER.md` explaining step-by-step AWS Console actions for alternative hosting on AWS ECS Fargate (AWS Console -> ECS -> Create Cluster -> Create Task Definition -> Launch Service).
- Call `finish`.
"""

# ==============================================================================
# Agent Tool Definitions (OpenAI/Groq Function Calling Format)
# ==============================================================================
def _tool_spec(name: str, desc: str, props: Dict[str, Any], required: List[str] = None) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required or [],
            },
        },
    }


TOOLS = [
    _tool_spec(
        "list_files",
        "Recursively lists files in a workspace directory (excludes .git, node_modules, __pycache__).",
        {"path": {"type": "string", "description": "Relative directory path (default: '.')"}},
    ),
    _tool_spec(
        "read_file",
        "Reads the UTF-8 content of a file within the repository.",
        {"path": {"type": "string", "description": "Relative path of file to read"}},
        ["path"],
    ),
    _tool_spec(
        "write_file",
        "Writes or overwrites a file inside the target repository with given UTF-8 content.",
        {
            "path": {"type": "string", "description": "Relative path to target file"},
            "content": {"type": "string", "description": "Complete text content to write"},
        },
        ["path", "content"],
    ),
    _tool_spec(
        "run_command",
        "Executes a deterministic safety-whitelisted validation command (py_compile, pytest, sam validate, node --check).",
        {"command": {"type": "string", "description": "Command string to execute"}},
        ["command"],
    ),
    _tool_spec(
        "finish",
        "Signals completion of the migration evaluation and generation process.",
        {
            "verdict": {
                "type": "string",
                "enum": ["migrate", "partial", "do_not_migrate"],
                "description": "Architectural migration verdict",
            },
            "summary": {"type": "string", "description": "Executive summary of migration findings and actions"},
        },
        ["verdict", "summary"],
    ),
]

# ==============================================================================
# Git Operations & Safety Sandbox
# ==============================================================================
def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [
        "git",
        "-c", "user.name=Lambda Migration Agent",
        "-c", "user.email=agent@lambda-migration.ai",
        *args,
    ]
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=check)


def get_current_branch(repo: Path) -> str:
    res = run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return res.stdout.strip()


def is_git_clean(repo: Path) -> bool:
    res = run_git(repo, "status", "--porcelain")
    return len(res.stdout.strip()) == 0


def get_git_remotes(repo: Path) -> List[str]:
    res = run_git(repo, "remote", check=False)
    if res.returncode != 0 or not res.stdout.strip():
        return []
    return [r.strip() for r in res.stdout.strip().splitlines() if r.strip()]


def get_remote_url(repo: Path, remote_name: str) -> Optional[str]:
    res = run_git(repo, "remote", "get-url", remote_name, check=False)
    if res.returncode == 0:
        return res.stdout.strip()
    return None


def construct_pr_url(remote_url: str, branch: str) -> Optional[str]:
    """Generates a direct 1-click Pull Request URL for GitHub or GitLab."""
    if not remote_url:
        return None
    # SSH format: git@github.com:owner/repo.git
    # HTTPS format: https://github.com/owner/repo.git
    m = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)(?:\.git)?", remote_url)
    if m:
        owner, repo_name = m.group(1), m.group(2)
        return f"https://github.com/{owner}/{repo_name}/pull/new/{branch}"
    m_gl = re.search(r"gitlab\.com[:/]([^/]+)/([^/\.]+)(?:\.git)?", remote_url)
    if m_gl:
        owner, repo_name = m_gl.group(1), m_gl.group(2)
        return f"https://gitlab.com/{owner}/{repo_name}/-/merge_requests/new?merge_request%5Bsource_branch%5D={branch}"
    return None


def safe_resolve_path(repo: Path, rel_path: str) -> Path:
    """Enforces sandboxing: prevents path traversal outside the repository."""
    full_path = (repo / rel_path).resolve()
    if full_path != repo and repo not in full_path.parents:
        raise PermissionError(f"Security Sandbox Violation: Path '{rel_path}' resolves outside the repository.")
    if ".git" in full_path.relative_to(repo).parts:
        raise PermissionError("Security Sandbox Violation: Access to .git directory is forbidden.")
    return full_path


# ==============================================================================
# Tool Execution Engine
# ==============================================================================
def execute_tool(repo: Path, name: str, args: Dict[str, Any], timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> str:
    try:
        if name == "list_files":
            base_dir = safe_resolve_path(repo, args.get("path", "."))
            files = []
            for p in sorted(base_dir.rglob("*")):
                if not p.is_file():
                    continue
                rel_parts = p.relative_to(repo).parts
                if any(x in rel_parts for x in (".git", "__pycache__", "node_modules", ".venv", "venv", ".idea")):
                    continue
                # Use as_posix() so file paths use forward slashes uniformly across Windows, Linux, and macOS
                files.append(p.relative_to(repo).as_posix())
            return "\n".join(files[:250]) if files else "(empty repository)"

        if name == "read_file":
            target = safe_resolve_path(repo, args["path"])
            if not target.exists():
                return f"ERROR: File '{args['path']}' does not exist."
            content = target.read_text(encoding="utf-8", errors="replace")
            # Limit return size to avoid context exhaustion
            return content[:16000]

        if name == "write_file":
            target = safe_resolve_path(repo, args["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args["content"], encoding="utf-8")
            return f"SUCCESS: Written {len(args['content'])} bytes to '{args['path']}'"

        if name == "run_command":
            cmd = args["command"].strip()
            # Command whitelist check
            if not cmd.startswith(ALLOWED_COMMAND_PREFIXES):
                return (
                    f"BLOCKED: Command not in safety whitelist. "
                    f"Permitted prefixes: {', '.join(ALLOWED_COMMAND_PREFIXES)}"
                )
            if any(forbidden in cmd.split() for forbidden in BLOCKED_COMMAND_KEYWORDS):
                return f"BLOCKED: Command contains disallowed keyword. Disallowed: {BLOCKED_COMMAND_KEYWORDS}"

            try:
                # OS-agnostic command tokenization
                cmd_parts = shlex.split(cmd, posix=(os.name != "nt"))
                # Map python / python3 binary to the active Python interpreter so py_compile works on all OS
                if cmd_parts and cmd_parts[0] in ("python", "python3"):
                    cmd_parts[0] = sys.executable

                proc = subprocess.run(
                    cmd_parts,
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                output = f"EXIT CODE: {proc.returncode}\n"
                if proc.stdout:
                    output += f"STDOUT:\n{proc.stdout[-3000:]}\n"
                if proc.stderr:
                    output += f"STDERR:\n{proc.stderr[-3000:]}\n"
                return output
            except FileNotFoundError:
                return (
                    f"TOOL NOT FOUND: The binary in '{cmd}' is not installed in the host system. "
                    f"Skipping this check and noting in migration report."
                )
            except subprocess.TimeoutExpired:
                return f"TIMEOUT: Command '{cmd}' exceeded execution limit of {timeout_sec}s."

        return f"ERROR: Unrecognized tool '{name}'."

    except Exception as exc:
        return f"TOOL EXECUTION ERROR: {str(exc)}"


# ==============================================================================
# Autonomous LLM Reasoning Loop
# ==============================================================================
def call_groq_with_retry(client: Groq, model: str, messages: List[Dict[str, Any]]) -> Any:
    """Robust Groq completion with exponential backoff on rate limits."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=4096,
            )
        except RateLimitError:
            wait_time = 12 * (attempt + 1)
            log_warn(f"Groq API rate limit encountered. Pausing for {wait_time}s (retry {attempt+1}/{max_retries})...")
            time.sleep(wait_time)
        except Exception as e:
            if "rate_limit" in str(e).lower():
                wait_time = 15 * (attempt + 1)
                log_warn(f"Rate limit notice: {e}. Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise e
    raise TimeoutError("Exceeded maximum Groq API retries due to persistent rate limiting.")


def run_agent_loop(repo: Path, model: str, max_turns: int = DEFAULT_MAX_TURNS) -> Optional[Dict[str, Any]]:
    client = Groq()
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Repository target path: {repo.name}. Begin autonomous assessment and migration.",
        },
    ]

    log_step("AGENT", f"Reasoning session initialized with model '{model}' (Turn budget: {max_turns})")

    malformed_retries = 0

    for turn in range(1, max_turns + 1):
        try:
            response = call_groq_with_retry(client, model, messages)
        except BadRequestError as err:
            malformed_retries += 1
            log_warn(f"Malformed tool call payload ({malformed_retries}/3): {str(err)[:120]}")
            if malformed_retries > 3:
                log_error("Aborting session: repeated malformed tool invocations from model.")
                return None
            messages.append({
                "role": "user",
                "content": "Your previous tool call had malformed JSON parameters. Please retry with strictly valid JSON.",
            })
            continue

        choice = response.choices[0].message
        if choice.content and choice.content.strip():
            log_step("THOUGHT", choice.content.strip()[:300] + ("..." if len(choice.content) > 300 else ""), Colors.BLUE)

        assistant_entry: Dict[str, Any] = {"role": "assistant", "content": choice.content or ""}
        if choice.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in choice.tool_calls
            ]
        messages.append(assistant_entry)

        if not choice.tool_calls:
            log_warn("Agent concluded turn without tool invocation.")
            return None

        completion_data = None
        for tc in choice.tool_calls:
            func_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "ERROR: Tool arguments were not valid JSON. Provide strict JSON formatting.",
                })
                continue

            arg_summary = json.dumps(args, ensure_ascii=False)
            if len(arg_summary) > 80:
                arg_summary = arg_summary[:77] + "..."
            log_tool(func_name, arg_summary)

            if func_name == "finish":
                completion_data = args
                tool_output = "Migration finalized."
            else:
                tool_output = execute_tool(repo, func_name, args)

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_output})

        if completion_data:
            return completion_data

    log_warn(f"Agent reached maximum execution turns limit ({max_turns}).")
    return None


# ==============================================================================
# CLI Entrypoint & Workflow Orchestrator
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Autonomous EC2 to AWS Lambda Migration Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze repo, migrate on feature branch, and push to origin
  python agent.py /path/to/my-ec2-app --push

  # Run migration locally without pushing to remote
  python agent.py /path/to/my-ec2-app --no-push

  # Use custom remote or model
  python agent.py /path/to/my-ec2-app --remote upstream --model llama-3.3-70b-versatile
        """,
    )
    parser.add_argument("repo", help="Path to local target git repository")
    parser.add_argument(
        "--push",
        dest="push",
        action="store_true",
        default=True,
        help="Push the migration feature branch to the remote git repository (default: enabled if remote exists)",
    )
    parser.add_argument(
        "--no-push",
        dest="push",
        action="store_false",
        help="Do NOT push the migration branch; keep changes strictly local",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Name of the git remote repository to push to (default: 'origin')",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Groq model identifier (default: '{DEFAULT_MODEL}')",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=DEFAULT_MAX_TURNS,
        help=f"Maximum agent decision loops (default: {DEFAULT_MAX_TURNS})",
    )

    args = parser.parse_args()
    repo_path = Path(args.repo).resolve()

    print("\n" + "=" * 70)
    print(f"{Colors.BOLD}AWS LAMBDA AUTONOMOUS MIGRATION AGENT{Colors.RESET}")
    print("=" * 70)

    # 1. Validation of target repository
    if not repo_path.is_dir():
        log_error(f"Target directory '{repo_path}' does not exist.")
        sys.exit(1)

    if not (repo_path / ".git").exists():
        check_git = run_git(repo_path, "rev-parse", "--is-inside-work-tree", check=False)
        if check_git.returncode != 0:
            log_step("GIT", f"Target directory '{repo_path.name}' is not a Git repo. Initializing Git repository automatically...")
            run_git(repo_path, "init")
            run_git(repo_path, "add", "-A")
            run_git(repo_path, "commit", "-m", "chore: initial commit before Lambda migration")
            log_success(f"Initialized Git repository in '{repo_path.name}'.")

    if not is_git_clean(repo_path):
        log_error(
            f"Git working tree in '{repo_path.name}' has uncommitted changes. "
            "Please commit or stash your changes before running the migration agent."
        )
        sys.exit(1)

    if not os.environ.get("GROQ_API_KEY"):
        log_error("Environment variable 'GROQ_API_KEY' is not set. Please export your Groq API key.")
        sys.exit(1)

    original_branch = get_current_branch(repo_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    migration_branch = f"lambda-migration-{timestamp}"

    # 2. Safe Feature Branch Isolation
    log_step("GIT", f"Original Branch: '{original_branch}'")
    log_step("GIT", f"Spawning isolated migration branch: '{migration_branch}'")
    run_git(repo_path, "checkout", "-b", migration_branch)

    migration_verdict = None
    try:
        migration_verdict = run_agent_loop(repo_path, model=args.model, max_turns=args.max_turns)
    except KeyboardInterrupt:
        log_warn("\nSession aborted by user.")
    finally:
        # Clean ephemeral cache artifacts
        for pycache in repo_path.rglob("__pycache__"):
            shutil.rmtree(pycache, ignore_errors=True)

        has_changes = not is_git_clean(repo_path)
        if has_changes:
            log_step("GIT", "Staging and committing generated migration artifacts...")
            run_git(repo_path, "add", "-A")
            commit_msg = (
                f"feat(aws-lambda): automated migration by Autonomous Agent\n\n"
                f"Verdict: {migration_verdict.get('verdict', 'processed') if migration_verdict else 'completed'}\n"
                f"Generated by: Lambda Migration Agent ({args.model})\n"
                f"Target Branch: {migration_branch}"
            )
            run_git(repo_path, "commit", "-m", commit_msg)
            log_success(f"Changes committed to isolated branch: '{migration_branch}'")

            # 3. Remote Push Handling
            if args.push:
                available_remotes = get_git_remotes(repo_path)
                if args.remote in available_remotes:
                    log_step("GIT", f"Pushing feature branch '{migration_branch}' to remote '{args.remote}'...")
                    push_res = run_git(repo_path, "push", "-u", args.remote, migration_branch, check=False)
                    if push_res.returncode == 0:
                        log_success(f"Pushed branch '{migration_branch}' to remote '{args.remote}' successfully!")
                        remote_url = get_remote_url(repo_path, args.remote)
                        pr_url = construct_pr_url(remote_url, migration_branch)
                        if pr_url:
                            print("\n" + "-" * 70)
                            log_success(f"Open Pull Request: {pr_url}")
                            print("-" * 70)
                    else:
                        log_warn(f"Remote push failed (non-fatal):\n{push_res.stderr.strip()}")
                        log_warn(f"You can manually push using: git push -u {args.remote} {migration_branch}")
                else:
                    log_warn(
                        f"Remote '{args.remote}' not found in repo (Available: {available_remotes or 'none'}). "
                        f"Changes remain safely committed locally on '{migration_branch}'."
                    )
            else:
                log_step("GIT", f"Push disabled (--no-push). Changes committed locally to '{migration_branch}'.")
        else:
            log_step("GIT", "No code changes generated during session.")

        # Always restore original working branch
        log_step("GIT", f"Restoring active workspace to original branch: '{original_branch}'")
        run_git(repo_path, "checkout", original_branch)

        # Cleanup empty branch if no commits were created
        diff_check = run_git(repo_path, "rev-list", f"{original_branch}..{migration_branch}", check=False)
        if not diff_check.stdout.strip():
            run_git(repo_path, "branch", "-D", migration_branch, check=False)

    print("\n" + "=" * 70)
    print(f"{Colors.BOLD}MIGRATION AGENT RUN SUMMARY{Colors.RESET}")
    print("=" * 70)
    if migration_verdict:
        verdict_str = migration_verdict.get("verdict", "N/A").upper()
        verdict_color = Colors.GREEN if verdict_str == "MIGRATE" else (Colors.YELLOW if verdict_str == "PARTIAL" else Colors.RED)
        if supports_color():
            print(f"VERDICT: {verdict_color}{Colors.BOLD}{verdict_str}{Colors.RESET}")
        else:
            print(f"VERDICT: {verdict_str}")
        print(f"SUMMARY: {migration_verdict.get('summary', 'No summary provided.')}\n")
    else:
        print("Agent concluded without an explicit verdict.\n")

    print(f"• Working Branch: {original_branch} (100% UNTOUCHED)")
    if has_changes:
        print(f"• Migration Branch: {migration_branch}")
        print(f"• Review Diff:     git diff {original_branch}..{migration_branch} --stat")
        print(f"• Checkout Branch: git checkout {migration_branch}")
        print(f"\n{Colors.BOLD}📖 NEXT STEPS FOR AWS DASHBOARD / CONSOLE:{Colors.RESET}")
        print(f"   1. Switch to migration branch:  {Colors.CYAN}git checkout {migration_branch}{Colors.RESET}")
        print(f"   2. Open '{Colors.CYAN}USER.md{Colors.RESET}' in the repo root for step-by-step AWS Dashboard instructions:")
        print(f"      - How to configure IAM Execution Roles & Policies in AWS Console")
        print(f"      - Environment variables to inject under Configuration -> Environment variables")
        print(f"      - API Gateway HTTP API trigger setup & live public endpoint")
        print(f"      - Sample test JSON event to paste into Lambda Console Test tab\n")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
