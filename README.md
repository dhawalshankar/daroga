# Autonomous EC2 to AWS Lambda Migration Agent CLI

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![AWS Lambda](https://img.shields.io/badge/AWS-Lambda%20Ready-FF9900.svg)](https://aws.amazon.com/lambda/)
[![AWS SAM](https://img.shields.io/badge/AWS-SAM%20Validated-red.svg)](https://aws.amazon.com/serverless/sam/)
[![Groq Fast Inference](https://img.shields.io/badge/LLM-Groq%20Tool%20Calling-orange.svg)](https://groq.com/)
[![Zero Blast Radius](https://img.shields.io/badge/Safety-Zero%20Blast%20Radius-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An enterprise-grade **autonomous AI agent CLI** that converts legacy EC2-hosted web services into production-ready AWS Lambda architectures. It analyzes existing application codebases at **any file path**, evaluates serverless feasibility, generates Lambda handlers and AWS SAM templates, self-validates through compiler/schema feedback loops, and publishes safe migration pull-requests on an isolated git branch.

In addition to technical migration artifacts, the agent autonomously generates **`USER.md`** inside the migrated repository — a step-by-step AWS Management Console guide detailing exactly what configurations, IAM roles, and environment variables to set on your AWS Dashboard to bring the service live.

---

## Table of Contents

- [Zero File Copying: Work on Any External Repository](#zero-file-copying-work-on-any-external-repository)
- [Why an Autonomous Agent vs a Transpiler/Script?](#why-an-autonomous-agent-vs-a-transpiler-script)
- [The Autonomous Decision Engine](#the-autonomous-decision-engine)
- [Architecture & ReAct Workflow](#architecture--react-workflow)
- [Safety & Zero Blast Radius Guarantee](#safety--zero-blast-radius-guarantee)
- [Installation & CLI Setup](#installation--cli-setup)
- [CLI Reference & Usage](#cli-reference--usage)
- [Generated Migration Artifacts (Including USER.md)](#generated-migration-artifacts)
- [Real-World Verification Scenarios](#real-world-verification-scenarios)
- [Security Sandbox Specifications](#security-sandbox-specifications)

---

## Zero File Copying: Work on Any External Repository

You **never need to copy or move your project files** into this agent's folder. The CLI operates directly on any local repository path on your machine:

```bash
# Point directly to your EC2 project located anywhere:
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

### Step-by-Step Practical Examples

#### Example 1: Migrate an EC2 Project at Another Path
```bash
aws-migrator "C:\Users\dhawal\Desktop\projects\inventory-api" --push
```

#### Example 2: Run Without Pushing to Remote (Local Only)
```bash
aws-migrator "/home/ubuntu/apps/user-service" --no-push
```

#### Example 3: Use a Custom LLM Model
```bash
aws-migrator "/path/to/project" --model llama-3.3-70b-versatile
```

---

## Generated Migration Artifacts

When a service is migrated, the agent generates:

### 1. `USER.md` (The Actionable AWS Dashboard Guide)
This file is generated specifically for the human developer. It translates code changes into clear, click-by-click instructions for the **AWS Management Console**:

```markdown
# AWS Console Deployment & Configuration Guide

### Step 1: Deploy the Code
Option A (Fastest via CLI):
$ sam build
$ sam deploy --guided

Option B (AWS Lambda Console Manual Upload):
1. Package dependencies: pip install -r requirements.txt -t .
2. Zip app files and upload via AWS Lambda Console -> Code -> Upload from -> .zip file.

### Step 2: Configure Lambda Settings
- Runtime: Python 3.11
- Handler: lambda_function.lambda_handler
- Memory: 512 MB
- Timeout: 30 seconds

### Step 3: Inject Environment Variables
Go to Configuration -> Environment variables -> Edit:
- DATABASE_URL = <your_rds_connection_string>
- SECRET_KEY = <your_secret_key>

### Step 4: IAM Execution Role & Permissions
Go to Configuration -> Permissions:
- Ensure 'AWSLambdaBasicExecutionRole' is attached for CloudWatch Logs.
- Attach 'AWSLambdaVPCAccessExecutionRole' if connecting to RDS inside a private VPC.

### Step 5: API Gateway HTTP Trigger
Go to Function Overview -> Add trigger -> API Gateway:
- Trigger type: Create an API -> HTTP API
- Security: Open (or JWT Authorizer)
- Note the generated HTTP API endpoint URL!

### Step 6: Test from Console
Under the 'Test' tab, paste the sample API Gateway v2 test payload and verify HTTP 200 OK.
```

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
Infrastructure as Code defining the Lambda function, IAM roles, memory, timeout, and API Gateway integration:
```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Automated AWS Lambda Serverless Migration

Globals:
  Function:
    Timeout: 30
    MemorySize: 512
    Runtime: python3.11

Resources:
  ApiFunction:
    Type: AWS::Serverless::Function
    Properties:
      Handler: lambda_function.lambda_handler
      CodeUri: .
      Events:
        ApiRoot:
          Type: HttpApi
          Properties:
            Path: /{proxy+}
            Method: ANY
```

### 4. `MIGRATION_REPORT.md`
A technical architecture report detailing:
- **Verdict & Technical Justification**: Assessment of serverless suitability.
- **Production Checklist**: IAM policies, VPC subnets, AWS Secrets Manager injection.
- **Cost Comparison**: Financial comparison between 24/7 EC2 compute (`t3.micro`/`t3.small`) vs AWS Lambda pay-per-request pricing ($0.20 per 1M invocations).

---

## Real-World Verification Scenarios

### Scenario A: Stateless Flask Service (`sample_app`)

```bash
aws-migrator sample_app --push
```

**Agent Behavior:**
1. Discovers `app.py` and detects Flask route definitions (`/health`, `/tasks`).
2. Confirms request-response statelessness (no background loops or disk locks).
3. Issues Verdict: `MIGRATE`.
4. Generates `lambda_function.py` utilizing `apig-wsgi` for zero-overhead WSGI dispatch.
5. Generates `template.yaml` (AWS SAM) with API Gateway HttpApi events.
6. Generates `USER.md` with complete AWS Console setup steps.
7. Validates code syntax via `python -m py_compile lambda_function.py`.
8. Commits changes and pushes to `origin/lambda-migration-<timestamp>`.

---

### Scenario B: Stateful Daemon Service (`sample_bad_app`)

```bash
aws-migrator sample_bad_app --no-push
```

**Agent Behavior:**
1. Discovers `threading.Thread` with an infinite daemon worker.
2. Identifies local disk SQLite file writes (`local_state.db`).
3. Autonomous Decision: **Rejects blind conversion** and issues Verdict: `DO_NOT_MIGRATE`.
4. Generates `MIGRATION_REPORT.md` and `USER.md` explaining:
   - Why continuous daemon threads freeze on AWS Lambda.
   - Step-by-step AWS Console instructions to deploy on **AWS ECS Fargate** instead.
5. Does not generate broken Lambda handlers.

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
