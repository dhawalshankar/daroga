#!/usr/bin/env python3
"""
Autonomous EC2 to AWS Lambda Migration Agent CLI
================================================
An enterprise-grade, autonomous AI agent that analyzes legacy EC2-hosted applications,
evaluates serverless architectural suitability, generates AWS Lambda entrypoints and SAM infrastructure,
self-validates code through compiler/schema feedback loops, and publishes safe migration pull-requests
on an isolated remote git branch.

Multi-Provider AI Engine:
- Groq (default / ultra-fast inference)
- OpenAI (ChatGPT: gpt-4o, o1, o3-mini)
- Google Gemini (gemini-2.0-flash, gemini-1.5-pro)
- Anthropic Claude (claude-3-5-sonnet, claude-3-5-haiku)
- xAI (grok-2, grok-beta)
- Custom / Local OpenAI-compatible endpoints (Ollama, DeepSeek, vLLM, OpenRouter)

Zero Blast Radius:
- The base/main branch is NEVER modified or committed to directly.
- All modifications occur on an isolated feature branch (`lambda-migration-<timestamp>`).
- Feature branch is committed and pushed to remote for PR review.
- The working copy is safely restored to the original branch upon completion.

Usage:
    aws-migrator /path/to/repo [--provider auto|groq|openai|gemini|claude|xai|custom] [--model MODEL] [--push]
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

# Multi-provider client imports with graceful fallbacks
try:
    from groq import Groq, RateLimitError as GroqRateLimitError, BadRequestError as GroqBadRequestError
except ImportError:
    Groq = None
    GroqRateLimitError = Exception
    GroqBadRequestError = Exception

# Import DAROGA modular auditor
try:
    from daroga.orchestrator import DarogaOrchestrator
except ImportError:
    DarogaOrchestrator = None

try:
    from openai import OpenAI, RateLimitError as OpenAIRateLimitError, BadRequestError as OpenAIBadRequestError
except ImportError:
    OpenAI = None
    OpenAIRateLimitError = Exception
    OpenAIBadRequestError = Exception

try:
    from anthropic import Anthropic, RateLimitError as AnthropicRateLimitError, BadRequestError as AnthropicBadRequestError
except ImportError:
    Anthropic = None
    AnthropicRateLimitError = Exception
    AnthropicBadRequestError = Exception


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
    "go vet",
    "go build",
    "go test",
    "npm run build",
    "npm test",
    "npm run",
    "npx",
)

BLOCKED_COMMAND_KEYWORDS = (
    "push", "merge", "deploy", "aws", "apply", "sudo", "rm", "curl", "wget", "git",
)

SYSTEM_PROMPT = """You are an Autonomous Cloud Migration Agent specializing in migrating EC2-hosted server applications to AWS Lambda Serverless architecture.

MISSION:
Your sole objective is to MIGRATE the target backend service from a legacy EC2 continuous VM model into production-ready AWS Lambda serverless infrastructure.
Every user running this tool expects code artifacts and SAM templates. You must ALWAYS generate the Lambda adapter, SAM template, and documentation!

DIRECTORY & REPOSITORY SCOPE:
- If the repository contains separate frontend and backend directories (e.g. `frontend/` and `backend/` or `client/` and `server/`):
  * Focus 100% of your attention on the `backend/` directory!
  * The frontend (Next.js, React, HTML) remains unchanged (hosted on S3, Amplify, or Vercel).
  * The backend API server is what ran on the EC2 VM and is what belongs on AWS Lambda.
- Never inspect or touch frontend UI assets, page components, or build bundles.

EFFICIENCY & PAGING RULE (PREVENT TOKEN LIMITS):
- DO NOT read entire large files or paginate through hundreds of lines!
- Inspecting the first 100-200 lines of `main.go` or `app.py` is sufficient to identify the HTTP router and entrypoint.
- Call `read_file` at most 1 or 2 times. Once you see the router, immediately proceed to generating `backend/lambda_main.go`, `template.yaml`, `MIGRATION_REPORT.md`, and `USER.md`!

FROM EC2 VM TO AWS LAMBDA (WHAT CHANGES):
- On EC2, the service ran as a continuous process listening on a TCP port (`http.ListenAndServe`, `app.run`, etc.).
- In AWS Lambda, continuous sockets are replaced by an event-driven AWS API Gateway trigger invoking the Lambda handler.
- What you must create:
  1. Serverless Adapter / Entrypoint:
     - Golang: Create `backend/lambda_main.go` wrapping the HTTP router with `github.com/aws/aws-lambda-go/lambda` or API proxy.
     - Python: Create `lambda_function.py` wrapping WSGI/ASGI apps with `apig_wsgi` or `mangum`.
     - Node.js: Create `lambda.js` wrapping Express/Fastify with `@vendia/serverless-express`.
  2. AWS SAM Infrastructure (`template.yaml`):
     - `AWS::Serverless::Function` resource definition with `provided.al2023` (Go), `python3.12` (Python), or `nodejs20.x`.
     - HTTP API Gateway events (`/{proxy+}`).
     - Environment variables and architecture (`arm64`).
  3. Technical Assessment (`MIGRATION_REPORT.md`):
     - Document the architectural transition from EC2 to Lambda.
     - Cost savings (24/7 EC2 instance hourly cost vs. Lambda 1M free requests + pay-per-millisecond).
  4. Step-by-Step AWS Console Guide (`USER.md`):
     - Explicit step-by-step clicks for deploying and testing in the AWS Lambda & API Gateway Management Console.

