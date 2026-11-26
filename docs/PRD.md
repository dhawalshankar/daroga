# Product Requirements Document: Autonomous Cloud Migration Agent CLI

| Attribute | Specification |
|---|---|
| **Author** | Cloud Automation & DevOps Team |
| **Status** | Production v1.0 |
| **Platform** | Python 3.10+, Groq API (Tool Calling Inference), Git |
| **Target Runtime** | AWS Lambda, Amazon API Gateway v2, AWS SAM |

---

## 1. Executive Summary

Enterprise cloud administrators and DevOps engineers spend extensive engineering hours manually assessing, refactoring, and migrating legacy EC2-hosted web services into modern serverless architectures. This project delivers an **Autonomous Migration Agent CLI** (`aws-migrator`) that inspects any target repository at any local file path, renders an objective feasibility verdict, generates production-ready AWS Lambda entrypoints and SAM infrastructure, self-validates syntax/schema through closed feedback loops, and publishes safe migration pull requests on an isolated git branch.

---

## 2. Problem Statement

Migrating an application from EC2 to AWS Lambda requires a cloud engineer to:
1. Assess architectural suitability: verify statelessness, inspect for blocking background threads/daemons, audit persistent disk writes, and evaluate execution duration against the 15-minute Lambda limit.
2. Adapt runtime entrypoints: wrap WSGI/ASGI handlers (e.g. `apig-wsgi`, `mangum`) to ingest API Gateway proxy events.
3. Author Infrastructure-as-Code: create AWS SAM or CloudFormation templates with appropriate timeouts, memory sizing, and HTTP API routes.
4. Document production deployment steps for cloud operators.

Manual execution is slow and error-prone. Traditional static scripts or AST transpilers fail because they lack architectural awareness: they cannot "say no" when encountering stateful blockers (such as daemon loops or local SQLite locks) and crash without self-healing when compiler errors occur.

---

## 3. Goals and Non-Goals

### Goals
- **G1. High-Fidelity Autonomous Assessment**: Objectively classify codebases into `migrate`, `partial`, or `do_not_migrate` with technical justifications.
- **G2. Closed-Loop Self-Healing**: Compile and validate generated code (`py_compile`, `sam validate`); autonomously parse tracebacks and correct syntax errors prior to finalizing.
- **G3. Zero Blast Radius**: Work exclusively on isolated feature branches (`lambda-migration-<timestamp>`). The base branch (`main` / `master`) is never altered.
- **G4. Remote Feature Branch Push**: Push the isolated migration branch to the git remote (`origin`) and generate direct 1-click Pull Request URLs.
- **G5. Human Operator Manual**: Autonomously author `USER.md` detailing step-by-step AWS Management Console clicks (IAM, env vars, API Gateway, test payloads).
- **G6. Cross-Platform Standalone CLI**: Native execution across Windows, Linux, and macOS without requiring projects to be copied into the agent directory.

### Non-Goals
- Deploying directly to live AWS infrastructure (ensures safety; human review via Pull Request is required).
- Rewriting core application business logic.
- Supporting non-standard custom binary runtimes outside major supported ecosystems (v1 focuses on Python web frameworks).

---

## 4. Architecture & System Flow

```
User CLI: aws-migrator /path/to/ec2_app --push
                     │
                     ▼
      [Verify Git Working Tree Clean]
                     │
                     ▼
  [Spawn Feature Branch: lambda-migration-<timestamp>]
                     │
   ┌─────────────────┴─────────────────────────────────────────┐
   │             AUTONOMOUS REASONING LOOP (ReAct)             │
   │                                                           │
   │  1. DISCOVERY ◄── list_files, read_file                   │
   │  2. VERDICT   ◄── migrate | partial | do_not_migrate      │
   │  3. GENERATE  ◄── lambda_function.py, template.yaml       │
   │  4. VALIDATE  ◄── py_compile, sam validate                │
   │  5. SELF-HEAL ◄── Autonomously fix syntax errors if any   │
   │  6. DOCUMENTS ◄── MIGRATION_REPORT.md, USER.md            │
   └─────────────────┬─────────────────────────────────────────┘
                     │
     ┌───────────────┴───────────────┐
     ▼                               ▼
[Commit Feature Branch]    [Push Remote: origin/<branch>]
     │                               │
     └───────────────┬───────────────┘
                     ▼
[Restore User Workspace to Original Branch (main)]
                     │
                     ▼
[Display PR URL & Prompt User to Review USER.md]
```

---

## 5. Functional Requirements

| ID | Requirement | Priority | Status |
|---|---|---|---|
| F1 | Accept any repository path and verify clean git status | P0 | Implemented |
| F2 | Autonomous architectural inspection (routes, threads, storage, timeouts) | P0 | Implemented |
| F3 | Objective verdict determination (`migrate` / `partial` / `do_not_migrate`) | P0 | Implemented |
| F4 | Isolated feature branch creation (`lambda-migration-<timestamp>`) | P0 | Implemented |
| F5 | Production artifact generation (`lambda_function.py`, `template.yaml`, `requirements.txt`) | P0 | Implemented |
| F6 | Deterministic self-validation via `py_compile` and `sam validate` with error recovery | P0 | Implemented |
| F7 | Technical migration reporting (`MIGRATION_REPORT.md`) with cost breakdown | P0 | Implemented |
| F8 | Operator guide generation (`USER.md`) for AWS Management Console setup | P0 | Implemented |
| F9 | Remote git branch push (`git push -u origin <branch>`) with Pull Request URL generation | P0 | Implemented |
| F10 | Clean workspace restoration (base branch remains 100% untouched) | P0 | Implemented |
| F11 | Cross-platform compatibility (Windows, Linux, macOS) | P0 | Implemented |

---

## 6. Security & Blast Radius Controls

1. **Main Branch Inviolability**: The agent is restricted from making direct commits or merges to base branches.
2. **Command Whitelist Sandbox**: Subprocess execution is strictly limited to safe validation tools (`py_compile`, `pytest`, `sam validate`, `node --check`).
3. **Keyword Blacklist**: Commands containing `sudo`, `deploy`, `aws`, `rm`, `curl`, `wget`, `git` inside tool calls are blocked.
4. **Path Traversal Jail**: File read and write operations are strictly bounded to the target repository directory; traversal into `.git/` or outside the root is prohibited.
5. **No Cloud Mutation**: The agent does not hold AWS credentials and cannot incur cloud spend or alter running infrastructure.

---

## 7. Verification Projects

The repository provides two reference projects:
1. **`ec2_app/`**: A standard legacy EC2 REST service running Flask with an HTTP host listener (`app.run()`). Used to demonstrate the agent performing an end-to-end migration.
2. **`lambda_app/`**: The reference target architecture demonstrating the expected output artifacts (`lambda_function.py`, `template.yaml`, `MIGRATION_REPORT.md`, `USER.md`).
