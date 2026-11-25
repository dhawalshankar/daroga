#!/usr/bin/env python3
"""
EC2 -> Lambda Migration Agent
- Repo padhta hai, verdict deta hai, Lambda-ready code likhta hai
- Nayi LOCAL branch banata hai aur wahin commit karta hai
- NO push, NO merge, NO deploy, NO cloud calls

Powered by Groq API (OpenAI-style tool calling).

Usage:
    export GROQ_API_KEY=gsk_...
    python agent.py /path/to/repo
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from groq import BadRequestError, Groq, RateLimitError

MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
MAX_TURNS = 30

# Sirf ye commands chalenge (shell=False, to ; && | wagairah kaam hi nahi karte)
ALLOWED_PREFIXES = (
    "python -m py_compile", "python3 -m py_compile",
    "python -m pytest", "pytest",
    "sam validate", "node --check",
)
BLOCKED_WORDS = ("push", "merge", "deploy", "aws", "apply", "sudo", "rm", "curl", "wget", "git")

SYSTEM = """You are a cloud migration agent. You convert an app that runs on EC2 into an AWS Lambda-ready version.
You work ONLY on code inside the given repo (already on a fresh git branch). You cannot push, merge, deploy or touch the cloud.

Follow these steps:
1. ANALYZE: list_files, then read the main files. Check: framework, routes, local file writes,
   background threads/schedulers, websockets, long-running work (>15 min), in-memory state,
   DB connections, package size, env vars.
2. VERDICT: migrate | partial | do_not_migrate. Be honest. If the app is stateful or long-running, say so.
3. If verdict is migrate or partial, write the Lambda version:
   - lambda_function.py (handler; for Flask/FastAPI use the apig-wsgi / Mangum wrapper)
   - updated requirements.txt
   - template.yaml (AWS SAM) with API Gateway or EventBridge
   - Do NOT delete or overwrite the original app files unless required; prefer new files.
4. VALIDATE: run py_compile on the new files, and `sam validate` if available. If it fails, read the error and fix, then re-run.
5. Write MIGRATION_REPORT.md: verdict + reasons, what changed, what needs manual work
   (IAM role, env vars, VPC, secrets, state moved to S3/DynamoDB), and a rough monthly cost note (EC2 always-on vs Lambda per-request, label it an estimate).
6. Call finish with the verdict and a short summary.

Rules: write ONE file per tool call and keep files short. Always give valid JSON tool arguments.