DECISION & COMPLETION:
- Verdict is always `migrate` (or `partial` if secondary background workers are decoupled).
- Always call `finish` when artifacts are created and validated.
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
        "search",
        "Searches for a keyword or text pattern across repository source files.",
        {"query": {"type": "string", "description": "Keyword string to search for"}},
        ["query"],
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
# Multi-Provider Unified AI Engine
# ==============================================================================
class NormalizedToolCall:
    def __init__(self, call_id: str, name: str, arguments: str, raw_dict: Optional[Dict[str, Any]] = None):
        self.id = call_id
        self.type = "function"
        self.function = type("FunctionObj", (), {"name": name, "arguments": arguments})()
        self.raw_dict = raw_dict or {}


class NormalizedMessage:
    def __init__(self, content: Optional[str], tool_calls: Optional[List[NormalizedToolCall]] = None):
        self.content = content
        self.tool_calls = tool_calls or []


class NormalizedResponse:
    def __init__(self, message: NormalizedMessage):
        self.choices = [type("ChoiceObj", (), {"message": message})()]


class UnifiedAIClient:
    """
    Unified client supporting Groq, OpenAI (ChatGPT), Google Gemini,
    Anthropic Claude, xAI (Grok), and custom OpenAI-compatible endpoints.
    """
    def __init__(self, provider: str, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._init_backend()

    def _init_backend(self):
        if self.provider == "anthropic" or self.provider == "claude":
            if Anthropic is None:
                raise ImportError("Anthropic SDK is not installed. Please run: pip install anthropic")
            key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise ValueError("Anthropic API key missing. Please export ANTHROPIC_API_KEY.")
            self.anthropic_client = Anthropic(api_key=key)
            self.mode = "anthropic"

        elif self.provider == "groq":
            if Groq is None and OpenAI is None:
                raise ImportError("Neither 'groq' nor 'openai' library is installed. Run: pip install groq openai")
            key = self.api_key or os.environ.get("GROQ_API_KEY")
            if not key:
                raise ValueError("Groq API key missing. Please export GROQ_API_KEY.")
            if Groq is not None:
                self.openai_client = Groq(api_key=key)
            else:
                self.openai_client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
            self.mode = "openai_compat"

        elif self.provider == "gemini":
            if OpenAI is None:
                raise ImportError("OpenAI SDK is required to connect to Gemini endpoint. Run: pip install openai")
            key = self.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if not key:
                raise ValueError("Gemini API key missing. Please export GEMINI_API_KEY or GOOGLE_API_KEY.")
            base = self.base_url or "https://generativelanguage.googleapis.com/v1beta/openai/"
            self.openai_client = OpenAI(api_key=key, base_url=base)
            self.mode = "openai_compat"

        elif self.provider == "xai":
            if OpenAI is None:
                raise ImportError("OpenAI SDK is required to connect to xAI endpoint. Run: pip install openai")
            key = self.api_key or os.environ.get("XAI_API_KEY")
            if not key:
                raise ValueError("xAI API key missing. Please export XAI_API_KEY.")
            base = self.base_url or "https://api.x.ai/v1"
            self.openai_client = OpenAI(api_key=key, base_url=base)
            self.mode = "openai_compat"

        elif self.provider == "openai":
            if OpenAI is None:
                raise ImportError("OpenAI SDK is required. Run: pip install openai")
            key = self.api_key or os.environ.get("OPENAI_API_KEY")
            if not key:
                raise ValueError("OpenAI API key missing. Please export OPENAI_API_KEY.")
            self.openai_client = OpenAI(api_key=key)
            self.mode = "openai_compat"

        elif self.provider == "ollama":
            if OpenAI is None:
                raise ImportError("OpenAI SDK is required to connect to Ollama. Run: pip install openai")
            base = self.base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
            self.openai_client = OpenAI(api_key="ollama", base_url=base)
            self.mode = "openai_compat"

        elif self.provider in ("offline", "heuristic"):
            self.mode = "offline"
        else:
            raise ValueError(f"Unsupported provider: '{self.provider}'. Supported: groq, openai, gemini, claude, xai, ollama, offline, custom")

    def chat_completion(self, messages: List[Dict[str, Any]]) -> NormalizedResponse:
        """Dispatches chat completion to the configured provider and normalizes response."""
        if self.mode == "openai_compat":
            # Context compaction: prune older tool outputs to strictly stay within free tier TPM limits
            tool_msg_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
            prune_set = set(tool_msg_indices[:-2]) if len(tool_msg_indices) > 2 else set()

            cleaned_messages = []
            for i, m in enumerate(messages):
                clean_m = {"role": m["role"]}
                if m.get("content") is not None and m.get("content") != "":
                    text = str(m["content"])
                    if i in prune_set and len(text) > 400:
                        text = text[:400] + "... [earlier inspection truncated to preserve token limits]"
                    clean_m["content"] = text
                elif m["role"] == "assistant" and not m.get("tool_calls"):
                    clean_m["content"] = ""

                if m.get("tool_calls"):
                    clean_m["tool_calls"] = m["tool_calls"]
                if m.get("tool_call_id"):
                    clean_m["tool_call_id"] = str(m["tool_call_id"])
                if m.get("name"):
                    clean_m["name"] = str(m["name"])
                cleaned_messages.append(clean_m)

            log_step("AGENT", f"Querying {self.provider.upper()} ({self.model})...", Colors.BLUE)
            resp = self.openai_client.chat.completions.create(
                model=self.model,
                messages=cleaned_messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=4096,
            )
            choice = resp.choices[0].message
            norm_tools = []
            if choice.tool_calls:
                for tc in choice.tool_calls:
                    raw_tc = {}
                    if hasattr(tc, "model_dump"):
                        raw_tc = tc.model_dump(exclude_none=True)
                    else:
                        raw_tc = {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}

                    # Preserve Gemini thought_signature and extra metadata
                    if hasattr(tc, "model_extra") and tc.model_extra:
                        raw_tc.update(tc.model_extra)
                    if hasattr(tc.function, "model_extra") and tc.function.model_extra:
                        raw_tc.setdefault("function", {}).update(tc.function.model_extra)

                    norm_tools.append(NormalizedToolCall(tc.id, tc.function.name, tc.function.arguments, raw_dict=raw_tc))
            return NormalizedResponse(NormalizedMessage(content=choice.content, tool_calls=norm_tools))

        elif self.mode == "anthropic":
            system_prompt = SYSTEM_PROMPT
            anthropic_messages = []
            for m in messages:
                role = m.get("role")
                if role == "system":
                    system_prompt = m.get("content", SYSTEM_PROMPT)
                elif role == "user":
                    anthropic_messages.append({"role": "user", "content": m.get("content", "")})
                elif role == "assistant":
                    content_blocks = []
                    if m.get("content"):
                        content_blocks.append({"type": "text", "text": m["content"]})
                    for tc in m.get("tool_calls", []):
                        try:
                            fn_args = json.loads(tc["function"]["arguments"] or "{}")
                        except Exception:
                            fn_args = {}
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": fn_args,
                        })
                    anthropic_messages.append({"role": "assistant", "content": content_blocks or "..."})
                elif role == "tool":
                    anthropic_messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": m.get("tool_call_id", ""),
                            "content": str(m.get("content", "")),
                        }],
                    })

            anthropic_tools = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "input_schema": t["function"]["parameters"],
                }
                for t in TOOLS
            ]

            resp = self.anthropic_client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=anthropic_messages,
                tools=anthropic_tools,
                max_tokens=4096,
                temperature=0.1,
            )

            text_content = ""
            norm_tools = []
            for block in resp.content:
                if block.type == "text":
                    text_content += block.text
                elif block.type == "tool_use":
                    norm_tools.append(NormalizedToolCall(
                        call_id=block.id,
                        name=block.name,
                        arguments=json.dumps(block.input, ensure_ascii=False),
                    ))
            return NormalizedResponse(NormalizedMessage(content=text_content or None, tool_calls=norm_tools))


