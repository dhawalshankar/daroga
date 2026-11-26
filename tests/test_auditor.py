"""
DAROGA Migration Auditor & Compatibility Engine Test Suite
Validates:
  1. Per-service language detection (Go backend + Next.js frontend -> Go/provided.al2023).
  2. Blocker-aware scoring & verdict (Docker container execution caps score at 60 and enforces MIGRATE (WITH DECOUPLING)).
  3. Cost estimation honesty (No live EC2 instance produces ESTIMATE label, never 100% savings).
  4. Single source of truth for verdict string across structured result, report, and CLI output.
"""

import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from daroga.repository_scanner import RepositoryScanner, RepoInspectionResult
from daroga.lambda_compatibility import LambdaCompatibilityEngine, CompatibilityEvaluationReport
from daroga.cost_estimator import CostEstimator, CostBreakdown
from daroga.orchestrator import DarogaOrchestrator, DarogaAuditResult


@pytest.fixture
def temp_polyglot_repo(tmp_path: Path) -> Path:
    """
    Creates a temporary monorepo with:
      - Go backend with backend/go.mod and backend/main.go (entry point).
      - Next.js frontend with 20+ JavaScript files in frontend/pages/.
    """
    repo = tmp_path / "polyglot_repo"
    repo.mkdir()

    # Backend Go service (with main.go entrypoint and Docker CLI call)
    backend_dir = repo / "backend"
    backend_dir.mkdir()
    (backend_dir / "go.mod").write_text("module example.com/backend\n\ngo 1.21\n", encoding="utf-8")
    (backend_dir / "main.go").write_text(
        """package main
import (
    "fmt"
    "net/http"
    "os/exec"
)

func runContainer(cmd string) {
    exec.Command("docker", "run", "--rm", "alpine", cmd).Run()
}

func main() {
    http.HandleFunc("/run", func(w http.ResponseWriter, r *http.Request) {
        runContainer("echo hello")
        fmt.Fprintf(w, "Executed")
    })
    http.ListenAndServe(":8080", nil)
}
""",
        encoding="utf-8",
    )

    # Frontend Next.js app (lots of JS files to ensure file-count dominance)
    frontend_dir = repo / "frontend" / "pages"
    frontend_dir.mkdir(parents=True)
    (repo / "frontend" / "package.json").write_text('{"name": "frontend", "dependencies": {"next": "14.0.0", "react": "18.0.0"}}', encoding="utf-8")
    for i in range(25):
        (frontend_dir / f"page_{i}.js").write_text(f"export default function Page{i}() {{ return <div>Page {i}</div>; }}", encoding="utf-8")

    return repo


def test_per_service_language_detection(temp_polyglot_repo: Path):
    """
    Asserts that RepositoryScanner identifies the target service runtime as GO (provided.al2023)
    from backend/main.go and backend/go.mod, despite repo having 25+ JS files.
    """
    scanner = RepositoryScanner(temp_polyglot_repo)
    inspection: RepoInspectionResult = scanner.scan()

    assert inspection.target_service_language.upper() == "GO", (
        f"Expected target service language to be 'GO', got '{inspection.target_service_language}'"
    )
    assert inspection.target_service_directory == "backend"
    assert "backend/main.go" in [p.replace("\\", "/") for p in inspection.entrypoints]
    # Verify repo-wide stats are also captured
    assert "JAVASCRIPT" in [lang.upper() for lang in inspection.repo_wide_languages]


