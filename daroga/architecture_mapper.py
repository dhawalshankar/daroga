"""
DAROGA Architecture Mapper Module
=================================
Maps current EC2 virtual machine responsibilities to their exact AWS Serverless equivalents.
Documents purpose, interaction, configuration requirements, and cost impacts.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from daroga.repository_scanner import RepoInspectionResult
from daroga.ec2_inspector import AWSInfrastructureReport
from daroga.lambda_compatibility import CompatibilityEvaluationReport


@dataclass
class ProposedComponent:
    service_name: str
    purpose: str
    replaces_ec2_responsibility: str
    lambda_interaction: str
    user_configuration: str
    cost_impact: str
    reusable_existing_resource: Optional[str] = None


@dataclass
class TargetServerlessArchitecture:
    project_name: str
    primary_compute: str = "AWS Lambda (arm64 Graviton)"
    api_gateway_type: str = "HTTP API (API Gateway v2)"
    components: List[ProposedComponent] = field(default_factory=list)
    iam_role_name: str = "LambdaExecutionRole"
    iam_policies: List[str] = field(default_factory=list)
    vpc_configuration: Optional[str] = None
    security_group_configuration: Optional[str] = None


class ArchitectureMapper:
    """
    Synthesizes a tailored, serverless AWS target architecture based on discovered findings.
    """

    def map_architecture(
        self,
        repo: RepoInspectionResult,
        aws: AWSInfrastructureReport,
        compat: CompatibilityEvaluationReport
    ) -> TargetServerlessArchitecture:
        arch = TargetServerlessArchitecture(
            project_name=repo.repo_name,
            iam_role_name=f"{repo.repo_name}-LambdaExecutionRole",
        )

        # 1. AWS Lambda Function
        arch.components.append(ProposedComponent(
            service_name="AWS Lambda (arm64 Graviton)",
            purpose=f"Executes {repo.primary_language.capitalize()} backend API logic on-demand without persistent EC2 instances.",
            replaces_ec2_responsibility="Replaces 24/7 EC2 virtual machine CPU, memory, and continuous OS host.",
            lambda_interaction="Core compute engine executing serverless entrypoint.",
            user_configuration=f"Configure runtime '{compat.recommended_runtime}', memory {compat.recommended_memory_mb} MB, timeout {compat.recommended_timeout_sec}s.",
            cost_impact="Pay-per-millisecond (First 1,000,000 requests and 3,200,000 compute-seconds per month are 100% FREE).",
            reusable_existing_resource="None (new serverless resource)",
        ))

        # 2. Amazon API Gateway HTTP API
        arch.components.append(ProposedComponent(
            service_name="Amazon API Gateway (HTTP API v2)",
            purpose="Exposes live public HTTPS endpoints and routes client requests directly to the Lambda function.",
            replaces_ec2_responsibility="Replaces EC2 local port listeners, reverse proxies (Nginx/Caddy), and public IP port routing.",
            lambda_interaction="Translates incoming HTTP requests into JSON events and invokes Lambda with `/{proxy+}` catch-all routes.",
            user_configuration="Create HTTP API with route `ANY /{proxy+}` integrating with the Lambda function with payload format version 2.0.",
            cost_impact="$1.00 per 1,000,000 requests after AWS Free Tier.",
            reusable_existing_resource="Can reuse existing custom domains via Route 53 and ACM certificates.",
        ))

        # 3. Amazon CloudWatch Logs
        arch.components.append(ProposedComponent(
            service_name="Amazon CloudWatch Logs",
            purpose="Aggregates application stdout/stderr logs and execution telemetry.",
            replaces_ec2_responsibility="Replaces local log files (`/var/log/...`), journald, and logrotate on the EC2 EBS volume.",
            lambda_interaction="Lambda runtime automatically streams stdout/stderr directly into log group `/aws/lambda/<function-name>`.",
            user_configuration="Set retention policy to 14 or 30 days to optimize storage costs.",
            cost_impact="5 GB ingestion free tier per month; $0.50 per GB ingested thereafter.",
            reusable_existing_resource="Existing CloudWatch log groups if already configured.",
        ))

        # 4. IAM Execution Role
        arch.iam_policies = [
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
        ]

        if aws.instances and aws.instances[0].vpc_id:
            arch.iam_policies.append("arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole")
            arch.vpc_configuration = f"Deploy within VPC {aws.instances[0].vpc_id} across private subnets for secure database access."
            arch.security_group_configuration = f"Attach to dedicated Lambda security group allowing outbound port access to existing security group {aws.instances[0].security_group_ids}."

        arch.components.append(ProposedComponent(
            service_name="AWS Identity and Access Management (IAM)",
            purpose="Grants Lambda least-privilege permission to emit logs, access VPC networking, and query databases.",
            replaces_ec2_responsibility="Replaces EC2 IAM Instance Profile attached to the virtual machine.",
            lambda_interaction="Assumed automatically by the Lambda service when executing invocations.",
            user_configuration="Create execution role with trust policy for `lambda.amazonaws.com` and attach basic execution policy.",
            cost_impact="Free of charge (IAM features are always free).",
            reusable_existing_resource=aws.instances[0].iam_instance_profile if (aws.instances and aws.instances[0].iam_instance_profile) else None,
        ))

        # 5. Database & Storage Considerations
        if repo.database_types:
            arch.components.append(ProposedComponent(
                service_name=f"Existing Database ({', '.join(repo.database_types)})",
                purpose="Maintains relational or document persistence for the backend service.",
                replaces_ec2_responsibility="Retains existing database infrastructure without modification.",
                lambda_interaction="Lambda connects via VPC networking or secure TLS connection strings.",
                user_configuration="Provide database connection URI under Lambda Environment Variables; optionally attach Amazon RDS Proxy.",
                cost_impact="No new charges; reuses existing database cluster.",
                reusable_existing_resource="Existing RDS / Aurora / MongoDB instance.",
            ))

        # 6. EventBridge Scheduler if background tasks exist
        if repo.has_scheduled_jobs:
            arch.components.append(ProposedComponent(
                service_name="Amazon EventBridge Scheduler",
                purpose="Triggers periodic maintenance, reporting, or batch jobs on a scheduled cron cadence.",
                replaces_ec2_responsibility="Replaces crontab or in-process cron tickers running continuously on EC2.",
                lambda_interaction="Invokes designated Lambda functions with scheduled JSON events.",
                user_configuration="Define schedule expression (e.g. `cron(0 0 * * ? *)`) with target set to Lambda ARN.",
                cost_impact="14,000,000 invocations free per month ($1.00 per million thereafter).",
                reusable_existing_resource="None",
            ))

        return arch