If verdict is do_not_migrate, write only MIGRATION_REPORT.md explaining why and what to change first."""

def _tool(name, desc, props, required=()):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": list(required)}}}


TOOLS = [
    _tool("list_files", "List files in a repo folder (recursive, skips .git).",
          {"path": {"type": "string", "description": "Folder, default '.'"}}),
    _tool("read_file", "Read a text file from the repo.",
          {"path": {"type": "string"}}, ["path"]),
    _tool("write_file", "Create or overwrite a file inside the repo.",
          {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _tool("run_command", "Run a validation command (py_compile, pytest, sam validate, node --check) in the repo.",
          {"command": {"type": "string"}}, ["command"]),
    _tool("finish", "Call when done.",
          {"verdict": {"type": "string", "enum": ["migrate", "partial", "do_not_migrate"]},
           "summary": {"type": "string"}}, ["verdict", "summary"]),
]


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-c", "user.name=Lambda Migration Agent", "-c", "user.email=agent@local", *args],
        cwd=repo, capture_output=True, text=True, check=check,
    )


def safe_path(repo: Path, rel: str) -> Path:
    full = (repo / rel).resolve()
    if full != repo and repo not in full.parents:
        raise ValueError("Path repo ke bahar hai, allowed nahi.")
    if ".git" in full.relative_to(repo).parts:
        raise ValueError(".git folder allowed nahi.")
    return full


def run_tool(repo: Path, name: str, args: dict) -> str:
    try:
        if name == "list_files":
            base = safe_path(repo, args.get("path", "."))
            out = [str(p.relative_to(repo)) for p in sorted(base.rglob("*"))
                   if p.is_file() and ".git" not in p.relative_to(repo).parts
                   and "__pycache__" not in p.parts and "node_modules" not in p.parts]
            return "\n".join(out[:200]) or "(empty)"
        if name == "read_file":
            return safe_path(repo, args["path"]).read_text(errors="replace")[:12000]
        if name == "write_file":
            p = safe_path(repo, args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"])
            return f"Wrote {args['path']}"
        if name == "run_command":
            cmd = args["command"].strip()
            if not cmd.startswith(ALLOWED_PREFIXES) or any(w in cmd.split() for w in BLOCKED_WORDS):
                return f"BLOCKED: command allowed nahi hai. Allowed: {ALLOWED_PREFIXES}"
            try:
                r = subprocess.run(shlex.split(cmd), cwd=repo, capture_output=True, text=True, timeout=120)
            except FileNotFoundError:
                return "Tool installed nahi hai (e.g. sam). Skip karke report mein likho."
            return f"exit={r.returncode}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}"
        return f"Unknown tool {name}"
    except Exception as e:
        return f"ERROR: {e}"


def chat(client, messages):
    """Groq call with retry on rate limit (free tier ke liye)."""
    for attempt in range(5):
        try:
            return client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOLS,
                tool_choice="auto", temperature=0.2, max_tokens=4096)
        except RateLimitError:
            wait = 15 * (attempt + 1)
            print(f"  (rate limit, {wait}s ruk raha hoon)")
            time.sleep(wait)
    raise RuntimeError("Groq rate limit baar-baar aa rahi hai, thodi der baad try karo.")


def agent_loop(repo: Path):
    client = Groq()  # GROQ_API_KEY env se leta hai
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Repo path: {repo}. Start the analysis."},
    ]
    malformed = 0
    for _ in range(MAX_TURNS):
        try:
            resp = chat(client, messages)
        except BadRequestError as e:
            malformed += 1
            print(f"  (malformed tool call: {str(e)[:120]})")
            if malformed > 3:
                return None
            messages.append({"role": "user", "content":
                             "Your last tool call was malformed. Retry with valid JSON arguments and a shorter file."})
            continue

        msg = resp.choices[0].message
        if msg.content and msg.content.strip():
            print(f"\n[agent] {msg.content.strip()}")
        entry = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [{"id": c.id, "type": "function",
                                    "function": {"name": c.function.name,
                                                 "arguments": c.function.arguments}}
                                   for c in msg.tool_calls]
        messages.append(entry)
        if not msg.tool_calls:
            return None

        done = None
        for c in msg.tool_calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                messages.append({"role": "tool", "tool_call_id": c.id,
                                 "content": "ERROR: arguments valid JSON nahi the, dobara try karo."})
                continue
            print(f"  -> {c.function.name} {json.dumps(args)[:100]}")
            if c.function.name == "finish":
                done = args
                out = "ok"
            else:
                out = run_tool(repo, c.function.name, args)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": out})
        if done:
            return done
    print("Max turns reached.")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    repo = Path(ap.parse_args().repo).resolve()

    if not (repo / ".git").exists():
        sys.exit("Ye git repo nahi hai. Pehle `git init` + ek commit karo.")
    if git(repo, "status", "--porcelain").stdout.strip():
        sys.exit("Working tree clean nahi hai. Pehle commit ya stash karo.")

    orig = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    branch = f"lambda-migration-{datetime.now():%Y%m%d-%H%M%S}"
    git(repo, "checkout", "-b", branch)
    print(f"Original branch: {orig} | Agent branch: {branch}")

    try:
        result = agent_loop(repo)
    finally:
        for d in repo.rglob("__pycache__"):   # validation ka kachra commit na ho
            subprocess.run(["rm", "-rf", str(d)])
        if git(repo, "status", "--porcelain").stdout.strip():
            git(repo, "add", "-A")
            git(repo, "commit", "-m", "Lambda migration (auto-generated by agent) - review before merge")
            print(f"\nCommitted on {branch} (not pushed, not merged).")
        else:
            print("\nKoi change nahi hua, branch hata raha hoon.")
        git(repo, "checkout", orig)
        if git(repo, "rev-list", f"{orig}..{branch}", check=False).stdout.strip() == "":
            git(repo, "branch", "-D", branch, check=False)

    if result:
        print(f"\nVERDICT: {result['verdict']}\n{result['summary']}")
    print(f"\nReview karo:  git diff {orig}..{branch} --stat\n"
          f"Files dekho:   git checkout {branch}")


if __name__ == "__main__":
    main()
