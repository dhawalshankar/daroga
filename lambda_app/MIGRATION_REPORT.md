# AWS Serverless Migration Report

## Executive Summary
- **Source Architecture**: Legacy AWS EC2 instance (always-on compute listener)
- **Target Architecture**: AWS Lambda + Amazon API Gateway (pay-per-request serverless)
- **Migration Verdict**: **MIGRATE**
- **Assessment Rationale**: The service is completely stateless, uses standard HTTP request-response lifecycles, and contains no blocking background threads or local filesystem database dependencies.

## Artifacts Generated
1. `lambda_function.py`: WSGI entrypoint wrapping the Flask app using `apig-wsgi`.
2. `requirements.txt`: Updated to include `apig-wsgi>=2.17.0`.
3. `template.yaml`: Complete AWS Serverless Application Model (SAM) definition with API Gateway v2 triggers.
4. `USER.md`: Human operator guide detailing exact AWS Management Console setup.

## Estimated Cost Analysis
- **EC2 Always-On Model**: An active `t3.small` instance costs ~$15.18/month compute + EBS volume costs (~$2.40/month) = ~$17.58/month regardless of traffic.
- **AWS Lambda Pay-Per-Request Model**: With 1,000,000 monthly invocations @ 512MB memory and 100ms average latency, estimated compute cost is ~$0.83/month.
- **Estimated Savings**: **~95% reduction** in idle compute expense.
