"""
DAROGA Lambda Compatibility & Rule-Based Architecture Engine
============================================================
Evaluates repository and infrastructure findings against AWS Lambda's execution model
using explicit deterministic rules. Classifies compatibility and prescribes required changes.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from daroga.repository_scanner import RepoInspectionResult
from daroga.ec2_inspector import AWSInfrastructureReport


class CompatibilityStatus(str, Enum):
    COMPATIBLE_WITHOUT_CHANGES = "Compatible without changes"
    COMPATIBLE_WITH_CODE_MODS = "Compatible with code modifications"
    COMPATIBLE_WITH_ARCH_MODS = "Compatible with architectural modifications"
    NOT_DIRECTLY_COMPATIBLE = "Not directly compatible"
    REQUIRES_FURTHER_INVESTIGATION = "Requires further investigation"


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class CompatibilityRuleFinding:
    rule_id: str
    category: str
    title: str
    status: CompatibilityStatus
    severity: Severity
    evidence: str
    recommended_action: str
    confidence_score: float  # 0.0 to 1.0
    requires_human_review: bool


@dataclass
class CompatibilityEvaluationReport:
    overall_verdict: str
    overall_score: float  # 0 to 100%
    findings: List[CompatibilityRuleFinding] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    required_code_changes: List[str] = field(default_factory=list)
    recommended_runtime: str = "provided.al2023"
    recommended_memory_mb: int = 512
    recommended_timeout_sec: int = 30

    def to_verdict_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.overall_verdict,
            "score": self.overall_score,
            "blockers": list(self.blockers),
            "conditions": list(self.conditions),
            "recommended_runtime": self.recommended_runtime,
        }


class LambdaCompatibilityEngine:
    """
    Deterministic rule-based evaluator for AWS Lambda migration suitability.
    """

    def evaluate(self, repo: RepoInspectionResult, aws: AWSInfrastructureReport) -> CompatibilityEvaluationReport:
        report = CompatibilityEvaluationReport(overall_verdict="MIGRATE", overall_score=85.0)

        # 1. Runtime Evaluation Rule (strictly based on target service language)
        lang = repo.primary_language.lower()
        if lang == "go":
            report.recommended_runtime = "provided.al2023"
            report.findings.append(CompatibilityRuleFinding(
                rule_id="RULE-RNT-01",
                category="Runtime Compatibility",
                title="Golang Custom Runtime on Amazon Linux 2023 (provided.al2023)",
                status=CompatibilityStatus.COMPATIBLE_WITH_CODE_MODS,
                severity=Severity.LOW,
                evidence=f"Target backend service written in Go (Runtime: provided.al2023, Binary: bootstrap arm64)",
                recommended_action="Compile binary for Linux ARM64 (bootstrap) and package using custom runtime 'provided.al2023'.",
                confidence_score=0.98,
                requires_human_review=False,
            ))
            report.required_code_changes.append("Wrap HTTP router in `backend/lambda_main.go` using `aws-lambda-go-api-proxy` or standard Lambda handler.")

        elif lang == "python":
            report.recommended_runtime = "python3.12"
            report.findings.append(CompatibilityRuleFinding(
                rule_id="RULE-RNT-02",
                category="Runtime Compatibility",
                title="Python Native Managed Runtime (python3.12)",
                status=CompatibilityStatus.COMPATIBLE_WITH_CODE_MODS,
                severity=Severity.LOW,
                evidence=f"Target service written in Python with dependencies: {repo.package_managers}",
                recommended_action="Deploy on managed runtime 'python3.12' using apig-wsgi or Mangum adapter.",
                confidence_score=0.99,
                requires_human_review=False,
            ))
            report.required_code_changes.append("Introduce `lambda_function.py` with `apig_wsgi.make_lambda_handler` or `Mangum(app)`.")

        elif lang in ("javascript", "typescript"):
            report.recommended_runtime = "nodejs20.x"
            report.findings.append(CompatibilityRuleFinding(
                rule_id="RULE-RNT-03",
                category="Runtime Compatibility",
                title="Node.js Managed Runtime (nodejs20.x)",
                status=CompatibilityStatus.COMPATIBLE_WITH_CODE_MODS,
                severity=Severity.LOW,
                evidence=f"Target service written in JavaScript/TypeScript with {repo.package_managers}",
                recommended_action="Deploy on managed runtime 'nodejs20.x' using @vendia/serverless-express.",
                confidence_score=0.98,
                requires_human_review=False,
            ))
            report.required_code_changes.append("Export serverless handler via `@vendia/serverless-express`.")

        # 2. Continuous Socket Listener Rule
        report.findings.append(CompatibilityRuleFinding(
            rule_id="RULE-NET-01",
            category="Application Execution Model",
            title="Continuous TCP Socket Listener Conversion",
            status=CompatibilityStatus.COMPATIBLE_WITH_CODE_MODS,
            severity=Severity.MEDIUM,
            evidence=f"Exposed ports detected: {repo.exposed_ports or '[dynamic port listener]'}",
            recommended_action="Replace continuous `http.ListenAndServe` with event-driven invocation via Amazon API Gateway HTTP API ($default or /{proxy+}).",
            confidence_score=0.95,
            requires_human_review=False,
        ))

        # 3. Docker Sandbox / Container Runtime Rule (Docker-in-Lambda is Unsupported)
        if repo.has_docker_execution:
            report.findings.append(CompatibilityRuleFinding(
                rule_id="RULE-CNT-01",
                category="Container Runtime",
                title="Docker-in-Lambda is Unsupported (Dynamic Container Execution Detected)",
                status=CompatibilityStatus.NOT_DIRECTLY_COMPATIBLE,
                severity=Severity.HIGH,
                evidence="; ".join(repo.docker_exec_evidence[:3]),
                recommended_action="AWS Lambda runs inside lightweight Firecracker microVMs with a read-only root filesystem and cannot run a Docker daemon or execute nested containers. Recommend AWS Lambda for the public API layer plus an asynchronous AWS ECS Fargate task (or AWS Batch) triggered via Amazon SQS or EventBridge for dynamic container execution.",
                confidence_score=0.98,
                requires_human_review=True,
            ))
            report.blockers.append("Dynamic Docker execution (docker run, docker.sock) is unsupported inside AWS Lambda.")
            report.conditions.append("Decouple dynamic container execution to AWS ECS Fargate task worker")
            report.required_code_changes.append("Decouple `docker run` container execution into an asynchronous ECS Fargate or Lambda container task.")

        # 4. WebSockets Rule (Persistent TCP / WebSocket Listener Requires Redesign)
        if repo.has_websockets:
            report.findings.append(CompatibilityRuleFinding(
                rule_id="RULE-WBS-01",
                category="Networking & Protocols",
                title="Persistent TCP / WebSocket Listener Requires Redesign",
                status=CompatibilityStatus.NOT_DIRECTLY_COMPATIBLE,
                severity=Severity.HIGH,
                evidence="; ".join(repo.websocket_evidence[:2]),
                recommended_action="Persistent bidirectional TCP/WebSocket connections cannot run directly on AWS Lambda without architectural redesign. Replace with Amazon API Gateway WebSocket API with connectionId state persisted in Amazon DynamoDB, or host on a dedicated real-time service.",
                confidence_score=0.95,
                requires_human_review=True,
            ))
            report.blockers.append("Persistent TCP/WebSocket connections require redesign to Amazon API Gateway WebSocket API or dedicated service.")
            report.conditions.append("Migrate WebSocket listeners to API Gateway WebSocket API + DynamoDB")
            report.required_code_changes.append("Refactor WebSocket handlers to consume API Gateway `$connect`, `$disconnect`, and `$default` events.")

        # 5. Local Storage & SQLite Rule
        if repo.has_local_storage:
            report.findings.append(CompatibilityRuleFinding(
                rule_id="RULE-STR-01",
                category="State Persistence",
                title="Embedded Local Storage / SQLite Database",
                status=CompatibilityStatus.COMPATIBLE_WITH_ARCH_MODS,
                severity=Severity.HIGH,
                evidence="; ".join(repo.storage_evidence[:2]),
                recommended_action="AWS Lambda runtime filesystem is ephemeral (/tmp is limited to 512MB-10GB and resets). Migrate persistent state to Amazon DynamoDB or Amazon RDS (Aurora Serverless v2).",
                confidence_score=0.94,
                requires_human_review=True,
            ))
            report.blockers.append("Local disk storage or SQLite resets across Lambda invocations.")
            report.conditions.append("Migrate persistent storage to Amazon S3 or DynamoDB")
            report.required_code_changes.append("Migrate local file storage/SQLite to Amazon S3 or Amazon DynamoDB.")

        # 6. Execution Limit Rules: Timeout, Payload, Storage
        if repo.has_docker_execution:
            report.findings.append(CompatibilityRuleFinding(
                rule_id="RULE-LIM-01",
                category="Execution Limits",
                title="15-Minute Timeout Limit (Long-Running Tasks Detected)",
                status=CompatibilityStatus.NOT_DIRECTLY_COMPATIBLE,
                severity=Severity.HIGH,
                evidence="In-app compiler/sandbox tasks risk exceeding the 15-minute Lambda ceiling.",
                recommended_action="AWS Lambda enforces a hard 15-minute (900s) maximum execution duration. Long-running compilation or batch tasks must be decoupled to ECS Fargate.",
                confidence_score=0.95,
                requires_human_review=True,
            ))
        else:
            report.findings.append(CompatibilityRuleFinding(
                rule_id="RULE-LIM-01",
                category="Execution Limits",
                title="15-Minute Maximum Execution Timeout",
                status=CompatibilityStatus.COMPATIBLE_WITHOUT_CHANGES,
                severity=Severity.INFO,
                evidence="Standard synchronous HTTP request-response pattern identified.",
                recommended_action="AWS Lambda enforces a 15-minute maximum timeout. Ensure API Gateway timeouts (max 30s) are respected.",
                confidence_score=0.95,
                requires_human_review=False,
            ))

        report.findings.append(CompatibilityRuleFinding(
            rule_id="RULE-LIM-02",
            category="Execution Limits",
            title="6 MB Synchronous Payload Limit",
            status=CompatibilityStatus.COMPATIBLE_WITHOUT_CHANGES,
            severity=Severity.INFO,
            evidence="Standard REST/JSON payload APIs detected.",
            recommended_action="AWS Lambda enforces a 6 MB maximum payload limit for synchronous API Gateway requests and responses. For large file uploads or outputs, generate Amazon S3 presigned URLs.",
            confidence_score=0.95,
            requires_human_review=False,
        ))

        report.findings.append(CompatibilityRuleFinding(
            rule_id="RULE-LIM-03",
            category="Execution Limits",
            title="Ephemeral Disk Storage (/tmp 512MB-10GB)",
            status=CompatibilityStatus.COMPATIBLE_WITHOUT_CHANGES,
            severity=Severity.INFO,
            evidence="No heavy persistent disk writes detected outside standard temporary files.",
            recommended_action="Ephemeral storage (/tmp) is available from 512 MB up to 10 GB. Data resets between warm container life cycles.",
            confidence_score=0.95,
            requires_human_review=False,
        ))

        # 7. Scheduled Tasks Rule
        if repo.has_scheduled_jobs:
            report.findings.append(CompatibilityRuleFinding(
                rule_id="RULE-JOB-01",
                category="Scheduled Jobs",
                title="Internal Background Cron / Scheduler Loops",
                status=CompatibilityStatus.COMPATIBLE_WITH_ARCH_MODS,
                severity=Severity.MEDIUM,
                evidence="; ".join(repo.job_evidence[:2]),
                recommended_action="Replace in-process cron tickers with Amazon EventBridge Scheduler rules triggering dedicated Lambda invocations.",
                confidence_score=0.96,
                requires_human_review=False,
            ))
            report.required_code_changes.append("Extract cron routines into standalone Lambda functions triggered by EventBridge Scheduler.")

        # 8. Database Connection Pooling Rule
        if repo.database_types:
            report.findings.append(CompatibilityRuleFinding(
                rule_id="RULE-DB-01",
                category="Database Connectivity",
                title=f"External Database Integration ({', '.join(repo.database_types)})",
                status=CompatibilityStatus.COMPATIBLE_WITH_CODE_MODS,
                severity=Severity.MEDIUM,
                evidence=f"Database driver integration: {', '.join(repo.database_types)}",
                recommended_action="In serverless environments, initialize database connection pools outside the request handler (global scope) to reuse connections across warm invocations. For relational databases (PostgreSQL/MySQL), configure Amazon RDS Proxy to avoid connection exhaustion.",
                confidence_score=0.95,
                requires_human_review=False,
            ))
            report.required_code_changes.append("Initialize database connections in global execution context to benefit from Lambda container reuse.")

        # 9. Blocker-Aware Scoring and Verdict Determination
        high_findings = [f for f in report.findings if f.severity == Severity.HIGH]
        critical_findings = [f for f in report.findings if f.severity == Severity.CRITICAL]

        if critical_findings:
            report.overall_score = min(40.0, 100.0 - (len(critical_findings) * 30))
            report.overall_verdict = "NOT RECOMMENDED"
        elif high_findings:
            # HIGH-severity findings cap the score at 60 and force the verdict to "MIGRATE (WITH DECOUPLING)"
            report.overall_score = min(60.0, max(45.0, 60.0 - ((len(high_findings) - 1) * 5)))
            report.overall_verdict = "MIGRATE (WITH DECOUPLING)"
        elif any(f.severity == Severity.MEDIUM for f in report.findings):
            report.overall_score = 80.0
            report.overall_verdict = "MIGRATE (WITH CODE MODIFICATIONS)"
        else:
            report.overall_score = 95.0
            report.overall_verdict = "MIGRATE (FULLY COMPATIBLE)"

        return report