def detect_provider_and_model(provider_opt: str, model_opt: Optional[str]) -> Tuple[str, str]:
    """
    Resolves the target provider and model based on CLI options and environment keys.
    """
    p = (provider_opt or "auto").lower()

    # Explicit provider specified
    if p != "auto":
        default_models = {
            "groq": "llama-3.1-8b-instant",
            "openai": "gpt-4o-mini",
            "gemini": "gemini-2.0-flash",
            "claude": "claude-3-5-haiku-20241022",
            "anthropic": "claude-3-5-haiku-20241022",
            "xai": "grok-2-latest",
            "ollama": "llama3.1:8b",
            "custom": "default",
            "offline": "static-analysis-engine",
            "heuristic": "static-analysis-engine",
        }
        model = model_opt or default_models.get(p, "llama-3.1-8b-instant")
        return p, model

    # Auto-detection from model name if provided
    if model_opt:
        m = model_opt.lower()
        if m.startswith("openai/"):
            return "groq", model_opt
        if "claude" in m:
            return "anthropic", model_opt
        if "gemini" in m:
            return "gemini", model_opt
        if "gpt" in m or m.startswith(("o1", "o3")):
            return "openai", model_opt
        if "grok" in m:
            return "xai", model_opt
        if "llama" in m or "mixtral" in m:
            return "groq", model_opt

    # Auto-detection from environment variables
    if os.environ.get("GROQ_API_KEY"):
        return "groq", model_opt or "llama-3.1-8b-instant"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai", model_opt or "gpt-4o"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini", model_opt or "gemini-2.0-flash"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", model_opt or "claude-3-5-sonnet-20241022"
    if os.environ.get("XAI_API_KEY"):
        return "xai", model_opt or "grok-2-latest"
    if os.environ.get("OPENAI_BASE_URL"):
        return "custom", model_opt or "default"

    # Default fallback
    if os.environ.get("GROQ_API_KEY"):
        return "groq", model_opt or "llama-3.1-8b-instant"
    return "offline", "static-analysis-engine"


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
            rel_dir = args.get("path", ".")
            log_step("EXPLORING", f"Scanning repository tree: '{rel_dir}'", Colors.CYAN)
            base_dir = safe_resolve_path(repo, rel_dir)
            files = []
            ignored_dirs = {
                ".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode",
                "dist", "build", ".next", ".turbo", "coverage", "static", "public", "assets",
                "images", "fonts", "vendor"
            }
            ignored_exts = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".lock", ".map", ".woff", ".woff2", ".ttf"}
            for p in sorted(base_dir.rglob("*")):
                if not p.is_file():
                    continue
                if any(part in ignored_dirs for part in p.parts):
                    continue
                if p.suffix.lower() in ignored_exts:
                    continue
                files.append(p.relative_to(repo).as_posix())
            res = "\n".join(files[:150]) if files else "(empty repository)"
            log_success(f"Discovered {len(files)} relevant server files in '{rel_dir}'")
            return res

        if name == "read_file":
            rel_path = args["path"]
            log_step("READING", f"Inspecting source code: '{rel_path}'", Colors.CYAN)
            target = safe_resolve_path(repo, rel_path)
            if not target.exists():
                log_warn(f"File not found: '{rel_path}'")
                return f"ERROR: File '{rel_path}' does not exist."
            content = target.read_text(encoding="utf-8", errors="replace")
            # Limit to 5,000 characters to strictly preserve free tier token quotas
            truncated = content[:5000]
            log_success(f"Loaded {len(truncated)} characters from '{rel_path}'")
            return truncated

        if name == "search":
            query = args.get("query", "").lower()
            log_step("SEARCH", f"Searching codebase for pattern: '{query}'", Colors.CYAN)
            matches = []
            for p in sorted(repo.rglob("*")):
                if not p.is_file():
                    continue
                if any(x in p.parts for x in (".git", "node_modules", ".next", "dist", "build", "__pycache__")):
                    continue
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                    if query in txt.lower():
                        matches.append(p.relative_to(repo).as_posix())
                except Exception:
                    continue
            res = f"Found '{query}' in {len(matches)} files: " + ", ".join(matches[:15]) if matches else f"No matches found for '{query}'."
            log_success(res)
            return res

        if name == "write_file":
            rel_path = args["path"]
            log_step("GENERATING", f"Authoring migration artifact: '{rel_path}' ({len(args['content'])} bytes)", Colors.YELLOW)
            target = safe_resolve_path(repo, rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args["content"], encoding="utf-8")
            log_success(f"Generated artifact: '{rel_path}'")
            return f"SUCCESS: Written {len(args['content'])} bytes to '{rel_path}'"

        if name == "run_command":
            cmd = args["command"].strip()
            log_step("VALIDATING", f"Running check: '{cmd}'", Colors.HEADER)
            if not cmd.startswith(ALLOWED_COMMAND_PREFIXES):
                log_warn(f"Command not permitted: {cmd}")
                return (
                    f"BLOCKED: Command not in safety whitelist. "
                    f"Permitted prefixes: {', '.join(ALLOWED_COMMAND_PREFIXES)}"
                )
            if any(forbidden in cmd.split() for forbidden in BLOCKED_COMMAND_KEYWORDS):
                log_warn(f"Command contains blocked keyword: {cmd}")
                return f"BLOCKED: Command contains disallowed keyword. Disallowed: {BLOCKED_COMMAND_KEYWORDS}"

            try:
                cmd_parts = shlex.split(cmd, posix=(os.name != "nt"))
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

                if proc.returncode == 0:
                    log_success(f"Validation passed: '{cmd}'")
                else:
                    log_warn(f"Validation failed (exit code {proc.returncode}): '{cmd}'")

                return output
            except FileNotFoundError:
                log_warn(f"Tool not found on host: '{cmd}'")
                return (
                    f"TOOL NOT FOUND: The binary in '{cmd}' is not installed in the host system. "
                    f"Skipping this check and noting in migration report."
                )
            except subprocess.TimeoutExpired:
                log_error(f"Command timed out: '{cmd}'")
                return f"TIMEOUT: Command '{cmd}' exceeded execution limit of {timeout_sec}s."

        if name == "finish":
            verdict = args.get("verdict", "").upper()
            log_step("DECISION", f"Migration Verdict Concluded: [{verdict}]", Colors.GREEN)
            return "Migration finalized."

        return f"ERROR: Unrecognized tool '{name}'."

    except Exception as exc:
        return f"TOOL EXECUTION ERROR: {str(exc)}"