def test_docker_blocker_caps_score_and_enforces_decoupling(temp_polyglot_repo: Path):
    """
    Asserts that Docker-in-Lambda is flagged as HIGH severity / NOT_DIRECTLY_COMPATIBLE,
    capping the score at <= 60 and forcing the verdict to 'MIGRATE (WITH DECOUPLING)'.
    """
    scanner = RepositoryScanner(temp_polyglot_repo)
    inspection: RepoInspectionResult = scanner.scan()

    # Create dummy AWS report for compatibility evaluation
    mock_aws = MagicMock()
    mock_aws.instances = []

    compat_engine = LambdaCompatibilityEngine()
    result: CompatibilityEvaluationReport = compat_engine.evaluate(inspection, mock_aws)

    assert result.overall_score <= 60, f"Expected score <= 60 due to Docker blocker, got {result.overall_score}"
    assert result.overall_verdict == "MIGRATE (WITH DECOUPLING)", (
        f"Expected verdict 'MIGRATE (WITH DECOUPLING)', got '{result.overall_verdict}'"
    )
    assert len(result.blockers) > 0, "Expected at least one blocker in result.blockers"
    assert any("Docker" in b or "container" in b.lower() for b in result.blockers)
    assert any("ECS Fargate" in c for c in result.conditions)

    # Test structured verdict dictionary format
    verdict_dict = result.to_verdict_dict()
    assert verdict_dict["verdict"] == "MIGRATE (WITH DECOUPLING)"
    assert verdict_dict["score"] <= 60
    assert len(verdict_dict["blockers"]) > 0
    assert len(verdict_dict["conditions"]) > 0


def test_honest_cost_estimation_with_zero_instances(temp_polyglot_repo: Path):
    """
    Asserts that CostEstimator with zero live EC2 instances:
      - Marks ec2_label with 'ESTIMATE (no live instance data)'
      - Does not claim 100% savings or zero EC2 expenditure
      - Includes auxiliary costs (API Gateway, CloudWatch, Fargate)
    """
    mock_aws = MagicMock()
    mock_aws.instances = []

    cost_estimator = CostEstimator()
    analysis: CostBreakdown = cost_estimator.estimate(
        aws=mock_aws,
        has_docker_decoupling=True,
    )

    assert not analysis.has_live_instance
    assert "ESTIMATE" in analysis.ec2_label
    assert "no live instance data" in analysis.ec2_label
    assert analysis.ec2_range != ""
    assert "100" not in analysis.savings_label or "ESTIMATE" in analysis.savings_label
    assert analysis.fargate_monthly_estimated > 0.0, "Expected Fargate task estimate when docker decoupling is required"
    assert "HTTP API" in str(analysis.lambda_itemized)
    assert "CloudWatch" in str(analysis.lambda_itemized)


def test_verdict_consistency_across_orchestrator(temp_polyglot_repo: Path):
    """
    Asserts that DarogaOrchestrator produces a single source of truth DarogaAuditResult
    whose verdict string, blockers, and conditions are identical across all reports and outputs.
    """
    out_report = temp_polyglot_repo / "EC2_TO_LAMBDA_MIGRATION_REPORT.md"
    orchestrator = DarogaOrchestrator(
        repo_path=temp_polyglot_repo,
        output_report_path=out_report,
    )

    # Mock EC2Inspector to return empty instances list
    with patch("daroga.orchestrator.EC2Inspector") as mock_ec2_cls:
        mock_ec2_instance = MagicMock()
        mock_aws_report = MagicMock()
        mock_aws_report.identity.account_id = "123456789012"
        mock_aws_report.identity.region = "us-east-1"
        mock_aws_report.instances = []
        mock_aws_report.discovered_from_cdp = False
        mock_aws_report.auto_discovered_region = None
        mock_ec2_instance.inspect_all.return_value = mock_aws_report
        mock_ec2_cls.return_value = mock_ec2_instance

        audit_res: DarogaAuditResult = orchestrator.run_audit()

    assert audit_res.verdict == "MIGRATE (WITH DECOUPLING)"
    assert audit_res.score <= 60
    assert len(audit_res.blockers) > 0
    assert audit_res.target_runtime == "provided.al2023"

    # Verify report was generated
    assert out_report.is_file()
    report_text = out_report.read_text(encoding="utf-8")
    assert "MIGRATE (WITH DECOUPLING)" in report_text
    assert "ESTIMATE (no live instance data)" in report_text
    assert "provided.al2023" in report_text
