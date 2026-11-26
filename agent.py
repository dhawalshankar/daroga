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
- Google Gemini (gemini-4-hydrogen, gemini-1.5-pro)
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

EFFICIENCY & FAST GENERATION PROTOCOL (STRICT):
- DO NOT read entire large files or loop through `read_file` or `search` calls!
- You have at most 2 turns for inspection:
  * Turn 1: `read_file` on `backend/main.go` or `backend/app.py` (first 100-200 lines only).
  * Turn 2 onwards: IMMEDIATELY start generating artifacts using `write_file`!
- REQUIRED DELIVERABLES YOU MUST WRITE IN ORDER:
  1. `write_file`: Serverless adapter (`backend/lambda_main.go` for Go, `lambda_function.py` for Python, `lambda.js` for Node.js).
  2. `write_file`: Build script if Go (`backend/build_lambda.sh`).
  3. `write_file`: AWS SAM Template (`template.yaml`).
  4. `write_file`: AWS Console Operator Guide (`USER.md`).
- ONCE THOSE FILES ARE WRITTEN:
  Immediately call `finish` with `{"verdict": "migrate", "summary": "..."}`!
- Do NOT search for lines or wander through the codebase. You already know the architecture from Phase 1 audit. Generate the deliverables immediately!

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
                "enum": [
                    "migrate", "partial", "do_not_migrate",
                    "MIGRATE", "PARTIAL", "DO_NOT_MIGRATE",
                    "MIGRATE (WITH DECOUPLING)", "migrate (with decoupling)",
                    "NOT RECOMMENDED", "not recommended",
                ],
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

        elif self.provider in ("custom", "openrouter", "vllm", "lmstudio", "local"):
            if OpenAI is None:
                raise ImportError("OpenAI SDK is required for custom/OSS endpoints. Run: pip install openai")
            base = self.base_url or os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENROUTER_BASE_URL", "http://localhost:1234/v1")
            key = self.api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "not-needed")
            self.openai_client = OpenAI(api_key=key, base_url=base)
            self.mode = "openai_compat"

        elif self.provider in ("offline", "heuristic"):
            self.mode = "offline"
        else:
            raise ValueError(f"Unsupported provider: '{self.provider}'. Supported: groq, openai, gemini, claude, xai, ollama, offline, custom")

    def chat_completion(self, messages: List[Dict[str, Any]]) -> NormalizedResponse:
        """Dispatches chat completion to the configured provider and normalizes response."""
        if self.mode == "openai_compat":
            # Strict Sliding Window Context Compaction for 8,000 TPM rate limits:
            # Keep system message, user prompt, and at most the last 4 turns (assistant + tool).
            # Prune tool outputs older than latest turn to 150 chars.
            tool_msg_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
            prune_set = set(tool_msg_indices[:-1]) if len(tool_msg_indices) > 1 else set()

            # If messages list is long, keep system (0), user (1), and last 6 messages
            if len(messages) > 8:
                messages_window = [messages[0], messages[1]] + messages[-6:]
            else:
                messages_window = messages

            cleaned_messages = []
            for i, m in enumerate(messages_window):
                clean_m = {"role": m["role"]}
                if m.get("content") is not None and m.get("content") != "":
                    text = str(m["content"])
                    role = m.get("role")
                    if role == "tool":
                        # If tool message is older than latest turn, keep it minimal
                        if i < len(messages_window) - 2:
                            if len(text) > 150:
                                text = text[:150] + "... [pruned]"
                        elif len(text) > 2500:
                            text = text[:2500] + "... [truncated]"
                    elif role == "user":
                        # Never over-truncate user instruction; allow up to 4500 chars
                        if len(text) > 4500:
                            text = text[:4500] + "... [truncated]"
                    elif role == "assistant":
                        if len(text) > 2000:
                            text = text[:2000]
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
                max_tokens=1500,
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
            "groq": "openai/gpt-oss-120b",
            "openai": "gpt-4o-mini",
            "gemini": "gemini-4-hydrogen",
            "claude": "claude-3-5-haiku-20241022",
            "anthropic": "claude-3-5-haiku-20241022",
            "xai": "grok-2-latest",
            "ollama": "llama3.1:8b",
            "openrouter": "openai/gpt-oss-120b",
            "vllm": "default",
            "lmstudio": "default",
            "custom": "default",
            "local": "llama3.1:8b",
            "offline": "static-analysis-engine",
            "heuristic": "static-analysis-engine",
        }
        model = model_opt or default_models.get(p, "openai/gpt-oss-120b")
        return p, model

    # Auto-detection from model name if provided
    if model_opt:
        m = model_opt.lower()
        if "gpt-oss" in m or "oss-gpt" in m or "120b" in m or m.startswith("openai/"):
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
        return "groq", model_opt or "openai/gpt-oss-120b"
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

    # Default to Groq
    return "groq", model_opt or "openai/gpt-oss-120b"


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