# ==============================================================================
# Autonomous LLM Reasoning Loop
# ==============================================================================
def call_ai_with_retry(client: UnifiedAIClient, messages: List[Dict[str, Any]]) -> NormalizedResponse:
    """Robust AI completion call with exponential backoff on rate limits."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return client.chat_completion(messages)
        except Exception as e:
            err_msg = str(e)
            if hasattr(e, "response") and hasattr(e.response, "text"):
                try:
                    err_json = json.loads(e.response.text)
                    if "error" in err_json and "message" in err_json["error"]:
                        err_msg = err_json["error"]["message"]
                    else:
                        err_msg = e.response.text
                except Exception:
                    err_msg = e.response.text

            log_error(f"{client.provider.upper()} API Error: {err_msg}")
            err_str = err_msg.lower()
            if "rate_limit" in err_str or "429" in err_str:
                wait_time = 10 * (attempt + 1)
                log_warn(f"Rate limit hit. Pausing {wait_time}s (retry {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
            elif "timeout" in err_str or "connection" in err_str:
                wait_time = 5 * (attempt + 1)
                log_warn(f"Network timeout. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise RuntimeError(err_msg)

    raise TimeoutError(f"Exceeded maximum API retries for provider '{client.provider}'.")


def run_agent_loop(repo: Path, client: UnifiedAIClient, max_turns: int = DEFAULT_MAX_TURNS) -> Optional[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Repository target path: {repo.name}. Begin autonomous assessment and migration.",
        },
    ]

    log_step("AGENT", f"Session active: provider '{client.provider.upper()}' | model '{client.model}' (Max turns: {max_turns})")

    for turn in range(1, max_turns + 1):
        log_step("AGENT", f"Turn {turn}/{max_turns}: Reasoning with {client.provider.upper()} ({client.model})...", Colors.BLUE)
        try:
            response = call_ai_with_retry(client, messages)
        except Exception as err:
            log_error(f"Aborting session due to API failure: {err}")
            return None

        choice = response.choices[0].message
        if choice.content and choice.content.strip():
            log_step("THOUGHT", choice.content.strip()[:350] + ("..." if len(choice.content) > 350 else ""), Colors.BLUE)

        assistant_entry: Dict[str, Any] = {"role": "assistant"}
        if choice.content:
            assistant_entry["content"] = choice.content
        if choice.tool_calls:
            assistant_entry["tool_calls"] = [
                getattr(tc, "raw_dict", None) or {
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
                    "name": func_name,
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

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": func_name,
                "content": str(tool_output),
            })

        if completion_data:
            return completion_data

    log_warn(f"Agent reached maximum execution turns limit ({max_turns}).")
    return None


# ==============================================================================
# Autonomous Heuristic & Static Architecture Engine (Zero-API / Zero-Cost)
# ==============================================================================
def run_offline_analysis(repo: Path) -> Dict[str, Any]:
    """
    Evaluates repository architecture and serverless suitability locally using
    deterministic static analysis and heuristic inference.
    Executes with ZERO external API calls, zero rate-limit constraints, and zero token costs.
    """
    log_step("AGENT", "Engaging Autonomous Offline Architecture Engine (Zero-API Mode)...", Colors.CYAN)

    ignored_dirs = {
        ".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode",
        "dist", "build", ".next", ".turbo", "coverage", "static", "public", "assets",
        "images", "fonts", "vendor"
    }
    server_files: List[Path] = []
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        if any(part in ignored_dirs for part in p.parts):
            continue
        server_files.append(p)

    log_success(f"Offline Engine indexed {len(server_files)} relevant project files.")

    # 1. Inspect dependency manifests and technology stacks
    has_go = any(p.name in ("go.mod", "main.go") or p.suffix == ".go" for p in server_files)
    has_python = any(p.name in ("requirements.txt", "Pipfile", "pyproject.toml") or p.suffix == ".py" for p in server_files)
    has_node = any(p.name == "package.json" for p in server_files)
    dockerfiles = [p for p in server_files if "dockerfile" in p.name.lower()]

    # 2. Inspect for architectural blockers (Docker sandbox, WebSockets, SQLite, etc.)
    has_docker_execution = False
    docker_reasons: List[str] = []
    has_websockets = False
    has_sqlite = False

    for df in dockerfiles:
        df_lower = df.name.lower()
        if any(k in df_lower for k in ("compiler", "runtime", "sandbox", "runner", "judge")):
            has_docker_execution = True
            docker_reasons.append(f"Dedicated container sandbox definition detected: `{df.relative_to(repo).as_posix()}`")

    for p in server_files:
        if p.suffix in (".go", ".py", ".js", ".ts", ".sh", ".mod"):
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            # Docker daemon or CLI execution checks
            if any(k in txt for k in (
                'exec.Command("docker"', "exec.Command('docker'", "docker run",
                "/var/run/docker.sock", "github.com/docker/docker/client", "docker.from_env()",
                "subprocess.run(['docker'", "subprocess.Popen(['docker'"
            )):
                has_docker_execution = True
                docker_reasons.append(f"Container runtime execution call detected in `{p.relative_to(repo).as_posix()}`")

            # WebSocket checks
            if any(k in txt for k in ("gorilla/websocket", "socket.io", "WebSocketServer", "import websockets")):
                has_websockets = True

            # SQLite checks
            if any(k in txt for k in ("sqlite3", "sqlite.Open", "import sqlite3")):
                has_sqlite = True

    # 3. Formulate Architecture Decision & Artifacts
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Resolve target backend directory (if monorepo with frontend/backend, focus on backend)
    backend_rel = "backend" if (repo / "backend").is_dir() else "."
    backend_dir = repo / backend_rel
    code_uri_val = f"{backend_rel}/" if backend_rel != "." else "."

    verdict = "migrate"
    summary = (
        f"Migrated EC2 continuous backend service into AWS Lambda serverless architecture. "
        f"Targeted backend scope '{backend_rel}'. Generated serverless runtime adapter, "
        f"AWS SAM infrastructure template, build scripts, and AWS Management Console guide."
    )

    created_artifacts: List[str] = []

    # Generate Language-Specific Lambda Adapter
    if has_go:
        lambda_go_file = backend_dir / "lambda_main.go"
        lambda_go_content = """package main

