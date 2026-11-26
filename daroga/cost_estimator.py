"""
DAROGA Cost & AWS Free-Tier Assessment Module
=============================================
Provides a deterministic cost comparison between 24/7 EC2 virtual machine hosting
and the on-demand AWS Lambda serverless model based on official AWS pricing.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
from daroga.ec2_inspector import AWSInfrastructureReport


@dataclass
class CostBreakdown:
    has_live_instance: bool
    ec2_label: str
    ec2_range: str
    ec2_monthly_estimated: float
    lambda_low_traffic_monthly: float
    lambda_medium_traffic_monthly: float
    monthly_savings_low: float
    monthly_savings_percent: Optional[float]
    savings_label: str
    fargate_monthly_estimated: float = 0.0
    ec2_itemized: Dict[str, str] = field(default_factory=dict)
    lambda_itemized: Dict[str, str] = field(default_factory=dict)
    free_tier_allowances: Dict[str, str] = field(default_factory=dict)
    assumptions: Dict[str, str] = field(default_factory=dict)


class CostEstimator:
    """
    Deterministic pricing calculator comparing legacy EC2 to AWS Lambda.
    """

    # Baseline On-Demand Hourly Rates (us-east-1 Linux)
    EC2_RATES = {
        "t2.nano": 0.0058, "t2.micro": 0.0116, "t2.small": 0.023, "t2.medium": 0.0464,
        "t3.nano": 0.0052, "t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416,
        "t3.large": 0.0832, "t4g.nano": 0.0042, "t4g.micro": 0.0084, "t4g.small": 0.0168,
        "t4g.medium": 0.0336, "t4g.large": 0.0672, "m5.large": 0.096, "c5.large": 0.085,
    }
    HOURS_PER_MONTH = 730
    EBS_GP3_PER_GB_MONTH = 0.08

    def estimate(
        self,
        aws: AWSInfrastructureReport,
        memory_mb: int = 512,
        avg_duration_ms: int = 150,
        has_docker_decoupling: bool = False,
    ) -> CostBreakdown:
        has_instance = bool(aws.instances)

        # 1. Calculate EC2 Costs
        inst_type = "t3.micro"
        if has_instance:
            inst = aws.instances[0]
            inst_type = inst.instance_type
            inst_name = inst.tags.get("Name") or inst.instance_id
            ec2_label = f"Live Instance: {inst_name} ({inst.instance_id}, {inst_type})"
        else:
            ec2_label = "ESTIMATE (no live instance data)"

        hourly_rate = self.EC2_RATES.get(inst_type, 0.0104)
        ec2_compute_monthly = hourly_rate * self.HOURS_PER_MONTH
        ebs_monthly = 30 * self.EBS_GP3_PER_GB_MONTH  # Baseline 30 GB gp3 volume
        ec2_total = ec2_compute_monthly + ebs_monthly

        if has_instance:
            ec2_range = f"${ec2_total:.2f}/month"
        else:
            ec2_range = "$5.00 – $35.00+/month (typical t3.nano to t3.medium)"

        # 2. Calculate Lambda Costs
        lambda_low_cost = 0.00
        lambda_medium_cost = 0.30 + 1.50  # Total $1.80/month for 2.5M requests

        fargate_cost = 0.0
        if has_docker_decoupling:
            fargate_cost = 5.00
            lambda_medium_cost += fargate_cost

        savings_low = ec2_total - lambda_low_cost

        if has_instance:
            savings_pct = (savings_low / ec2_total) * 100 if ec2_total > 0 else 0.0
            savings_label = f"{savings_pct:.1f}% (~${savings_low:.2f}/mo)"
        else:
            # Never claim 100% savings without real instance data!
            savings_pct = None
            savings_label = "ESTIMATE (no live instance data - depends on actual EC2 type)"

        ec2_itemized_data = {
            f"EC2 Compute ({inst_type} 24/7)": f"${ec2_compute_monthly:.2f}/mo ({hourly_rate:.4f}/hr * 730 hrs)",
            "EBS Volume Storage (30 GB gp3)": f"${ebs_monthly:.2f}/mo ($0.08/GB-month)",
            "Baseline EC2 Total": f"${ec2_total:.2f}/month",
        }
        if not has_instance:
            ec2_itemized_data["Status Note"] = "No live EC2 instance discovered; baseline calculated using t3.micro heuristics ($5-$35/mo range)."

        lambda_itemized_data = {
            "Low Traffic (<1,000,000 requests/mo)": "$0.00/month (100% Free Tier Eligible)",
            "Moderate Traffic (2,500,000 requests/mo)": f"${lambda_medium_cost:.2f}/month ($1.50 API Gateway + $0.30 Lambda invocations" + (f" + ${fargate_cost:.2f} Fargate" if has_docker_decoupling else "") + ")",
            "Amazon API Gateway HTTP API": "$1.00 per 1M requests after 1M free",
            "Amazon CloudWatch Logs": "$0.50 per GB ingested after 5 GB free tier",
            "Data Transfer Out": "Free tier covers first 100 GB/month ($0.09/GB thereafter)",
        }
        if has_docker_decoupling:
            lambda_itemized_data["AWS Fargate Task Worker (Decoupled Runner)"] = "$2.50 – $15.00/month (per-second vCPU/RAM for container tasks)"

        breakdown = CostBreakdown(
            has_live_instance=has_instance,
            ec2_label=ec2_label,
            ec2_range=ec2_range,
            ec2_monthly_estimated=round(ec2_total, 2),
            lambda_low_traffic_monthly=round(lambda_low_cost, 2),
            lambda_medium_traffic_monthly=round(lambda_medium_cost, 2),
            monthly_savings_low=round(savings_low, 2),
            monthly_savings_percent=savings_pct,
            savings_label=savings_label,
            fargate_monthly_estimated=fargate_cost,
            ec2_itemized=ec2_itemized_data,
            lambda_itemized=lambda_itemized_data,
            free_tier_allowances={
                "AWS Lambda Invocations": "1,000,000 free requests per month (Permanent Free Tier)",
                "AWS Lambda Compute (Arm64 Graviton)": "3,200,000 GB-seconds per month (Permanent Free Tier)",
                "Amazon API Gateway (HTTP API)": "1,000,000 free API calls per month for the first 12 months",
                "Amazon CloudWatch Logs": "5 GB log data ingestion and 5 GB archival per month (Permanent Free Tier)",
            },
            assumptions={
                "Function Memory": f"{memory_mb} MB allocated",
                "Average Request Duration": f"{avg_duration_ms} ms per invocation",
                "Architecture": "Arm64 (Graviton2/Graviton3) providing 20% lower price than x86",
                "Data Transfer Out": "Assumed under 100 GB/month (AWS provides 100 GB free Internet egress per month)",
            }
        )
        return breakdown