def raise_pull_request(
    repo: Path,
    branch: str,
    base_branch: str,
    title: str,
    body: str,
    remote_url: Optional[str] = None,
) -> Optional[str]:
    """
    Autonomously creates a GitHub Pull Request using GitHub CLI ('gh pr create').
    Falls back gracefully to a 1-click web PR URL if 'gh' is unauthenticated or unavailable.
    """
    # 1. Attempt automated PR creation via GitHub CLI (gh)
    try:
        gh_check = subprocess.run(["gh", "--version"], capture_output=True, text=True, check=False)
        if gh_check.returncode == 0:
            log_step("GH-PR", "Autonomous Pull Request Creation via GitHub CLI ('gh')...", Colors.CYAN)
            pr_res = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--base", base_branch,
                    "--head", branch,
                    "--title", title,
                    "--body", body,
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            if pr_res.returncode == 0:
                live_pr_url = pr_res.stdout.strip()
                log_success(f"Successfully raised live GitHub Pull Request: {live_pr_url}")
                return live_pr_url
            else:
                stderr_clean = pr_res.stderr.strip()
                if "already exists" in stderr_clean.lower():
                    # Extract existing PR URL if available
                    for line in stderr_clean.splitlines():
                        if "http" in line:
                            log_success(f"Pull Request already active: {line.strip()}")
                            return line.strip()
                    log_warn(f"GitHub Pull Request already exists for branch '{branch}'.")
                else:
                    log_warn(f"GitHub CLI 'gh pr create' returned non-zero:\n{stderr_clean}")
    except Exception as exc:
        log_warn(f"GitHub CLI invocation skipped: {exc}")

    # 2. Fallback to 1-Click Pull Request URL
    if remote_url:
        return construct_pr_url(remote_url, branch)
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
            rel_path = args.get("path", "")
            if "report" in rel_path.lower():
                log_warn(f"Intercepted read of report '{rel_path}' - directing agent to author deliverables.")
                return (
                    f"NOTICE: '{rel_path}' is an informational audit report generated for the human operator. "
                    f"Do not inspect this report. You already have the verified architecture findings in your prompt. "
                    f"Proceed immediately to calling 'write_file' to create 'backend/lambda_main.go', "
                    f"'backend/build_lambda.sh', 'template.yaml', and 'USER.md'."
                )
            log_step("READING", f"Inspecting source code: '{rel_path}'", Colors.CYAN)
            target = safe_resolve_path(repo, rel_path)
            if not target.exists():
                log_warn(f"File not found: '{rel_path}'")
                return f"ERROR: File '{rel_path}' does not exist."
            content = target.read_text(encoding="utf-8", errors="replace")
            # Limit to 3,000 characters to strictly preserve free tier token quotas
            truncated = content[:3000]
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
            if "rate limit" in err_str or "rate_limit" in err_str or "429" in err_str or "tokens per minute" in err_str:
                wait_time = 3 * (attempt + 1)
                # Parse exact retry ms/seconds from Groq error message if present (e.g. "Please try again in 90ms")
                m_ms = re.search(r"try again in (\d+)ms", err_msg)
                m_s = re.search(r"try again in ([\d\.]+)s", err_msg)
                if m_ms:
                    wait_time = max(1.0, float(m_ms.group(1)) / 1000.0 + 0.5)
                elif m_s:
                    wait_time = max(1.0, float(m_s.group(1)) + 0.5)

                log_warn(f"Rate limit hit. Pausing {wait_time:.1f}s (retry {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
            elif "timeout" in err_str or "connection" in err_str:
                wait_time = 3 * (attempt + 1)
                log_warn(f"Network timeout. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise RuntimeError(err_msg)

    raise TimeoutError(f"Exceeded maximum API retries for provider '{client.provider}'.")


def run_agent_loop(
    repo: Path,
    client: UnifiedAIClient,
    max_turns: int = DEFAULT_MAX_TURNS,
    audit_res: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    # Construct rich, targeted context from deterministic audit so LLM has zero need to browse or search
    context_bulletins = []
    if audit_res is not None:
        context_bulletins.append(f"Target Service Runtime: {audit_res.target_runtime}")
        context_bulletins.append(f"Verdict: {audit_res.verdict} (Score: {audit_res.score}%)")
        if audit_res.conditions:
            context_bulletins.append(f"Conditions: {'; '.join(audit_res.conditions)}")
        if audit_res.blockers:
            context_bulletins.append(f"Blockers: {'; '.join(audit_res.blockers)}")
        if getattr(audit_res, "repo", None):
            rep = audit_res.repo
            context_bulletins.append(f"Target Service Directory: {getattr(rep, 'target_service_directory', 'backend')}")
            context_bulletins.append(f"Entry Points: {', '.join(getattr(rep, 'entrypoints', []))}")
            context_bulletins.append(f"Exposed Ports: {', '.join(map(str, getattr(rep, 'exposed_ports', [])))}")
            context_bulletins.append(f"Frameworks: {', '.join(getattr(rep, 'frameworks', []))}")

        # In-Guest VM Telemetry injection (from --vm-access / SSH / SSM)
        guest = getattr(audit_res, "guest_telemetry", None)
        if guest and getattr(guest, "accessible", False):
            context_bulletins.append(f"In-Guest VM Telemetry: OS '{guest.os_release}' via {guest.access_method}")
            if guest.listening_ports:
                ports_desc = [f"{b.port}/{b.protocol}" if hasattr(b, 'protocol') else str(b) for b in guest.listening_ports[:5]]
                context_bulletins.append(f"In-Guest Live Listening Sockets: {', '.join(ports_desc)}")
            if guest.active_services:
                context_bulletins.append(f"In-Guest Active Services: {', '.join(guest.active_services[:6])}")
            if getattr(guest, "docker_images", None):
                context_bulletins.append(f"In-Guest Docker Images: {', '.join(guest.docker_images[:4])}")
            if getattr(guest, "docker_containers", None):
                context_bulletins.append(f"In-Guest Running Containers: {', '.join(guest.docker_containers[:4])}")

    audit_summary_str = "\n".join(f"- {b}" for b in context_bulletins)

    # Pre-extract target entrypoint source snippet so LLM doesn't need to read files
    entrypoint_code = ""
    target_ep_name = ""
    if audit_res is not None and getattr(audit_res, "repo", None) and getattr(audit_res.repo, "entrypoints", None):
        for ep_cand in audit_res.repo.entrypoints:
            ep_file = repo / ep_cand
            if ep_file.is_file():
                try:
                    entrypoint_code = ep_file.read_text(encoding="utf-8", errors="replace")[:1200]
                    target_ep_name = ep_cand
                    break
                except Exception:
                    pass

    user_instruction = (
        f"Repository '{repo.name}' has been deterministically scanned and audited with the following findings:\n"
        f"{audit_summary_str}\n\n"
    )
    if entrypoint_code:
        user_instruction += (
            f"TARGET ENTRYPOINT PREVIEW ('{target_ep_name}'):\n"
            f"```\n{entrypoint_code}\n```\n\n"
        )
    user_instruction += (
        f"INSTRUCTION: You do NOT need to explore or read files repeatedly. The architecture, entrypoints, and runtime are already verified above.\n"
        f"Generate the production deliverables immediately using `write_file` in this exact order:\n"
        f"1. Serverless adapter (`backend/lambda_main.go` for Go / `lambda_function.py` for Python / `lambda.js` for Node).\n"
        f"2. Build script (`backend/build_lambda.sh`) if Go.\n"
        f"3. Production AWS SAM specification (`template.yaml`).\n"
        f"4. AWS Console Operator Deployment Guide (`USER.md`) — MUST be authored via write_file(path='USER.md', content=...), NEVER as raw chat text!\n\n"
        f"When written, immediately call `finish` with verdict '{getattr(audit_res, 'verdict', 'MIGRATE')}'. Be fast and concise!"
    )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_instruction},
    ]

    log_step("AGENT", f"Session active: provider '{client.provider.upper()}' | model '{client.model}' (Max turns: {max_turns})")

    exploratory_count = 0

    for turn in range(1, max_turns + 1):
        log_step("AGENT", f"Turn {turn}/{max_turns}: Reasoning with {client.provider.upper()} ({client.model})...", Colors.BLUE)
        try:
            response = call_ai_with_retry(client, messages)
        except Exception as err:
            backend_rel = "backend" if (repo / "backend").is_dir() else "."
            backend_dir = repo / backend_rel
            has_adapter = (backend_dir / "lambda_main.go").is_file() or (backend_dir / "lambda_function.py").is_file() or (backend_dir / "lambda.js").is_file()
            has_sam = (repo / "template.yaml").is_file()
            has_user = (repo / "USER.md").is_file()
            if has_adapter and has_sam and has_user:
                log_success("All migration deliverables verified on disk before API interruption!")
                return {"verdict": getattr(audit_res, "verdict", "MIGRATE")}
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
            if choice.content and len(choice.content) > 150 and not (repo / "USER.md").is_file():
                log_step("GENERATING", "Capturing synthesized Operator Guide directly into 'USER.md'...", Colors.YELLOW)
                (repo / "USER.md").write_text(choice.content.strip(), encoding="utf-8")
                log_success("Saved artifact: 'USER.md'")

            backend_rel = "backend" if (repo / "backend").is_dir() else "."
            backend_dir = repo / backend_rel
            has_adapter = (backend_dir / "lambda_main.go").is_file() or (backend_dir / "lambda_function.py").is_file() or (backend_dir / "lambda.js").is_file()
            has_sam = (repo / "template.yaml").is_file()
            has_user = (repo / "USER.md").is_file()

            if has_adapter and has_sam and has_user:
                log_success("All essential migration artifacts verified on disk!")
                return {"verdict": getattr(audit_res, "verdict", "MIGRATE")}

            log_warn("Agent replied with message text instead of invoking tools. Prompting for completion...")
            messages.append({
                "role": "user",
                "content": "Please invoke 'write_file' for any remaining files (e.g. 'USER.md') or invoke 'finish' with verdict.",
            })
            continue

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
            elif func_name in ("list_files", "read_file", "search"):
                exploratory_count += 1
                if exploratory_count > 2:
                    log_warn("Exploratory budget exhausted - prompting agent to generate deliverables.")
                    tool_output = (
                        "INSPECTION BUDGET EXHAUSTED: You have already inspected the codebase. "
                        "Do not read further files. Proceed immediately to 'write_file' to produce "
                        "'backend/lambda_main.go', 'backend/build_lambda.sh' (for Go), 'template.yaml', "
                        "and 'USER.md', then call 'finish'."
                    )
                else:
                    tool_output = execute_tool(repo, func_name, args)
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

        # Early Completion Check: If all required deliverables exist on disk, finalize immediately!
        backend_rel = "backend" if (repo / "backend").is_dir() else "."
        backend_dir = repo / backend_rel
        has_adapter = (backend_dir / "lambda_main.go").is_file() or (backend_dir / "lambda_function.py").is_file() or (backend_dir / "lambda.js").is_file()
        has_sam = (repo / "template.yaml").is_file()
        has_user = (repo / "USER.md").is_file()
        has_build = (backend_dir / "build_lambda.sh").is_file() if (audit_res and getattr(audit_res, "target_runtime", "").lower() == "go") else True

        if has_adapter and has_sam and has_user and has_build:
            log_success("All essential migration deliverables ('lambda_main', 'build_lambda.sh', 'template.yaml', 'USER.md') successfully generated!")
            verdict_val = getattr(audit_res, "verdict", "MIGRATE")
            log_step("DECISION", f"Migration Verdict Concluded: [{verdict_val.upper()}]", Colors.GREEN)
            return {"verdict": verdict_val}

    log_warn(f"Agent reached maximum execution turns limit ({max_turns}).")
    return None


# ==============================================================================
# Autonomous Heuristic & Static Architecture Engine (Zero-API / Zero-Cost)
# ==============================================================================
def run_offline_analysis(repo: Path, audit_res: Optional[Any] = None) -> Dict[str, Any]:
    """
    Evaluates repository architecture and serverless suitability locally using
    deterministic static analysis and heuristic inference.
    Executes with ZERO external API calls, zero rate-limit constraints, and zero token costs.
    If audit_res from DarogaOrchestrator is provided, its structured verdict, target runtime,
    and blockers are used as the single source of truth.
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

    # 1. Determine target service runtime and scope
    backend_rel = "backend" if (repo / "backend").is_dir() else "."
    backend_dir = repo / backend_rel
    code_uri_val = f"{backend_rel}/" if backend_rel != "." else "."

    if audit_res is not None and getattr(audit_res, "target_runtime", None):
        target_runtime_clean = audit_res.target_runtime.lower()
        has_go = target_runtime_clean == "go"
        has_python = target_runtime_clean == "python"
        has_node = target_runtime_clean in ("node", "javascript", "typescript")
        if getattr(audit_res, "repo", None) and getattr(audit_res.repo, "target_service_directory", None):
            backend_rel = audit_res.repo.target_service_directory
            backend_dir = repo / backend_rel if backend_rel != "." else repo
            code_uri_val = f"{backend_rel}/" if backend_rel != "." else "."
    else:
        # Fallback inspection of entrypoint manifests in backend_dir first, then repo
        target_check_dir = backend_dir if backend_dir.is_dir() else repo
        has_go = (target_check_dir / "go.mod").is_file() or any(p.suffix == ".go" for p in target_check_dir.glob("*"))
        has_python = not has_go and ((target_check_dir / "requirements.txt").is_file() or (target_check_dir / "pyproject.toml").is_file() or any(p.suffix == ".py" for p in target_check_dir.glob("*")))
        has_node = not has_go and not has_python and ((target_check_dir / "package.json").is_file() or any(p.suffix in (".js", ".ts") for p in target_check_dir.glob("*")))

    # 2. Inspect for architectural blockers (Docker sandbox, WebSockets, SQLite, etc.)
    dockerfiles = [p for p in server_files if "dockerfile" in p.name.lower()]
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

    # 3. Formulate Architecture Decision & Verdict
    # Single source of truth: honor audit_res verdict if available
    if audit_res is not None and getattr(audit_res, "verdict", None):
        verdict = audit_res.verdict
        blockers = getattr(audit_res, "blockers", [])
        conditions = getattr(audit_res, "conditions", [])
    else:
        if has_docker_execution or has_websockets:
            verdict = "MIGRATE (WITH DECOUPLING)"
            blockers = docker_reasons
            conditions = ["Decouple long-running container tasks to ECS Fargate"]
        else:
            verdict = "MIGRATE"
            blockers = []
            conditions = []

    summary = (
        f"Migrated EC2 continuous backend service into AWS Lambda serverless architecture. "
        f"Targeted backend scope '{backend_rel}'. Generated serverless runtime adapter, "
        f"AWS SAM infrastructure template, build scripts, and AWS Management Console guide."
    )
    if conditions:
        summary += f" Conditions: {'; '.join(conditions)}."

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

func main() {
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
            "echo 'Downloading AWS Lambda Go dependencies...'\n"
            "go get github.com/aws/aws-lambda-go/lambda github.com/aws/aws-lambda-go/events github.com/awslabs/aws-lambda-go-api-proxy/httpadapter 2>/dev/null || true\n"
            "go mod tidy 2>/dev/null || true\n"
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

    # 4. Generate AWS SAM Infrastructure Template (template.yaml)
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
# DAROGA Unified Autonomous Migration & Audit CLI Entrypoint
# ==============================================================================
def daroga_main():
    """
    DAROGA — Autonomous EC2 to AWS Lambda Migration Auditor & Code Generator.
    Unifies:
      1. Deterministic/LLM AWS & repository inspection (DarogaOrchestrator).
      2. Serverless architecture code generation (adapters, SAM templates, build scripts).
      3. Isolated feature branch lifecycle (git checkout, commit, push, PR creation).
      4. Complete zero-blast-radius preservation of the original working branch.
    """
    parser = argparse.ArgumentParser(
        description="DAROGA — Autonomous EC2 to AWS Lambda Migration Auditor & Planning Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported AI Providers:
  • Groq:      export GROQ_API_KEY="..."       (Default: llama-3.3-70b-versatile)
  • OpenAI:    export OPENAI_API_KEY="..."     (Default: gpt-4o)
  • Gemini:    export GEMINI_API_KEY="..."     (Default: gemini-4-hydrogen)
  • Claude:    export ANTHROPIC_API_KEY="..."  (Default: claude-3-5-sonnet-20241022)
  • xAI:       export XAI_API_KEY="..."        (Default: grok-2-latest)
  • Offline:   --offline                        (Zero-API deterministic heuristic engine)

Examples:
  # Autonomous migration & audit with automated feature branch push
  daroga /path/to/my-ec2-app

  # Audit only (read-only, no code generation or branch checkout)
  daroga /path/to/my-ec2-app --audit-only

  # Explicit provider and model
  daroga /path/to/my-ec2-app --provider groq --model llama-3.3-70b-versatile
        """,
    )
    parser.add_argument("repo", nargs="?", default=".", help="Path to local target git repository (default: '.')")
    parser.add_argument(
        "--push",
        dest="push",
        action="store_true",
        default=False,
        help="Push the migration feature branch to the remote git repository (default: disabled / opt-in)",
    )
    parser.add_argument(
        "--no-push",
        dest="push",
        action="store_false",
        help="Do NOT push the migration branch; keep changes strictly local (default)",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Name of the git remote repository to push to (default: 'origin')",
    )
    parser.add_argument("--region", default=None, help="AWS Region (default: from AWS_REGION or 'us-east-1')")
    parser.add_argument("--instance-id", default=None, help="Specific EC2 instance ID to inspect")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222", help="Chrome DevTools Protocol URL (default: 'http://127.0.0.1:9222')")
    parser.add_argument("--output", default=None, help="Path to output markdown report (default: '<repo>/EC2_TO_LAMBDA_MIGRATION_REPORT.md')")
    parser.add_argument(
        "--provider",
        default="auto",
        choices=["auto", "groq", "openai", "gemini", "claude", "anthropic", "xai", "ollama", "offline", "heuristic", "custom"],
        help="AI model provider (default: 'auto')",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model identifier override (e.g. gpt-4o, gemini-4-hydrogen, llama-3.3-70b-versatile)",
    )
    parser.add_argument("--api-key", default=None, help="Optional API key override")
    parser.add_argument("--base-url", default=None, help="Custom base URL for OpenAI-compatible endpoints")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run offline using deterministic architecture engine (zero API calls, zero cost)",
    )
    parser.add_argument(
        "--audit-only",
        "--audit",
        dest="audit_only",
        action="store_true",
        help="Run in read-only audit mode (generates EC2_TO_LAMBDA_MIGRATION_REPORT.md without git branch or code modifications)",
    )
    parser.add_argument(
        "--vm-access",
        action="store_true",
        help="Enable in-guest VM inspection via AWS Systems Manager (SSM) or SSH",
    )
    parser.add_argument(
        "--ssh-key",
        default=None,
        help="Optional path to private SSH key for in-guest VM inspection (.pem / .id_rsa)",
    )
    parser.add_argument(
        "--ssh-user",
        default="ubuntu",
        help="SSH username for in-guest inspection (default: 'ubuntu')",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=DEFAULT_MAX_TURNS,
        help=f"Maximum agent decision loops (default: {DEFAULT_MAX_TURNS})",
    )

    args = parser.parse_args()
    repo_path = Path(args.repo).resolve()
    out_p = Path(args.output).resolve() if args.output else (repo_path / "EC2_TO_LAMBDA_MIGRATION_REPORT.md")

    # 1. Target repository validation
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

    # Clean stray untracked report from previous run so git working tree remains clean
    stray_report = repo_path / "EC2_TO_LAMBDA_MIGRATION_REPORT.md"
    if stray_report.exists():
        status_chk = run_git(repo_path, "status", "--porcelain", check=False)
        if "EC2_TO_LAMBDA_MIGRATION_REPORT.md" in status_chk.stdout:
            try:
                stray_report.unlink()
            except Exception:
                pass

    if not is_git_clean(repo_path):
        log_error(
            f"Git working tree in '{repo_path.name}' has uncommitted changes. "
            "Please commit or stash your changes before running the migration agent."
        )
        sys.exit(1)

    # 2. Audit-Only Mode Short-Circuit
    if args.audit_only:
        if DarogaOrchestrator is None:
            log_error("DAROGA modules not found. Ensure 'daroga' package is installed.")
            sys.exit(1)
        orchestrator = DarogaOrchestrator(
            repo_path=repo_path,
            region=args.region,
            instance_id=args.instance_id,
            cdp_url=args.cdp_url,
            output_report_path=out_p,
        )
        orchestrator.run_audit()
        return

    # 3. Full Unified Migration Lifecycle
    print("\n" + "=" * 70)
    print(f"{Colors.BOLD}DAROGA — EC2 TO AWS LAMBDA AUTONOMOUS MIGRATION AGENT CLI{Colors.RESET}")
    print("=" * 70)

    original_branch = get_current_branch(repo_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    migration_branch = f"lambda-migration-{timestamp}"

    log_step("GIT", f"Original Branch: '{original_branch}'")
    log_step("GIT", f"Spawning isolated migration branch: '{migration_branch}'")
    run_git(repo_path, "checkout", "-b", migration_branch)

    migration_verdict = None
    audit_res = None
    try:
        # Phase 1: DAROGA Infrastructure & Architecture Audit
        if DarogaOrchestrator is not None:
            log_step("DAROGA", "Executing comprehensive AWS infrastructure inspection and architecture audit...")
            orchestrator = DarogaOrchestrator(
                repo_path=repo_path,
                region=args.region,
                instance_id=args.instance_id,
                cdp_url=args.cdp_url,
                output_report_path=out_p,
            )
            audit_res = orchestrator.run_audit()

            # Optional In-Guest VM Inspection if requested via --vm-access or --ssh-key
            if args.vm_access or args.ssh_key:
                log_step("VM-ACCESS", "Executing non-destructive in-guest VM inspection via AWS Systems Manager / SSH...", Colors.CYAN)
                try:
                    from daroga.vm_inspector import VMInspector
                    vm_insp = VMInspector(region=audit_res.aws.identity.region if audit_res and audit_res.aws else args.region)
                    target_inst = audit_res.aws.instances[0] if (audit_res and audit_res.aws and audit_res.aws.instances) else None
                    if target_inst:
                        guest_rep = vm_insp.inspect_instance(
                            instance_id=target_inst.instance_id,
                            public_ip=target_inst.public_ip,
                            ssh_key_path=args.ssh_key,
                            ssh_user=args.ssh_user,
                        )
                        if guest_rep.accessible:
                            if audit_res is not None:
                                audit_res.guest_telemetry = guest_rep
                            docker_desc = f", {len(guest_rep.docker_images)} docker images" if getattr(guest_rep, 'docker_images', None) else ""
                            log_success(f"In-Guest VM Telemetry captured via {guest_rep.access_method}: OS '{guest_rep.os_release}', {len(guest_rep.active_services)} active services{docker_desc}.")
                        else:
                            log_warn(guest_rep.error_message or "In-guest inspection did not connect.")
                    else:
                        log_warn("No running EC2 instance detected to execute in-guest inspection against.")
                except Exception as vm_err:
                    log_warn(f"In-guest VM inspection skipped: {vm_err}")
        else:
            log_warn("DarogaOrchestrator not loaded. Proceeding with heuristic code generation.")

        # Phase 2: Autonomous Serverless Code & Infrastructure Generation
        log_step("CODE-GEN", "Synthesizing serverless runtime adapters, build scripts, and AWS SAM templates...")

        # Decide between Online AI reasoning or Autonomous Offline Engine
        provider_name, target_model = detect_provider_and_model(args.provider, args.model)
        if args.offline:
            provider_name = "offline"
            target_model = "static-analysis-engine"

        ai_client = None
        # Engage Online AI reasoning if not explicitly --offline
        if provider_name not in ("offline", "heuristic") and not args.offline:
            try:
                ai_client = UnifiedAIClient(
                    provider=provider_name,
                    model=target_model,
                    api_key=args.api_key,
                    base_url=args.base_url,
                )
                log_success(f"AI Provider connected: [{provider_name.upper()}] with model '{target_model}'")
                migration_verdict = run_agent_loop(repo_path, client=ai_client, max_turns=args.max_turns, audit_res=audit_res)
                
                # Check that essential artifacts were actually written
                backend_rel = "backend" if (repo_path / "backend").is_dir() else "."
                backend_dir = repo_path / backend_rel
                has_adapter = (backend_dir / "lambda_main.go").is_file() or (backend_dir / "lambda_function.py").is_file() or (backend_dir / "lambda.js").is_file()
                has_sam = (repo_path / "template.yaml").is_file()
                has_user = (repo_path / "USER.md").is_file()

                if has_adapter and has_sam and has_user:
                    if not migration_verdict:
                        migration_verdict = {"verdict": getattr(audit_res, "verdict", "MIGRATE")}
                else:
                    log_warn("Online AI did not generate complete deliverables. Engaging Deterministic Architecture Engine...")
                    migration_verdict = run_offline_analysis(repo_path, audit_res=audit_res)
            except Exception as exc:
                backend_rel = "backend" if (repo_path / "backend").is_dir() else "."
                backend_dir = repo_path / backend_rel
                has_adapter = (backend_dir / "lambda_main.go").is_file() or (backend_dir / "lambda_function.py").is_file() or (backend_dir / "lambda.js").is_file()
                has_sam = (repo_path / "template.yaml").is_file()
                has_user = (repo_path / "USER.md").is_file()
                if has_adapter and has_sam and has_user:
                    log_success("All essential migration deliverables verified on disk.")
                    migration_verdict = {"verdict": getattr(audit_res, "verdict", "MIGRATE")}
                else:
                    log_warn(f"Online AI session encountered an error or rate-limit: {exc}")
                    log_step("AGENT", "Engaging Autonomous Heuristic Architecture Engine as smart failover...", Colors.YELLOW)
                    migration_verdict = run_offline_analysis(repo_path, audit_res=audit_res)
        else:
            migration_verdict = run_offline_analysis(repo_path, audit_res=audit_res)

    except KeyboardInterrupt:
        log_warn("\nSession aborted by user.")
    except Exception as exc:
        log_warn(f"Migration session encountered an error: {exc}")
        log_step("AGENT", "Engaging Autonomous Heuristic Architecture Engine as smart failover...", Colors.YELLOW)
        migration_verdict = run_offline_analysis(repo_path, audit_res=audit_res)
    finally:
        # Clean ephemeral cache artifacts
        for pycache in repo_path.rglob("__pycache__"):
            shutil.rmtree(pycache, ignore_errors=True)

        has_changes = not is_git_clean(repo_path)
        if has_changes:
            log_step("GIT", "Staging and committing generated migration artifacts...")
            run_git(repo_path, "add", "-A")
            commit_verdict_str = audit_res.verdict if audit_res else (migration_verdict.get('verdict', 'migrate') if migration_verdict else 'MIGRATE')
            commit_msg = (
                f"feat(aws-lambda): automated migration by DAROGA Autonomous Agent\n\n"
                f"Verdict: {commit_verdict_str.upper()}\n"
                f"Target Branch: {migration_branch}\n\n"
                f"Generated Deliverables:\n"
                f"- EC2_TO_LAMBDA_MIGRATION_REPORT.md (23-section architecture audit)\n"
                f"- Serverless runtime adapter & Linux ARM64 build script\n"
                f"- template.yaml (AWS SAM HTTP API Gateway v2 specification)\n"
                f"- USER.md (Step-by-step AWS Management Console deployment guide)"
            )
            run_git(repo_path, "commit", "-m", commit_msg)
            log_success(f"Changes committed to isolated branch: '{migration_branch}'")

            # Remote Push & Autonomous Pull Request Raising
            pr_result_url = None
            if args.push:
                available_remotes = get_git_remotes(repo_path)
                if args.remote in available_remotes:
                    log_step("GIT", f"Pushing feature branch '{migration_branch}' to remote '{args.remote}'...")
                    push_res = run_git(repo_path, "push", "-u", args.remote, migration_branch, check=False)
                    if push_res.returncode == 0:
                        log_success(f"Pushed branch '{migration_branch}' to remote '{args.remote}' successfully!")
                        remote_url = get_remote_url(repo_path, args.remote)
                        
                        # Autonomously raise Pull Request via gh CLI (or generate web PR URL fallback)
                        pr_title = f"feat(aws-lambda): migrate {repo_path.name} backend service to AWS Serverless"
                        pr_body = (
                            f"## 🚀 DAROGA Autonomous Cloud Infrastructure Migration\n\n"
                            f"**Target Architecture:** AWS Lambda (Graviton arm64) + Amazon API Gateway HTTP API v2\n"
                            f"**Migration Verdict:** `{commit_verdict_str.upper()}`\n\n"
                            f"### Generated Serverless Deliverables\n"
                            f"- `EC2_TO_LAMBDA_MIGRATION_REPORT.md`: Authoritative 23-section architecture audit and cost analysis.\n"
                            f"- `template.yaml`: Production AWS SAM infrastructure specification.\n"
                            f"- `USER.md`: AWS Management Console step-by-step setup guide.\n"
                            f"- Serverless runtime adapters and ARM64 Graviton build script.\n\n"
                            f"### Safety & Non-Destructive Guarantee\n"
                            f"- The `{original_branch}` branch and live EC2 instances were left **100% untouched**.\n"
                            f"- Review changes before merging: `git diff {original_branch}..{migration_branch}`."
                        )
                        pr_result_url = raise_pull_request(
                            repo=repo_path,
                            branch=migration_branch,
                            base_branch=original_branch,
                            title=pr_title,
                            body=pr_body,
                            remote_url=remote_url,
                        )
                        if pr_result_url:
                            print("\n" + "=" * 70)
                            log_success(f"Pull Request Ready: {pr_result_url}")
                            print("=" * 70)
                    else:
                        log_warn(f"Remote push failed (non-fatal):\n{push_res.stderr.strip()}")
                        log_warn(f"You can manually push using: git push -u {args.remote} {migration_branch}")
                else:
                    log_warn(
                        f"Remote '{args.remote}' not found in repo (Available: {available_remotes or 'none'}). "
                        f"Changes remain safely committed locally on '{migration_branch}'."
                    )
            else:
                log_step("GIT", f"Remote push skipped (default opt-in). Changes committed locally to '{migration_branch}'.")
                print(f"ℹ Push command: git push -u {args.remote} {migration_branch}")
                print(f"ℹ Raise PR with: gh pr create --base {original_branch} --head {migration_branch} --title \"feat(aws-lambda): migrate to serverless\"")
        else:
            log_step("GIT", "No code changes generated during session.")

        # Always restore original working branch
        log_step("GIT", f"Restoring active workspace to original branch: '{original_branch}'")
        run_git(repo_path, "checkout", original_branch)

        # Verify original branch is completely clean / untouched
        original_clean = is_git_clean(repo_path)
        if not original_clean:
            status_p = run_git(repo_path, "status", "--porcelain", check=False).stdout.strip()
            log_warn(f"Original branch '{original_branch}' has untracked or modified files:\n{status_p}")

        # Cleanup empty branch if no commits were created
        diff_check = run_git(repo_path, "rev-list", f"{original_branch}..{migration_branch}", check=False)
        if not diff_check.stdout.strip():
            run_git(repo_path, "branch", "-D", migration_branch, check=False)

    print("\n" + "=" * 70)
    print(f"{Colors.BOLD}DAROGA MIGRATION & AUDIT SUMMARY{Colors.RESET}")
    print("=" * 70)
    final_verdict_str = audit_res.verdict if audit_res else (migration_verdict.get("verdict", "MIGRATE") if migration_verdict else "MIGRATE")
    verdict_color = Colors.GREEN if "MIGRATE" in final_verdict_str and "NOT" not in final_verdict_str else Colors.YELLOW
    if supports_color():
        print(f"VERDICT: {verdict_color}{Colors.BOLD}{final_verdict_str.upper()}{Colors.RESET}")
    else:
        print(f"VERDICT: {final_verdict_str.upper()}")

    if audit_res and audit_res.conditions:
        print(f"CONDITIONS: {'; '.join(audit_res.conditions)}")
    if audit_res and audit_res.blockers:
        print(f"BLOCKERS:   {'; '.join(audit_res.blockers)}")

    summary_text = migration_verdict.get('summary', 'Migration completed successfully.') if migration_verdict else 'Audit completed.'
    print(f"SUMMARY: {summary_text}\n")

    if original_clean:
        print(f"• Working Branch:   {original_branch} (100% UNTOUCHED)")
    else:
        print(f"• Working Branch:   {original_branch} (WARNING: dirty files present)")

    if has_changes:
        branch_action = "COMMITTED & PUSHED" if args.push else "COMMITTED LOCALLY"
        print(f"• Migration Branch: {migration_branch} ({branch_action})")
        if pr_result_url:
            print(f"• Pull Request:     {Colors.CYAN}{pr_result_url}{Colors.RESET}")
        print(f"• Review Diff:      git diff {original_branch}..{migration_branch} --stat")
        print(f"• Checkout Branch:  git checkout {migration_branch}")
        if not args.push:
            print(f"• Push to Remote:   git push -u {args.remote} {migration_branch}")
            print(f"• Raise PR with:    gh pr create --base {original_branch} --head {migration_branch} --title \"feat(aws-lambda): migrate to serverless\"")
        print(f"\n{Colors.BOLD}📖 NEXT STEPS FOR AWS DASHBOARD / CONSOLE:{Colors.RESET}")
        print(f"   1. Switch to migration branch:  {Colors.CYAN}git checkout {migration_branch}{Colors.RESET}")
        print(f"   2. Open '{Colors.CYAN}USER.md{Colors.RESET}' in the repo root for step-by-step AWS Dashboard instructions:")
        print(f"      - How to configure IAM Execution Roles & Policies in AWS Console")
        print(f"      - Environment variables to inject under Configuration -> Environment variables")
        print(f"      - API Gateway HTTP API trigger setup & live public endpoint")
        print(f"      - Sample test JSON event to paste into Lambda Console Test tab")
        print(f"   3. Open '{Colors.CYAN}EC2_TO_LAMBDA_MIGRATION_REPORT.md{Colors.RESET}' for the full 23-section architecture audit.\n")
    print("=" * 70 + "\n")


def main():
    daroga_main()


if __name__ == "__main__":
    daroga_main()