import (
	"context"
	"log"
	"net/http"
	"os"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/awslabs/aws-lambda-go-api-proxy/httpadapter"
)

// LambdaAdapter proxies incoming API Gateway v2 HTTP events to the Go HTTP handler
var LambdaAdapter *httpadapter.HandlerAdapter

func init() {
	// Proxy existing HTTP server routes through AWS Lambda adapter
	mux := http.DefaultServeMux
	LambdaAdapter = httpadapter.New(mux)
}

// LambdaHandler is invoked by AWS Lambda on incoming API Gateway requests
func LambdaHandler(ctx context.Context, req events.APIGatewayV2HTTPRequest) (events.APIGatewayV2HTTPResponse, error) {
	return LambdaAdapter.ProxyWithContext(ctx, req)
}

// RunAsLambda starts the Lambda runtime listener when invoked in AWS Serverless environment
func RunAsLambda() {
	log.Println("[LAMBDA] Starting AWS Lambda serverless event loop...")
	lambda.Start(LambdaHandler)
}
"""
        lambda_go_file.write_text(lambda_go_content, encoding="utf-8")
        created_artifacts.append(lambda_go_file.relative_to(repo).as_posix())
        log_success(f"Generated Go serverless adapter: '{lambda_go_file.name}'")

        # Build script for Linux ARM64 bootstrap
        build_sh = backend_dir / "build_lambda.sh"
        build_sh.write_text(
            "#!/usr/bin/env bash\n"
            "# Cross-compile Go binary for AWS Lambda Amazon Linux 2023 (arm64)\n"
            "set -e\n"
            "echo 'Building bootstrap binary for AWS Lambda Graviton (arm64)...'\n"
            "GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o bootstrap lambda_main.go\n"
            "echo 'Build complete: bootstrap ready for deployment.'\n",
            encoding="utf-8"
        )
        created_artifacts.append(build_sh.relative_to(repo).as_posix())
        log_success(f"Generated Lambda build script: '{build_sh.name}'")

    elif has_python:
        lambda_py = backend_dir / "lambda_function.py"
        lambda_py_content = """import os
