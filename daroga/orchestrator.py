"""
DAROGA Pipeline Orchestrator Module
===================================
Coordinates the complete, deterministic 11-stage audit pipeline:
Repository Scanning -> AWS EC2 Inspection -> Playwright CDP Browser Check ->
Compatibility Evaluation -> Architecture Mapping -> Cost Analysis -> Report Generation.
"""

import logging
from pathlib import Path
from typing import Optional

from daroga.repository_scanner import RepositoryScanner
from daroga.ec2_inspector import EC2Inspector
from daroga.browser_inspector import BrowserInspector
from daroga.lambda_compatibility import LambdaCompatibilityEngine
from daroga.architecture_mapper import ArchitectureMapper
from daroga.cost_estimator import CostEstimator
from daroga.report_generator import ReportGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from daroga.repository_scanner import RepositoryScanner, RepoInspectionResult
from daroga.ec2_inspector import EC2Inspector, AWSInfrastructureReport
from daroga.browser_inspector import BrowserInspector, BrowserConsoleFinding
from daroga.lambda_compatibility import LambdaCompatibilityEngine, CompatibilityEvaluationReport
from daroga.architecture_mapper import ArchitectureMapper, TargetServerlessArchitecture
from daroga.cost_estimator import CostEstimator, CostBreakdown
from daroga.report_generator import ReportGenerator
from daroga.token_tracker import TokenTracker

logger = logging.getLogger("daroga.orchestrator")


@dataclass
class DarogaAuditResult:
    report_path: Path
    verdict: str
    score: float
    blockers: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    target_runtime: str = "provided.al2023"
    summary: str = ""
    repo: Optional[RepoInspectionResult] = None
    aws: Optional[AWSInfrastructureReport] = None
    compat: Optional[CompatibilityEvaluationReport] = None
    arch: Optional[TargetServerlessArchitecture] = None
    cost: Optional[CostBreakdown] = None


