# Autonomous EC2 to AWS Lambda Migration Agent CLI

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![AWS Lambda](https://img.shields.io/badge/AWS-Lambda%20Ready-FF9900.svg)](https://aws.amazon.com/lambda/)
[![AWS SAM](https://img.shields.io/badge/AWS-SAM%20Validated-red.svg)](https://aws.amazon.com/serverless/sam/)
[![Groq Fast Inference](https://img.shields.io/badge/LLM-Groq%20Tool%20Calling-orange.svg)](https://groq.com/)
[![Cross-Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-blueviolet.svg)]()
[![Zero Blast Radius](https://img.shields.io/badge/Safety-Zero%20Blast%20Radius-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An enterprise-grade **autonomous AI agent CLI** (`aws-migrator`) that converts legacy EC2-hosted web services into production-ready AWS Lambda architectures. It analyzes existing application codebases at **any file path**, evaluates serverless feasibility, generates Lambda handlers and AWS SAM templates, self-validates through compiler/schema feedback loops, and publishes safe migration pull requests on an isolated git branch.

In addition to technical migration artifacts, the agent autonomously generates **`USER.md`** inside the migrated repository — a step-by-step AWS Management Console guide detailing exactly what configurations, IAM roles, and environment variables to set on your AWS Dashboard to bring the service live.

---

## Table of Contents

- [Zero File Copying: Work on Any External Repository](#zero-file-copying-work-on-any-external-repository)
- [Repository Structure & Reference Projects](#repository-structure--reference-projects)
- [Why an Autonomous Agent vs a Transpiler/Script?](#why-an-autonomous-agent-vs-a-transpiler-script)
- [The Autonomous Decision Engine](#the-autonomous-decision-engine)
- [Architecture & ReAct Workflow](#architecture--react-workflow)
- [Safety & Zero Blast Radius Guarantee](#safety--zero-blast-radius-guarantee)
- [Installation & CLI Setup](#installation--cli-setup)
- [CLI Reference & Usage](#cli-reference--usage)
- [Generated Migration Artifacts (Including USER.md)](#generated-migration-artifacts)
- [End-to-End Live Demonstration Walkthrough](#end-to-end-live-demonstration-walkthrough)
- [Security Sandbox Specifications](#security-sandbox-specifications)

---

## Zero File Copying: Work on Any External Repository

You **never need to copy or move your project files** into this agent's folder. The CLI operates directly on any local repository path on your machine:

```bash
# Point directly to your EC2 project located anywhere on your system:
aws-migrator "C:\Users\username\Desktop\code\my-ec2-api" --push

# Or on Linux / macOS:
aws-migrator /home/ubuntu/projects/billing-service --push
```

### What Happens When You Run the CLI:
1. **Target Verification**: The CLI inspects your external project directory, verifies it is a Git repo, and confirms a clean working tree.
2. **Safe Branch Spawning**: Inside *your* project, it creates an isolated branch (`lambda-migration-<timestamp>`).
3. **Autonomous Agent Loop**: It inspects routes, threads, and databases, writes `lambda_function.py`, `template.yaml`, `MIGRATION_REPORT.md`, and `USER.md`, and runs syntax validation (`py_compile`, `sam validate`).
4. **Git Commit & Remote Push**: It commits the changes on the migration branch and pushes it to your remote repository (`origin`).
5. **PR Link Generation**: Prints a direct 1-click GitHub / GitLab Pull Request URL.
6. **Workspace Restoration**: Safely checks out your original working branch (`main` / `master`). **Your base code is 100% untouched.**
7. **Actionable AWS Dashboard Guide**: You checkout the migration branch and open `USER.md` for a complete click-by-click AWS Console setup guide.

---

## Repository Structure & Reference Projects

The repository includes two dedicated reference applications:

```
lambda-agent/
├── README.md              # Complete system documentation
├── agent.py               # Autonomous Migration Agent Engine
├── aws-migrator           # Linux / macOS CLI executable
├── aws-migrator.cmd       # Windows Command Prompt / PowerShell executable
├── setup.py               # Package metadata and CLI entrypoints
├── pyproject.toml         # Modern build configuration
├── requirements.txt       # Dependencies
├── docs/
│   └── PRD.md             # Product Requirements Document
├── ec2_app/               # Source project: Legacy EC2 Flask service
│   ├── app.py
│   └── requirements.txt
└── lambda_app/            # Target architecture: Migrated AWS Lambda service
    ├── app.py
    ├── lambda_function.py
    ├── template.yaml
    ├── requirements.txt
    ├── MIGRATION_REPORT.md
    └── USER.md
```

- **`ec2_app/`**: A realistic legacy EC2 REST service running Flask with an active host/port listener (`app.run()`). Use this folder to run live end-to-end migration tests.
- **`lambda_app/`**: The reference target architecture demonstrating the expected output artifacts produced by the agent.

---

## Why an Autonomous Agent vs a Transpiler/Script?

A frequent question is: *"Why build an AI Agent instead of a conversion script?"*

A standard script or AST transpiler blindly replaces code patterns (e.g., swapping `app.run()` with a WSGI adapter and outputting boilerplate YAML). Scripts **cannot reason** about system architecture, **cannot say "No"** when migration is dangerous, and **cannot self-correct** when syntax or schemas fail.

| Capability | Dumb Script / Rule-Based Converter | Autonomous Migration Agent CLI |
|---|---|---|
| **Architectural Assessment** | None. Blindly attempts conversion on any codebase. | Inspects threads, state, database patterns, and execution durations to evaluate serverless suitability. |
| **Objectivity ("Saying No")** | Fails silently or generates broken serverless code. | Independently issues a `DO_NOT_MIGRATE` or `PARTIAL` verdict with technical justifications. |
| **Execution Path** | Rigid, static step sequence. | **ReAct Pattern:** Autonomously chooses which files to read, when to write, and which validation tools to run. |
| **Closed-Loop Self-Healing** | Crashes on syntax/compiler errors. | Captures compiler/validator tracebacks, diagnoses the root cause, and autonomously rewrites faulty files until valid. |
| **Infrastructure Synthesis** | Hardcoded generic templates. | Custom SAM templates tailored to the discovered runtime, dependencies, timeout requirements, and API routes. |
| **Human Operator Guidance** | None. | Generates **`USER.md`** with exact step-by-step clicks for the AWS Management Console. |
| **PR & Git Workflow** | Requires manual branching and pushing. | Automates isolated feature branching, commit authoring, and remote pushing with ready-to-merge PR links. |

---

## The Autonomous Decision Engine

During repository discovery, the agent assesses the codebase against the AWS Serverless Execution Model using the following decision matrix:

```
                      ┌──────────────────────────────────────┐
                      │ Repository Architectural Discovery   │
                      │ (Files, Routes, Configs, Daemons)    │
                      └──────────────────┬───────────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
      [Stateful / Daemon Blocker?]                   [Stateless / Decoupled?]
      • Continuous background threads                • Request-response lifecycle
      • Local SQLite or disk file state              • External DB or stateless store
      • Long running jobs (>15 min)                  • Execution lifetime < 15 min
      • Persistent WebSocket connections             • HTTP REST / JSON endpoints
                 │                                               │
                 ▼                                               ▼
         VERDICT: DO_NOT_MIGRATE                         VERDICT: MIGRATE
     (Generates Blocker Report &                       (Writes Lambda entrypoint,
      Fargate Modernization Plan)                       SAM template, USER.md, & PR)
```

---

## Architecture & ReAct Workflow

The agent uses the **ReAct (Reason + Act)** paradigm over an isolated Git workspace:

```
[Target External Repo (Clean Git State)]
                    │
                    ▼
   [Create Migration Branch] ──► lambda-migration-YYYYMMDD-HHMMSS
                    │
   ┌────────────────┴───────────────────────────────────────────┐
   │                  AUTONOMOUS REASONING LOOP                 │
   │                                                            │
   │  1. OBSERVE    ◄── list_files, read_file                   │
   │  2. REASON     ◄── Formulate architectural hypothesis       │
   │  3. ACT        ◄── write_file (lambda_function, SAM)        │
   │  4. VALIDATE   ◄── run_command (py_compile, SAM)            │
   │  5. SELF-HEAL  ◄── Fix compilation errors if found          │
   │  6. SYNTHESIZE ◄── MIGRATION_REPORT.md & USER.md            │
   └────────────────────────────┬───────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
    [Commit to Feature Branch]     [Remote Push & PR Link]
     feat(aws-lambda): automated    git push -u origin <branch>
                │                               │
                └───────────────┬───────────────┘
                                ▼
        [Safely Restore User's Original Working Branch]
```

---

## Safety & Zero Blast Radius Guarantee

- **100% Untouched Base Branch**: The agent never commits to or alters `main`, `master`, or your active development branch.
- **Isolated Feature Branch**: All modifications occur on `lambda-migration-<timestamp>`.
- **Remote Push for PR Flow**: When push is enabled, the agent pushes **only** the migration branch to your remote repository (`origin`), allowing your team to review the diff via a standard Pull Request.
- **Sandboxed Execution Whitelist**: The agent cannot execute arbitrary shell commands. It is restricted to read-only linters and compilers (`py_compile`, `pytest`, `sam validate`, `node --check`).
- **No Cloud Mutation**: The agent has no AWS API credentials and cannot deploy, provision, or mutate live cloud resources directly.

---

## Installation & CLI Setup

### Prerequisites
- **Python**: 3.10 or higher
- **Git**: Installed and accessible in your system `PATH`
- **Groq API Key**: Fast inference engine key ([Obtain from Groq Console](https://console.groq.com))
- **AWS SAM CLI** *(Optional, recommended)*: Enables automated template validation (`sam validate`)

### 1. One-Time Setup

```bash
# Clone the repository
git clone https://github.com/dhawalshankar/lambda-agent.git
cd lambda-agent

# Install dependencies and register CLI globally
pip install -r requirements.txt
pip install -e .
```

*Note for Windows users:* The repository also includes `aws_migrator.cmd` and `aws-migrator.cmd` wrappers, so adding this directory to your system `PATH` allows you to type `aws_migrator` or `aws-migrator` from any terminal or PowerShell window.

*Note for Linux/macOS users:* The bash wrappers `aws-migrator` and `aws_migrator` have the executable bit pre-configured (`chmod +x`).

### 2. Configure Your Groq API Key

```bash
# Linux / macOS:
export GROQ_API_KEY="gsk_your_api_key_here"

# Windows (PowerShell):
$env:GROQ_API_KEY="gsk_your_api_key_here"
```

---

## CLI Reference & Usage

Once installed, use the `aws-migrator` or `aws_migrator` command anywhere:

```bash
aws-migrator <path_to_repo> [options]
# Or using python directly:
python agent.py <path_to_repo> [options]
```

### Options

| Flag | Description | Default |
|---|---|---|
| `repo` | Path to the target Git repository (relative or absolute) | *Required* |
| `--push` | Push the migration feature branch to the remote git repository | `True` (if remote exists) |
| `--no-push` | Do NOT push the migration branch; keep all changes strictly local | `False` |
| `--remote <name>` | Git remote name to push to | `origin` |
| `--model <id>` | Groq model identifier | `openai/gpt-oss-120b` |
| `--max-turns <n>` | Maximum autonomous decision loops | `30` |

---

## Generated Migration Artifacts

When a service is migrated, the agent generates:

### 1. `USER.md` (The Actionable AWS Dashboard Guide)
This file is generated specifically for the human developer. It translates code changes into clear, click-by-click instructions for the **AWS Management Console**:
- Step 1: Automated deployment via `sam build && sam deploy --guided` or manual `.zip` packaging.
- Step 2: Function runtime and handler configuration (`lambda_function.lambda_handler`).
- Step 3: Environment variable injection under *Configuration -> Environment variables*.
- Step 4: IAM Execution Role attachment (`AWSLambdaBasicExecutionRole` & VPC access).
- Step 5: API Gateway HTTP API ingress trigger creation.
- Step 6: Console Test event payload verification.
- Step 7: CloudWatch log inspection.

### 2. `lambda_function.py`
The production AWS Lambda entrypoint bridging API Gateway events to your web framework:
```python
import logging
from apig_wsgi import make_lambda_handler
from app import app

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# High-performance WSGI adapter
lambda_handler = make_lambda_handler(app)
```

### 3. `template.yaml` (AWS Serverless Application Model)
Infrastructure as Code defining the Lambda function, IAM roles, memory, timeout, and API Gateway integration.

### 4. `MIGRATION_REPORT.md`
A technical architecture report detailing:
- **Verdict & Technical Justification**: Assessment of serverless suitability.
- **Production Checklist**: IAM policies, VPC subnets, AWS Secrets Manager injection.
- **Cost Comparison**: Financial comparison between 24/7 EC2 compute (`t3.micro`/`t3.small`) vs AWS Lambda pay-per-request pricing ($0.20 per 1M invocations).

---

## End-to-End Live Demonstration Walkthrough

To demonstrate the agent live to an interviewer or panel:

### Step 1: Inspect the Source Project (`ec2_app`)
Open `ec2_app/app.py` and show that it is a standard legacy Flask API listening on a network port:
```bash
cd ec2_app
git status    # Clean working tree
cat app.py    # Shows app.run(host="0.0.0.0", port=port)
cd ..
```

### Step 2: Run the Autonomous Migration CLI
```bash
aws-migrator ec2_app --push
```

### Step 3: Observe Real-Time Agent Execution
1. **ReAct Reasoning Loop**: The agent observes directory topology, reads `app.py` and `requirements.txt`, and formulates its migration plan.
2. **Autonomous Verdict**: Evaluates that `ec2_app` is stateless and assigns Verdict: `MIGRATE`.
3. **Artifact Generation**: Writes `lambda_function.py`, `template.yaml`, `MIGRATION_REPORT.md`, and `USER.md`.
4. **Closed-Loop Validation**: Runs `python -m py_compile` to self-validate syntax.
5. **Git Push & Zero Blast Radius**: Commits the changes to `lambda-migration-<timestamp>`, pushes to `origin`, outputs the Pull Request URL, and checks out `main` cleanly.

### Step 4: Review the Migrated Code and Operator Guide
```bash
cd ec2_app
git checkout lambda-migration-<timestamp>
ls -la
# View the generated handler and the operator guide
cat USER.md
```

---

## Security Sandbox Specifications

To ensure enterprise-grade safety, the tool execution layer implements:

1. **Path Resolution Jails**: All file access paths are resolved against the repository root. Any traversal outside the repository or into `.git/` raises a `PermissionError`.
2. **Deterministic Command Whitelisting**: Execution is restricted strictly to:
   - `python -m py_compile`
   - `python3 -m py_compile`
   - `pytest` / `python -m pytest`
   - `sam validate`
   - `node --check`
3. **Keyword Blacklist**: Commands containing `sudo`, `deploy`, `aws`, `rm`, `curl`, `wget`, `git` inside the tool sandbox are strictly blocked.
4. **Isolated Git Execution**: Git mutations (branching, committing, pushing) are handled strictly by the Python orchestration layer with predefined safe arguments, completely isolated from model control.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