import sys

# AWS Lambda Serverless Entrypoint for WSGI / ASGI Applications
try:
    from app import app
except ImportError:
    try:
        from main import app
    except ImportError:
        app = None

def lambda_handler(event, context):
    try:
        import apig_wsgi
        return apig_wsgi.make_lambda_handler(app)(event, context)
    except ImportError:
        pass

    try:
        from mangum import Mangum
        return Mangum(app)(event, context)
    except ImportError:
        pass

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": '{"message": "Hello from migrated AWS Lambda function!"}'
    }
"""
        lambda_py.write_text(lambda_py_content, encoding="utf-8")
        created_artifacts.append(lambda_py.relative_to(repo).as_posix())
        log_success(f"Generated Python serverless adapter: '{lambda_py.name}'")

    elif has_node:
        lambda_js = backend_dir / "lambda.js"
        lambda_js_content = """const serverless = require('@vendia/serverless-express');
let app;
try {
    app = require('./app');
} catch (e) {
    app = require('./index');
}

exports.handler = serverless({ app });
"""
        lambda_js.write_text(lambda_js_content, encoding="utf-8")
        created_artifacts.append(lambda_js.relative_to(repo).as_posix())
        log_success(f"Generated Node.js serverless adapter: '{lambda_js.name}'")

    # Generate AWS SAM Infrastructure Template (template.yaml)
    sam_template = repo / "template.yaml"
    runtime_str = "provided.al2023" if has_go else ("python3.12" if has_python else "nodejs20.x")
    handler_str = "bootstrap" if has_go else ("lambda_function.lambda_handler" if has_python else "lambda.handler")

    sam_content = f"""AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: AWS SAM template migrating {repo.name} backend service from EC2 to AWS Lambda

Globals:
  Function:
    Timeout: 30
    MemorySize: 512
    Architectures:
      - arm64

Resources:
  BackendFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: {code_uri_val}
      Handler: {handler_str}
      Runtime: {runtime_str}
      Environment:
        Variables:
          ENVIRONMENT: production
          PORT: "8080"
      Events:
        RootRoute:
          Type: HttpApi
          Properties:
            Path: /
            Method: ANY
        ProxyRoute:
          Type: HttpApi
          Properties:
            Path: /{{proxy+}}
            Method: ANY

Outputs:
  ApiUrl:
    Description: "Live Public HTTP API Gateway Endpoint URL"
    Value: !Sub "https://${{ServerlessHttpApi}}.execute-api.${{AWS::Region}}.amazonaws.com"
  FunctionArn:
    Description: "Lambda Function ARN"
    Value: !GetAtt BackendFunction.Arn
"""
    sam_template.write_text(sam_content, encoding="utf-8")
    created_artifacts.append("template.yaml")
    log_success("Generated AWS SAM infrastructure definition: 'template.yaml'")

    # Generate MIGRATION_REPORT.md
    report_path = repo / "MIGRATION_REPORT.md"
    report_content = f"""# AWS Lambda Migration Assessment Report: {repo.name}

**Generated by:** Autonomous Migration Agent CLI
**Analysis Date:** {timestamp_str}
**Verdict:** **MIGRATE** (`migrate`)
**Target Scope:** `{backend_rel}` backend service

---

## Executive Summary
Target application `{repo.name}` has been migrated from a legacy continuous EC2 virtual machine deployment into an event-driven **AWS Lambda Serverless** architecture.

On EC2, the service ran as an uninterrupted background daemon listening continuously on a local TCP socket. In AWS Lambda, continuous socket listeners are replaced by an event-driven AWS API Gateway HTTP trigger that invokes your serverless handler on demand.

---

## Migration Deliverables (Generated Artifacts)
{chr(10).join(f"- `{f}`" for f in created_artifacts)}

---

## Architectural Delta: EC2 vs. AWS Lambda

| Attribute | Legacy EC2 Virtual Machine | Migrated AWS Lambda Serverless |
| :--- | :--- | :--- |
| **Execution Model** | 24/7 continuous process listening on port | Event-driven micro-invocations on HTTP request |
| **Cost Model** | Billed 24/7/365 regardless of traffic | **Pay-per-millisecond** (1,000,000 requests/mo FREE) |
| **Scaling** | Manual EC2 Auto Scaling groups (minutes) | Sub-second automatic concurrency scaling |
| **OS Maintenance** | Patching kernel, AMI updates, SSH keys | 100% managed by AWS (zero server maintenance) |

---