class DarogaOrchestrator:
    """
    Autonomous EC2 to Lambda Migration Auditor Orchestrator.
    Executes in read-only mode: does not touch or modify source code or AWS infrastructure.
    """

    def __init__(
        self,
        repo_path: Path,
        region: Optional[str] = None,
        instance_id: Optional[str] = None,
        cdp_url: str = "http://127.0.0.1:9222",
        output_report_path: Optional[Path] = None,
    ):
        self.repo_path = repo_path.resolve()
        self.region = region
        self.instance_id = instance_id
        self.cdp_url = cdp_url
        self.output_report_path = (output_report_path or (self.repo_path / "EC2_TO_LAMBDA_MIGRATION_REPORT.md")).resolve()
        self.tracker = TokenTracker()

    def run_audit(self) -> DarogaAuditResult:
        print("\n" + "=" * 70)
        print("DAROGA — EC2 TO AWS LAMBDA MIGRATION AUDITOR")
        print("Autonomous Cloud Infrastructure Inspection & Planning Agent")
        print("=" * 70)

        # 1. Repository Scanner (Target Service AST Inspection)
        print("[SCANNER] Deterministically inspecting target application repository...")
        scanner = RepositoryScanner(self.repo_path)
        repo_res = scanner.scan()
        self.tracker.record_scan(repo_res.total_files_scanned)
        print(f"✓ Indexed {repo_res.total_files_scanned} files across repository.")
        print(f"  • Target Service Runtime: {repo_res.primary_language.upper()} (Scope: {repo_res.target_service_directory or '.'})")
        if repo_res.repo_wide_languages:
            print(f"  • Repo-Wide Languages:    {', '.join(repo_res.repo_wide_languages)}")
        print(f"  • Frameworks:             {', '.join(repo_res.frameworks) or 'Standard net/http'}")
        if repo_res.repo_wide_frameworks and repo_res.repo_wide_frameworks != repo_res.frameworks:
            print(f"  • Repo-Wide Frameworks:   {', '.join(repo_res.repo_wide_frameworks)}")
        print(f"  • Entry Points:           {', '.join(repo_res.entrypoints) or 'Auto-detected'}")
        print(f"  • Exposed Ports:          {', '.join(str(p) for p in repo_res.exposed_ports) or 'Dynamic'}")

        # 2. Browser CDP Inspection (checked early to discover active AWS console region if open)
        print("\n[BROWSER-CDP] Checking for active browser session via Chrome DevTools Protocol...")
        browser_inspector = BrowserInspector(cdp_url=self.cdp_url)
        browser_res = browser_inspector.inspect()
        active_region = self.region
        if browser_res.cdp_available:
            print(f"✓ CDP connection active on {self.cdp_url}.")
            if browser_res.aws_console_tabs:
                print(f"✓ Detected {len(browser_res.aws_console_tabs)} open AWS Management Console tab(s):")
                for tab in browser_res.aws_console_tabs[:3]:
                    print(f"  ↳ {tab['title']} ({tab['url'][:65]}...)")
                if not active_region and browser_res.detected_region:
                    active_region = browser_res.detected_region
                    print(f"ℹ Auto-detected active AWS Console region from browser: `{active_region}`")
        else:
            print(f"ℹ {browser_res.notes[0]}")

        # 3. AWS EC2 Infrastructure Inspector
        print("\n[AWS-EC2] Inspecting live AWS cloud infrastructure (read-only)...")
        aws_inspector = EC2Inspector(region_name=active_region, instance_id=self.instance_id)
        aws_res = aws_inspector.inspect_all()
        res_count = len(aws_res.instances) + len(aws_res.security_groups) + len(aws_res.vpcs)
        self.tracker.record_aws(res_count)
        if aws_res.identity.configured:
            print(f"✓ AWS Identity verified: Account `{aws_res.identity.account_id}` in `{aws_res.identity.region}`")
            if aws_res.instances:
                inst = aws_res.instances[0]
                inst_name = inst.tags.get("Name") or inst.instance_id
                print(f"✓ Found target EC2 Instance: `{inst.instance_id}` ({inst_name}, {inst.instance_type}, {inst.state}) in `{aws_res.identity.region}`")
            else:
                print(f"ℹ No running EC2 instances found matching filter in region `{aws_res.identity.region}`. Using infrastructure heuristics.")
        else:
            print(f"ℹ AWS CLI/Credentials note: {aws_res.identity.error or 'Unconfigured'}. Using deterministic defaults.")

        # 4. Lambda Compatibility Engine
        print("\n[COMPATIBILITY] Evaluating application architecture against AWS Lambda execution limits...")
        compat_engine = LambdaCompatibilityEngine()
        compat_res = compat_engine.evaluate(repo_res, aws_res)
        self.tracker.record_deterministic_finding(len(compat_res.findings))
        print(f"✓ Verdict Concluded: [{compat_res.overall_verdict}] (Score: {compat_res.overall_score:.0f}%)")
        for f in compat_res.findings:
            print(f"  ↳ [{f.severity.value}] {f.title}: {f.status.value}")

        # 5. Architecture Mapper
        print("\n[ARCHITECTURE] Synthesizing target AWS Serverless topology...")
        mapper = ArchitectureMapper()
        arch_res = mapper.map_architecture(repo_res, aws_res, compat_res)
        print(f"✓ Primary Compute: {arch_res.primary_compute}")
        print(f"✓ Ingress Router:  {arch_res.api_gateway_type}")
        print(f"✓ Execution Role:  {arch_res.iam_role_name}")

        # 6. Cost Estimator
        print("\n[COST] Estimating comparative infrastructure expenditure & free-tier coverage...")
        estimator = CostEstimator()
        cost_res = estimator.estimate(
            aws_res,
            memory_mb=compat_res.recommended_memory_mb,
            avg_duration_ms=150,
            has_docker_decoupling=repo_res.has_docker_execution
        )
        if cost_res.has_live_instance:
            print(f"✓ Live EC2 Instance:      ${cost_res.ec2_monthly_estimated:.2f}/month ({cost_res.ec2_label})")
            print(f"✓ Lambda Free Tier Level: ${cost_res.lambda_low_traffic_monthly:.2f}/month")
            print(f"✓ Projected Savings:      {cost_res.savings_label}")
        else:
            print(f"✓ Legacy EC2 Compute:     {cost_res.ec2_label} [{cost_res.ec2_range}]")
            print(f"✓ Lambda Free Tier Level: ${cost_res.lambda_low_traffic_monthly:.2f}/month")
            print(f"✓ Projected Savings:      {cost_res.savings_label}")

        # 7. Final Report Generation (One authoritative report)
        print(f"\n[REPORT] Generating authoritative 23-section migration report: '{self.output_report_path.name}'...")
        generator = ReportGenerator()
        report_md = generator.generate(
            repo=repo_res,
            aws=aws_res,
            browser=browser_res,
            compat=compat_res,
            arch=arch_res,
            cost=cost_res,
            tracker=self.tracker,
        )

        self.output_report_path.write_text(report_md, encoding="utf-8")
        print(f"✓ Successfully generated: {self.output_report_path}")

        print("\n" + "=" * 70)
        print("AUDIT COMPLETE — READY FOR MANUAL REVIEW")
        print("=" * 70)
        print(f"• Target Report: {self.output_report_path}")
        print("• Safety Guarantee: Source code and cloud infrastructure were 100% UNTOUCHED.")
        print("• Action Item: Open EC2_TO_LAMBDA_MIGRATION_REPORT.md for exact AWS Console clicks & CLI commands.\n")

        return DarogaAuditResult(
            report_path=self.output_report_path,
            verdict=compat_res.overall_verdict,
            score=compat_res.overall_score,
            blockers=list(compat_res.blockers),
            conditions=list(compat_res.conditions),
            target_runtime=compat_res.recommended_runtime,
            summary=(
                f"Evaluated {repo_res.primary_language.upper()} service in '{repo_res.target_service_directory or '.'}'. "
                f"Verdict: {compat_res.overall_verdict} (Score: {compat_res.overall_score:.0f}%). "
                f"{'; '.join(compat_res.conditions) if compat_res.conditions else 'Ready for serverless deployment.'}"
            ),
            repo=repo_res,
            aws=aws_res,
            compat=compat_res,
            arch=arch_res,
            cost=cost_res,
        )
