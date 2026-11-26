# Product Requirements Document: DAROGA (v2.0)
## Autonomous EC2 to AWS Lambda Migration Auditor & Planning Agent

| Attribute | Specification |
|---|---|
| **Product Name** | **DAROGA** |
| **CLI Commands** | `daroga`, `aws-migrator`, `aws_migrator` |
| **Status** | Production v2.0 |
| **Scope** | **AWS EC2 to AWS Lambda ONLY** |
| **Target Runtime** | AWS Lambda Graviton (`arm64`), Amazon API Gateway HTTP API v2, AWS SAM |
| **Inspection Modalities** | Deterministic AST, Boto3 AWS CLI, Playwright Chrome DevTools Protocol (CDP) |
| **Deliverables** | 23-Section Audit Report, Serverless Adapters, AWS SAM Template, Operator Guide, Git PR |

---

## 1. Executive Summary

Enterprise cloud teams spend substantial engineering hours auditing, refactoring, and migrating legacy web applications running continuously on AWS EC2 instances into event-driven serverless architectures. 

**DAROGA** is an autonomous cloud engineering auditor and migration agent. Given any local repository path, DAROGA independently inspects the codebase, assesses compatibility with AWS Lambda execution limits, audits live AWS cloud infrastructure in read-only mode, inspects open AWS Console tabs via Chrome DevTools Protocol (CDP), synthesizes an authoritative **23-section architecture audit report**, authors production-ready serverless runtime adapters and AWS SAM infrastructure definitions, commits the deliverables onto an isolated Git feature branch, pushes to the remote repository, and outputs a ready-to-merge GitHub Pull Request link.

---

## 2. Strict Scope: EC2 → AWS Lambda ONLY

DAROGA has one singular purpose: **Assess how the user's specific existing EC2-hosted application can be migrated to AWS Lambda.**

### In-Scope
- Moving continuous HTTP/REST services from EC2 VMs to AWS Lambda (ARM64 Graviton) backed by Amazon API Gateway HTTP API v2.
- In full-stack monorepos with `frontend/` and `backend/`, isolating and migrating the `backend/` server.
- Decoupling asynchronous or batch worker jobs to AWS SQS or worker queues while hosting public API routes on AWS Lambda.
- Read-only inspection of live EC2 instances, VPC subnets, Security Groups, and IAM instance profiles.
- Read-only inspection of active AWS Management Console tabs via CDP.
- Generation of the comprehensive 23-section `EC2_TO_LAMBDA_MIGRATION_REPORT.md`.
- Authoring human-operator manuals (`USER.md`) detailing AWS Console clicks and CLI commands.

### Explicitly Out-of-Scope (Non-Goals)
- Deflecting compute workloads to ECS, EKS, or App Runner as the primary recommendation.
- General cloud optimizations or unrelated security audits.
- Mutating live AWS infrastructure directly (zero blast radius; all deployments are human-reviewed).
- Modifying frontend client applications.

---

## 3. Core Architecture & Pipeline

```
[Target External Repository]
            │
            ▼
[Git Cleanliness & Validation]
            │
            ▼
[Spawn Isolated Feature Branch: lambda-migration-<timestamp>]
            │
┌───────────┴───────────────────────────────────────────────────────┐
│                    DAROGA 11-STAGE AUDIT & SYNTHESIS              │
│                                                                   │
│  Stage 1: Repository AST Scan (Go, Python, Node, Dockerfiles)      │
│  Stage 2: Live AWS Cloud Audit (Boto3 STS, EC2, VPC, SecGroups)   │
│  Stage 3: Browser CDP Console Check (Playwright :9222)            │
│  Stage 4: Lambda Compatibility & Execution Limits Engine          │
│  Stage 5: Target Architecture Mapping (Graviton arm64 + API GW)  │
│  Stage 6: Comparative Cost Estimation (EC2 vs. Lambda Free Tier)  │
│  Stage 7: Generate 23-Section EC2_TO_LAMBDA_MIGRATION_REPORT.md   │
│  Stage 8: Synthesize Serverless Adapter (lambda_main.go / py / js)│
│  Stage 9: Generate Linux ARM64 Build Script (build_lambda.sh)     │
│  Stage 10: Author AWS SAM Template (template.yaml)                │
│  Stage 11: Author Operator Guide (USER.md) & Executive Summary    │
└───────────┬───────────────────────────────────────────────────────┘
            │
┌───────────┴───────────────────────────────┐
│         GIT AUTOMATION & ZERO BLAST       │
│                                           │
│  • Stage All 6 Deliverables               │
│  • Commit to lambda-migration-<timestamp> │
│  • Push Feature Branch to Remote (origin) │
│  • Construct Direct GitHub PR URL         │
│  • Restore Local Workspace to main        │
└───────────────────────────────────────────┘
```