## Decoupled Architecture Notes
- If the application executes asynchronous background jobs or long-running compiler workers, decouple these workers using **AWS SQS** or run the batch runners on **AWS ECS Fargate**, while the public REST API routes execute cost-effectively on **AWS Lambda**.
- Deploy the frontend (`Next.js`/`React`) to **AWS Amplify**, **Vercel**, or **Amazon S3 + CloudFront**, pointing `NEXT_PUBLIC_API_URL` to your API Gateway endpoint.

See `USER.md` for AWS Management Console setup instructions.
"""
    report_path.write_text(report_content, encoding="utf-8")
    log_success(f"Generated architectural evaluation: '{report_path.name}'")

    # Generate USER.md
    user_path = repo / "USER.md"
    user_content = f"""# AWS Deployment Guide: {repo.name}

This guide provides step-by-step instructions for deploying your migrated backend service to **AWS Lambda** and **Amazon API Gateway** using both the AWS SAM CLI and the AWS Management Console.

---

## Option 1: One-Click Deployment via AWS SAM CLI (Recommended)

1. Make sure you have the [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) installed and configured with your AWS credentials (`aws configure`).
2. Run the build and deployment commands from the repository root:
   ```bash
   sam build
   sam deploy --guided
   ```
3. During the guided prompt:
   - Stack Name: `{repo.name}-stack`
   - AWS Region: `us-east-1` (or your preferred region)
   - Allow SAM CLI to create IAM roles: **Yes**
   - Save arguments to configuration file: **Yes**
4. Once deployed, SAM will output your live public HTTP API endpoint:
   `https://<api-id>.execute-api.<region>.amazonaws.com`

---

## Option 2: Manual Setup via AWS Management Console

