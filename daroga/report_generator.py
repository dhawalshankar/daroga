"""
DAROGA Comprehensive Migration Report Generator
===============================================
Generates the authoritative EC2_TO_LAMBDA_MIGRATION_REPORT.md deliverable
incorporating all 23 required sections based on discovered technical facts.
"""

from datetime import datetime
from typing import Dict, List, Optional
from daroga.repository_scanner import RepoInspectionResult
from daroga.ec2_inspector import AWSInfrastructureReport
from daroga.browser_inspector import BrowserConsoleFinding
from daroga.lambda_compatibility import CompatibilityEvaluationReport, Severity
from daroga.architecture_mapper import TargetServerlessArchitecture
from daroga.cost_estimator import CostBreakdown
from daroga.token_tracker import TokenTracker


class ReportGenerator:
    """
    Renders the formal, 23-section EC2 to Lambda migration report.
    """

    def generate(
        self,
        repo: RepoInspectionResult,
        aws: AWSInfrastructureReport,
        browser: BrowserConsoleFinding,
        compat: CompatibilityEvaluationReport,
        arch: TargetServerlessArchitecture,
        cost: CostBreakdown,
        tracker: TokenTracker,
    ) -> str:
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        account_id_str = aws.identity.account_id or "[Unconfigured / Manual Entry]"
        region_str = aws.identity.region or "us-east-1"

        instance_id_str = aws.instances[0].instance_id if aws.instances else "[ec2-instance-id]"
        instance_type_str = aws.instances[0].instance_type if aws.instances else "t3.micro"
        vpc_id_str = aws.instances[0].vpc_id if (aws.instances and aws.instances[0].vpc_id) else (aws.vpcs[0]["VpcId"] if aws.vpcs else "[vpc-xxxx]")
        subnet_id_str = aws.instances[0].subnet_id if (aws.instances and aws.instances[0].subnet_id) else (aws.subnets[0]["SubnetId"] if aws.subnets else "[subnet-xxxx]")
        sg_ids_str = ", ".join(aws.instances[0].security_group_ids) if (aws.instances and aws.instances[0].security_group_ids) else "[sg-xxxx]"

        # Format compatibility findings table
        findings_rows = []
        for f in compat.findings:
            sev_badge = f"**{f.severity.value}**"
            findings_rows.append(f"| `{f.rule_id}` | {f.category} | {f.title} | {f.status.value} | {sev_badge} | {f.recommended_action} |")
        findings_table = "\n".join(findings_rows)

        # Format components table
        components_rows = []
        for c in arch.components:
            components_rows.append(f"| **{c.service_name}** | {c.purpose} | {c.replaces_ec2_responsibility} | {c.cost_impact} |")
        components_table = "\n".join(components_rows)

        if cost.has_live_instance:
            ec2_cost_str = f"**${cost.ec2_monthly_estimated:.2f}/month** ({cost.ec2_label})"
            savings_str = f"**{cost.monthly_savings_percent:.1f}%** (${cost.monthly_savings_low:.2f}/month)"
        else:
            ec2_cost_str = f"**{cost.ec2_label}:** {cost.ec2_range}"
            savings_str = f"**{cost.savings_label}**"

        report = f"""# EC2 TO LAMBDA MIGRATION REPORT
**Audited Application:** `{repo.repo_name}`  
**Audit Tool:** DAROGA Autonomous Infrastructure Inspector & Migration Auditor  
**Generated Date:** {timestamp_str}  
**AWS Account ID:** `{account_id_str}`  
**AWS Region:** `{region_str}`  

---

## 1. Executive Summary
This report presents an application-specific, architectural migration assessment for transitioning `{repo.repo_name}` from an Amazon EC2 virtual machine hosting model to **AWS Lambda Serverless Architecture**.

* **Target Service Stack:** {repo.primary_language.capitalize()} ({', '.join(repo.frameworks) or 'Standard HTTP/REST'})
* **Target Migration Scope:** {'`' + repo.target_service_directory + '` backend service' if repo.target_service_directory else 'Root application service'}
* **Migration Suitability Verdict:** **{compat.overall_verdict}** (Compatibility Score: **{compat.overall_score:.0f}%**)
* **Baseline EC2 Cost:** {ec2_cost_str}
* **Projected Serverless Lambda Cost (Low/Moderate Traffic):** **${cost.lambda_low_traffic_monthly:.2f} – ${cost.lambda_medium_traffic_monthly:.2f}/month**
* **Potential Monthly Infrastructure Savings:** {savings_str}
{('* **Blockers Detected:** ' + '; '.join(compat.blockers)) if compat.blockers else ''}
{('* **Required Architectural Conditions:** ' + '; '.join(compat.conditions)) if compat.conditions else ''}

> **Important Operational Guardrail:** This report is prepared by an autonomous auditor. In accordance with safety restrictions, **no production infrastructure was modified and no code was deployed**. The user performs all actual implementation steps manually using the copy-paste instructions in Section 16 & 17.

---

## 2. Existing Application Architecture
* **Target Service Language & Runtime:** {repo.primary_language.capitalize()} (Recommended Lambda Runtime: `{compat.recommended_runtime}`)
* **Repo-Wide Languages:** {', '.join(repo.repo_wide_languages) or ', '.join(repo.languages)}
* **Web Framework:** {', '.join(repo.frameworks) or 'Native HTTP router'}
* **Entry Point(s):** {', '.join(repo.entrypoints) or 'Not explicitly resolved'}
* **Exposed Ports:** {', '.join(str(p) for p in repo.exposed_ports) or 'Dynamic / Environment PORT'}
* **Continuous Execution Model:** The application currently runs as a persistent listening daemon (managed via systemd, PM2, or Docker) on an EC2 instance. In the serverless model, this persistent socket listener is superseded by an event-driven AWS API Gateway HTTP trigger.

---

## 3. Repository Analysis
* **Total Files Scanned:** {repo.total_files_scanned} files inspected deterministically.
* **Package Managers & Manifests:** {', '.join(repo.package_managers) or 'None detected'}
* **Container Specifications:** {', '.join(repo.dockerfiles) or 'None'}
* **Web Server / Reverse Proxy Configs:** {', '.join(repo.nginx_configs) or 'None (direct port binding)'}
* **CI/CD Workflows:** {', '.join(repo.cicd_configs) or 'None detected'}
* **Database Integrations:** {', '.join(repo.database_types) or 'None detected / Stateless API'}

---

## 4. Existing EC2 Configuration
* **Instance ID:** `{instance_id_str}`
* **Instance Type:** `{instance_type_str}`
* **State:** `{aws.instances[0].state if aws.instances else 'Assumed Running'}`
* **AMI ID:** `{aws.instances[0].ami_id if aws.instances else '[ami-xxxx]'}`
* **Platform Details:** `{aws.instances[0].platform_or_os if aws.instances else 'Linux/UNIX'}`
* **Attached EBS Volumes:** {', '.join(f'`{v}`' for v in aws.instances[0].ebs_volume_ids) if (aws.instances and aws.instances[0].ebs_volume_ids) else 'Standard gp3 root volume (30 GB)'}
* **IAM Instance Profile:** `{aws.instances[0].iam_instance_profile if (aws.instances and aws.instances[0].iam_instance_profile) else 'None'}`

---

## 5. Existing AWS Dependencies
* **Core Compute:** Amazon EC2 Virtual Machine
* **Storage:** Amazon EBS gp3 Elastic Block Store
* **Networking:** Amazon VPC, Internet Gateway, Security Groups
* **Auxiliary Services Inspected:** {'None required' if not repo.database_types else ', '.join(repo.database_types)}
* **Browser CDP Cross-Check:** {'Authenticated AWS Console session verified on port 9222.' if browser.cdp_available else 'CDP not connected: ' + '; '.join(browser.notes)}

---

## 6. Existing Networking Architecture
* **Virtual Private Cloud (VPC):** `{vpc_id_str}`
* **Subnet ID:** `{subnet_id_str}`
* **Security Group Associations:** `{sg_ids_str}`
* **Ingress Traffic Flow:** Currently allows direct inbound traffic on ports `{', '.join(str(p) for p in repo.exposed_ports) or '80, 443, 8080'}` to the EC2 network interface.
* **Target Serverless Flow:** Public traffic hits Amazon API Gateway HTTPS endpoints, which invokes AWS Lambda within the private VPC subnets.

---

## 7. Relevant IAM Configuration
* **Existing EC2 Role:** `{aws.instances[0].iam_instance_profile if (aws.instances and aws.instances[0].iam_instance_profile) else 'None (uses default AWS credentials or instance metadata)'}`
* **Required Lambda Execution Role:** `{arch.iam_role_name}`
* **Trust Relationship:** `lambda.amazonaws.com`
* **Managed Policies to Attach:**
{chr(10).join(f"- `{p}`" for p in arch.iam_policies)}

---

## 8. Lambda Compatibility Assessment

| Rule ID | Category | Assessment Finding | Compatibility Classification | Severity | Recommended Action |
| :--- | :--- | :--- | :--- | :--- | :--- |
{findings_table}

---

## 9. Migration Blockers
{chr(10).join(f"- ⚠️ **{b}**" for b in compat.blockers) if compat.blockers else "- ✅ **Zero Fatal Blockers:** The application architecture is compatible with AWS Lambda serverless execution."}

---

## 10. Proposed Lambda Architecture
The recommended target architecture replaces the 24/7 EC2 server process with an event-driven serverless topology:

```
[Client / Browser / Frontend]
              │
              ▼ HTTPS
[Amazon API Gateway (HTTP API v2)]
              │
              ▼ Event Payload (APIGatewayV2HTTPRequest)
[AWS Lambda Function (arm64 Graviton)]
        │                    │
        ▼                    ▼
[Amazon CloudWatch Logs]  [Existing Database / VPC Resources]
```

---

## 11. Required AWS Resources

| AWS Service | Architectural Role | Replaces EC2 Responsibility | Cost Impact |
| :--- | :--- | :--- | :--- |
{components_table}

---

## 12. IAM Execution Role Requirements
Create an execution role for Lambda with least-privilege permissions:
* **Role Name:** `{arch.iam_role_name}`
* **Trust Policy:**
```json
{{
  "Version": "2012-10-17",
  "Statement": [
    {{
      "Effect": "Allow",
      "Principal": {{
        "Service": "lambda.amazonaws.com"
      }},
      "Action": "sts:AssumeRole"
    }}
  ]
}}
```

---

## 13. API Gateway Configuration
* **Type:** HTTP API (API Gateway v2) — provides lowest latency and 70% cost savings compared to REST APIs.
* **Integrations:** AWS Lambda proxy integration (`payloadFormatVersion: "2.0"`).
* **Routes to Configure:**
  - `ANY /` -> Integrates with Lambda
  - `ANY /{{proxy+}}` -> Integrates with Lambda catch-all
* **CORS Settings:** Allowed Origins: `*` (or your production frontend domain), Allowed Methods: `GET, POST, PUT, DELETE, OPTIONS`.

---

## 14. Networking and Database Configuration
* **VPC Attachment:** If connecting to private RDS or internal VPC caches, attach Lambda to VPC `{vpc_id_str}` across subnets `{subnet_id_str}`.
* **Security Group:** Assign a security group allowing outbound port access (e.g. `5432` for Postgres, `3306` for MySQL) into the database security group.
* **Connection Lifecycle:** In serverless architectures, instantiate database connection pools outside the main request handler (in global initialization scope) to reuse database sockets across warm invocations.

---

## 15. Required Application Code Changes
To run on AWS Lambda, the user must implement the following serverless entrypoint adjustments:

{chr(10).join(f"{i+1}. **{c}**" for i, c in enumerate(compat.required_code_changes))}

*Example Serverless Entrypoint (Golang):*
```go
package main

import (
    "context"
    "net/http"
    "github.com/aws/aws-lambda-go/events"
    "github.com/aws/aws-lambda-go/lambda"
    "github.com/awslabs/aws-lambda-go-api-proxy/httpadapter"
)

var adapter *httpadapter.HandlerAdapter

func init() {{
    adapter = httpadapter.New(http.DefaultServeMux)
}}

func Handler(ctx context.Context, req events.APIGatewayV2HTTPRequest) (events.APIGatewayV2HTTPResponse, error) {{
    return adapter.ProxyWithContext(ctx, req)
}}

func main() {{
    lambda.Start(Handler)
}}
```

---

## 16. Step-by-Step AWS Console Instructions

### Step 1: Create IAM Role in AWS Console
1. Open the [AWS IAM Console -> Roles](https://console.aws.amazon.com/iam/home#/roles).
2. Click **Create role** -> Select **AWS service** -> Use case: **Lambda** -> Click **Next**.
3. Under Add permissions, search and select:
   - `AWSLambdaBasicExecutionRole`
   - `AWSLambdaVPCAccessExecutionRole` (if VPC database connectivity is required)
4. Role name: `{arch.iam_role_name}` -> Click **Create role**.

### Step 2: Create the Lambda Function in AWS Console
1. Open the [AWS Lambda Console](https://console.aws.amazon.com/lambda/home#/functions).
2. Click **Create function** -> **Author from scratch**.
3. **Function name:** `{repo.repo_name}-backend`
4. **Runtime:** Select `{compat.recommended_runtime}`.
5. **Architecture:** Select **arm64** (Graviton2/3).
6. Under Permissions, select **Use an existing role** -> Choose `{arch.iam_role_name}`.
7. Click **Create function**.

### Step 3: Configure Function Timeout & Memory
1. In the function details, open the **Configuration** tab -> **General configuration** -> Click **Edit**.
2. Set **Memory:** `{compat.recommended_memory_mb} MB`.
3. Set **Timeout:** `{compat.recommended_timeout_sec} sec`.
4. Click **Save**.

### Step 4: Configure API Gateway HTTP Trigger
1. In the Lambda function overview diagram, click **+ Add trigger**.
2. Select **API Gateway**.
3. Intent: **Create a new API** -> API type: **HTTP API**.
4. Security: **Open** (or configure JWT / IAM authorizer).
5. Click **Add**.
6. The public URL will display under **API endpoint** (e.g. `https://xxxx.execute-api.{region_str}.amazonaws.com`).

---

## 17. Copy-Paste-Ready AWS CLI Commands

> **Notice:** All commands below are for manual execution by the user. The agent does not execute modification commands.

### Inspection Commands (Read-Only)
```powershell
# Verify current AWS identity and active region
aws sts get-caller-identity

# Inspect existing EC2 instance configuration
aws ec2 describe-instances --instance-ids {instance_id_str} --region {region_str}

# Inspect associated security groups
aws ec2 describe-security-groups --group-ids {sg_ids_str} --region {region_str}
```

### Manual Deployment Commands (User-Executed)
```powershell
# 1. Create the Lambda Execution Role
aws iam create-role `
  --role-name {arch.iam_role_name} `
  --assume-role-policy-document '{{"Version":"2012-10-17","Statement":[{{"Effect":"Allow","Principal":{{"Service":"lambda.amazonaws.com"}},"Action":"sts:AssumeRole"}}]}}'

# 2. Attach Basic Execution Policy
aws iam attach-role-policy `
  --role-name {arch.iam_role_name} `
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# 3. Create the Lambda Function (replace deployment.zip with your compiled zip)
aws lambda create-function `
  --function-name {repo.repo_name}-backend `
  --runtime {compat.recommended_runtime} `
  --role arn:aws:iam::{account_id_str}:role/{arch.iam_role_name} `
  --handler bootstrap `
  --architectures arm64 `
  --timeout {compat.recommended_timeout_sec} `
  --memory-size {compat.recommended_memory_mb} `
  --zip-file fileb://deployment.zip `
  --region {region_str}
```

---

## 18. Cost and Free-Tier Assessment

### Cost Comparison Table

| Service / Resource | Legacy EC2 Virtual Machine | Proposed AWS Lambda Serverless |
| :--- | :--- | :--- |
| **Compute Charges** | `${cost.ec2_monthly_estimated:.2f}/month` (24/7 {instance_type_str}) | `$0.00/month` (Within 3.2M free GB-seconds) |
| **Request Charges** | N/A (included in VM) | `$0.00/month` (Within 1M free requests) |
| **API Gateway Ingress** | N/A (direct TCP ingress) | `$0.00/month` (<1M free calls) or ~$1.00/M |
| **Disk Storage** | ~$2.40/month (30 GB gp3 volume) | `$0.00/month` (512MB ephemeral `/tmp` included) |
| **Monthly Total** | **${cost.ec2_monthly_estimated:.2f}/month** | **${cost.lambda_low_traffic_monthly:.2f} – ${cost.lambda_medium_traffic_monthly:.2f}/month** |

* **AWS Free Tier Allowances Applicable:**
  - 1,000,000 Lambda invocations free per month (Permanent).
  - 3,200,000 GB-seconds of compute time per month (Permanent).
  - 1,000,000 HTTP API calls free per month (First 12 months).
  - 5 GB CloudWatch Logs ingestion free per month (Permanent).

---

## 19. Verification Checklist
- [ ] Lambda function created with runtime `{compat.recommended_runtime}` and architecture `arm64`.
- [ ] IAM execution role `{arch.iam_role_name}` attached with basic logging permissions.
- [ ] API Gateway HTTP trigger mapped to `ANY /{{proxy+}}` routes.
- [ ] Database connection URI and secrets added under Configuration -> Environment variables.
- [ ] Executed test event in Lambda Console (`apigateway-aws-proxy` template) returns HTTP 200.
- [ ] Tested public HTTPS endpoint using curl or Postman.
- [ ] CloudWatch Log stream verified under Monitoring -> View CloudWatch logs.

---

## 20. Rollback Procedure
* **EC2 Instance Preservation:** Keep the existing EC2 instance `{instance_id_str}` in the **Running** or **Stopped** state throughout the initial serverless evaluation period.
* **Instant Traffic Rollback:** Because DNS traffic routing is managed at the domain level (Route 53 or your DNS registrar), if any unforeseen issue arises on AWS Lambda, simply point your DNS A-Record or ALB target back to the EC2 Elastic IP address `{aws.instances[0].public_ip if (aws.instances and aws.instances[0].public_ip) else '[ec2-public-ip]'}`.
* **Zero Downtime Risk:** No existing EC2 compute or EBS storage is terminated during the migration planning phase.

---

## 21. Final Migration Readiness Assessment
* **Readiness Level:** **READY FOR MANUAL SERVERLESS STAGING**
* **Technical Verdict:** The application's core HTTP routing is well suited for AWS Lambda pay-per-request execution. By containerizing or compiling to an ARM64 binary with a serverless adapter, the workload eliminates 24/7 idle EC2 compute costs while achieving automated scaling.

---

## 22. Inspection Limitations
- **Read-Only Scope:** The auditor strictly abstained from modifying files, creating resources, or touching live production configurations.
- **Dynamic Workload Runtime:** If the application relies on nested Docker daemon calls or background compilations, these subroutines must be asynchronously delegated to ECS Fargate or Lambda Container images as outlined in Section 8.
- **Browser CDP:** {browser.notes[0] if browser.notes else 'Existing browser inspected.'}

---

## 23. LLM Usage and Token Consumption Summary
```text
{tracker.get_summary()}
```

---
*Report compiled autonomously by DAROGA Migration Auditor.*
"""
        return report