---

## 4. Functional Requirements

| ID | Requirement | Priority | Implementation Component |
|---|---|---|---|
| **FR-1** | Accept any local repository path without copying files into the tool directory | P0 | `agent.py` CLI parser |
| **FR-2** | Check git status and enforce a clean working tree before proceeding | P0 | `agent.is_git_clean` |
| **FR-3** | Monorepo detection: Automatically scope migration to `backend/` if monorepo detected | P0 | `daroga.repository_scanner` |
| **FR-4** | Live AWS EC2 & VPC inspection via read-only Boto3 / AWS CLI | P0 | `daroga.ec2_inspector` |
| **FR-5** | Live AWS Console inspection via Chrome DevTools Protocol (`http://127.0.0.1:9222`) | P0 | `daroga.browser_inspector` |
| **FR-6** | Compatibility evaluation against AWS Lambda runtime limits (15 min, 6MB, ephemeral disk) | P0 | `daroga.lambda_compatibility` |
| **FR-7** | Produce authoritative 23-section `EC2_TO_LAMBDA_MIGRATION_REPORT.md` | P0 | `daroga.report_generator` |
| **FR-8** | Generate production serverless runtime adapters (`lambda_main.go`, `lambda_function.py`, `lambda.js`) | P0 | `agent.run_offline_analysis` |
| **FR-9** | Generate cross-compilation build scripts for ARM64 Graviton (`build_lambda.sh`) | P0 | `agent.run_offline_analysis` |
| **FR-10** | Generate production-ready AWS SAM template (`template.yaml`) | P0 | `agent.run_offline_analysis` |
| **FR-11** | Generate step-by-step human operator manual for AWS Console (`USER.md`) | P0 | `agent.run_offline_analysis` |
| **FR-12** | Automatic feature branch creation (`lambda-migration-<timestamp>`) | P0 | `agent.daroga_main` |
| **FR-13** | Automatic remote push (`git push -u origin <branch>`) with Pull Request URL generation | P0 | `agent.daroga_main` |
| **FR-14** | Zero Blast Radius: Local working tree on `main` remains 100% clean and untouched | P0 | `agent.daroga_main` |
| **FR-15** | Autonomous Offline Heuristic Engine (Zero-API, zero-cost mode) | P0 | `agent.run_offline_analysis` |

---

## 5. Security & Safety Controls

1. **Zero Cloud Mutation**: DAROGA never issues mutating AWS API calls. It holds read-only privileges (`sts:GetCallerIdentity`, `ec2:DescribeInstances`, `ec2:DescribeVpcs`, `ec2:DescribeSecurityGroups`).
2. **Main Branch Inviolability**: The agent is programmatically blocked from committing directly to `main` or `master`. All work occurs inside an ephemeral feature branch.
3. **No Sensitive Data Leaks**: CDP browser inspections only read document titles and URLs of AWS Console tabs. Passwords, session cookies, and authentication tokens are never recorded or written to disk.
4. **Sandboxed Command Execution**: Internal validations are limited strictly to safe linters and compilers (`py_compile`, `go build`, `sam validate`).

---

## 6. Deliverable Artifacts Matrix

| Artifact | Location | Purpose |
|---|---|---|
| `EC2_TO_LAMBDA_MIGRATION_REPORT.md` | Repository Root | Comprehensive 23-section architecture audit and feasibility evaluation. |
| `lambda_main.go` / `lambda_function.py` | `backend/` or Root | Production serverless HTTP adapter proxying API Gateway events. |
| `build_lambda.sh` | `backend/` or Root | Cross-compilation script targeting Amazon Linux 2023 Graviton (`arm64`). |
| `template.yaml` | Repository Root | AWS SAM template declaring API Gateway v2, Lambda functions, and IAM policies. |
| `USER.md` | Repository Root | Click-by-click AWS Management Console guide for DevOps engineers. |
| `MIGRATION_REPORT.md` | Repository Root | Executive summary of architectural delta and cost savings. |