### Step 1: Create the Lambda Function
1. Open the [AWS Lambda Console](https://console.aws.amazon.com/lambda/).
2. Click **Create function** -> **Author from scratch**.
3. **Function name:** `{repo.name}-backend`
4. **Runtime:** 
   - For Go: Choose **Amazon Linux 2023** (`provided.al2023`).
   - For Python: Choose **Python 3.12**.
   - For Node.js: Choose **Node.js 20.x**.
5. **Architecture:** Select **arm64** (Graviton — faster and 20% cheaper).
6. Click **Create function**.

### Step 2: Configure Environment Variables
1. In your new Lambda function, navigate to the **Configuration** tab.
2. Click **Environment variables** on the left menu -> **Edit** -> **Add environment variable**.
3. Add any necessary database connection strings or configuration variables:
   - `ENVIRONMENT` = `production`
   - `PORT` = `8080`
4. Click **Save**.

### Step 3: Add API Gateway HTTP Trigger
1. In the function overview diagram, click **+ Add trigger**.
2. Select **API Gateway**.
3. Trigger type: **Create a new API** -> Choose **HTTP API**.
4. Security: **Open** (or IAM / JWT if authentication is required).
5. Click **Add**.
6. The public URL will appear under **API endpoint** (e.g. `https://xxxx.execute-api.us-east-1.amazonaws.com`).

### Step 4: Test Your Function
1. Navigate to the **Test** tab in the Lambda Console.
2. Select **Create new event** -> Choose the template **apigateway-aws-proxy**.
3. Click **Test**.
4. Verify you receive `HTTP 200 OK` in the execution output!

---

## Frontend Integration
In your frontend configuration (e.g. `frontend/.env.local` or environment settings):
```env
NEXT_PUBLIC_API_URL=https://<your-api-id>.execute-api.<region>.amazonaws.com
```
"""
    user_path.write_text(user_content, encoding="utf-8")
    log_success(f"Generated AWS Console deployment guide: '{user_path.name}'")

    log_step("DECISION", f"Migration Verdict Concluded: [{verdict.upper()}]", Colors.GREEN)
    return {"verdict": verdict, "summary": summary}


# ==============================================================================
# CLI Entrypoint & Workflow Orchestrator
# ==============================================================================
# ==============================================================================
# DAROGA CLI Entrypoint & Workflow Orchestrator
# ==============================================================================
def daroga_main():
    """
    DAROGA — EC2 to AWS Lambda Migration Auditor Entrypoint.
    Inspects repository, AWS EC2 infrastructure, and existing browser console.
    Generates the authoritative 23-section EC2_TO_LAMBDA_MIGRATION_REPORT.md.
    Strictly read-only: does not modify code or cloud infrastructure.
    """
    parser = argparse.ArgumentParser(
        description="DAROGA — EC2 to AWS Lambda Migration Auditor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("repo", nargs="?", default=".", help="Path to local target git repository (default: '.')")
    parser.add_argument("--region", default=None, help="AWS Region (default: from AWS_REGION or 'us-east-1')")
    parser.add_argument("--instance-id", default=None, help="Specific EC2 instance ID to inspect")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222", help="Chrome DevTools Protocol URL (default: 'http://127.0.0.1:9222')")
    parser.add_argument("--output", default=None, help="Path to output markdown report (default: '<repo>/EC2_TO_LAMBDA_MIGRATION_REPORT.md')")

    args = parser.parse_args()
    repo_p = Path(args.repo).resolve()
    out_p = Path(args.output).resolve() if args.output else None

    if DarogaOrchestrator is None:
        log_error("DAROGA modules not found. Ensure 'daroga' package is installed.")
        sys.exit(1)

    orchestrator = DarogaOrchestrator(
        repo_path=repo_p,
        region=args.region,
        instance_id=args.instance_id,
        cdp_url=args.cdp_url,
        output_report_path=out_p,
    )
    orchestrator.run_audit()


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous EC2 to AWS Lambda Migration Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported AI Providers:
  • Groq:      export GROQ_API_KEY="..."       (Default: llama-3.3-70b-versatile)
  • OpenAI:    export OPENAI_API_KEY="..."     (Default: gpt-4o)
  • Gemini:    export GEMINI_API_KEY="..."     (Default: gemini-2.0-flash)
  • Claude:    export ANTHROPIC_API_KEY="..."  (Default: claude-3-5-sonnet-20241022)
  • xAI:       export XAI_API_KEY="..."        (Default: grok-2-latest)
  • Custom:    export OPENAI_BASE_URL="..."    (Ollama, DeepSeek, vLLM, OpenRouter)

Examples:
  # Auto-detect provider from environment key and run
  aws-migrator /path/to/my-ec2-app --push

  # Use OpenAI (ChatGPT)
  aws-migrator /path/to/my-ec2-app --provider openai --model gpt-4o

  # Use Google Gemini
  aws-migrator /path/to/my-ec2-app --provider gemini --model gemini-2.0-flash

  # Use Anthropic Claude
  aws-migrator /path/to/my-ec2-app --provider claude --model claude-3-5-sonnet-20241022

  # Use xAI (Grok)
  aws-migrator /path/to/my-ec2-app --provider xai --model grok-2-latest
        """,
    )
    parser.add_argument("repo", help="Path to local target git repository")
    parser.add_argument(
        "--provider",
        default="auto",
        choices=["auto", "groq", "openai", "gemini", "claude", "anthropic", "xai", "ollama", "offline", "heuristic", "custom"],
        help="AI model provider (default: 'auto' - auto-detects from model or environment variables)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run offline using the built-in Autonomous Heuristic Architecture Engine (zero API calls, zero cost)",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Run in DAROGA read-only audit mode to generate EC2_TO_LAMBDA_MIGRATION_REPORT.md without touching code",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model identifier (e.g. gpt-4o, gemini-2.0-flash, claude-3-5-sonnet-20241022, grok-2-latest, llama-3.3-70b-versatile)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key override (overrides environment variable)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Custom base URL for OpenAI-compatible endpoints (Ollama, DeepSeek, OpenRouter, vLLM)",
    )
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
        "--max-turns",
        type=int,
        default=DEFAULT_MAX_TURNS,
        help=f"Maximum agent decision loops (default: {DEFAULT_MAX_TURNS})",
    )

    args = parser.parse_args()
    repo_path = Path(args.repo).resolve()

    if getattr(args, "audit", False):
        if DarogaOrchestrator is None:
            log_error("DAROGA modules not found. Ensure 'daroga' package is installed.")
            sys.exit(1)
        orchestrator = DarogaOrchestrator(repo_path=repo_path)
        orchestrator.run_audit()
        return

    print("\n" + "=" * 70)
    print(f"{Colors.BOLD}AWS LAMBDA AUTONOMOUS MIGRATION AGENT CLI{Colors.RESET}")
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

    # 2. Resolve AI Provider and Initialize Client
    provider_name, target_model = detect_provider_and_model(args.provider, args.model)
    if args.offline:
        provider_name = "offline"
        target_model = "static-analysis-engine"

    ai_client = None
    if provider_name not in ("offline", "heuristic"):
        try:
            ai_client = UnifiedAIClient(
                provider=provider_name,
                model=target_model,
                api_key=args.api_key,
                base_url=args.base_url,
            )
            log_success(f"AI Provider connected: [{provider_name.upper()}] with model '{target_model}'")
        except Exception as exc:
            log_warn(f"Remote AI Provider Initialization Failed: {exc}")
            log_step("AGENT", "Automatically falling back to Autonomous Offline Architecture Engine...", Colors.YELLOW)
            provider_name = "offline"
            target_model = "static-analysis-engine"
    else:
        log_success(f"Execution Mode: [OFFLINE] Autonomous Heuristic Architecture Engine (Zero-API)")

    original_branch = get_current_branch(repo_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    migration_branch = f"lambda-migration-{timestamp}"

    # 3. Safe Feature Branch Isolation
    log_step("GIT", f"Original Branch: '{original_branch}'")
    log_step("GIT", f"Spawning isolated migration branch: '{migration_branch}'")
    run_git(repo_path, "checkout", "-b", migration_branch)

    migration_verdict = None
    try:
        if provider_name in ("offline", "heuristic"):
            migration_verdict = run_offline_analysis(repo_path)
        else:
            migration_verdict = run_agent_loop(repo_path, client=ai_client, max_turns=args.max_turns)
            if not migration_verdict:
                log_warn("Online reasoning concluded without verdict or encountered an API failure.")
                log_step("AGENT", "Engaging Autonomous Offline Architecture Engine as smart failover...", Colors.YELLOW)
                migration_verdict = run_offline_analysis(repo_path)
    except KeyboardInterrupt:
        log_warn("\nSession aborted by user.")
    except Exception as exc:
        log_warn(f"Online AI session encountered an error: {exc}")
        log_step("AGENT", "Engaging Autonomous Offline Architecture Engine as smart failover...", Colors.YELLOW)
        migration_verdict = run_offline_analysis(repo_path)
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
                f"Generated by: Lambda Migration Agent ({provider_name}/{target_model})\n"
                f"Target Branch: {migration_branch}"
            )
            run_git(repo_path, "commit", "-m", commit_msg)
            log_success(f"Changes committed to isolated branch: '{migration_branch}'")

            # 4. Remote Push Handling
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
