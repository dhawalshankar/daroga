# AWS Serverless Migration Report

Reference note for the bundled `lambda_app/` Flask service. The `daroga` CLI does not write this filename. A live audit writes `EC2_TO_LAMBDA_MIGRATION_REPORT.md` with the 23 sections produced by `daroga/report_generator.py`.

## Executive Summary

- **Source:** `ec2_app/` Flask process (`compute: AWS EC2` on `/health`)
- **This folder:** `lambda_app/` Flask app wrapped by `apig_wsgi` in `lambda_function.py`
- **Checked-in runtime:** `python3.11` in `lambda_app/template.yaml` (handler `lambda_function.lambda_handler`, HTTP API `ANY /` and `ANY /{proxy+}`, 512 MB, 30 s)
- **Current generator default for a new Python service:** `python3.12` in templates emitted by `agent.run_offline_analysis`
- **Verdict for this sample:** The app is a stateless JSON API with an in-memory list. That shape is the compatibility engine’s normal HTTP case: **`MIGRATE (WITH CODE MODIFICATIONS)`** because the continuous process must become an API Gateway event (rule `RULE-NET-01`, medium). There is no Docker, WebSocket, or SQLite finding in this sample, so it is not a decoupling case

## Artifacts in this folder

1. `app.py` — Flask routes `/health`, `/tasks`
2. `lambda_function.py` — `apig_wsgi.make_lambda_handler(app)`
3. `requirements.txt` — Flask and `apig-wsgi`
4. `template.yaml` — SAM definition pinned to Python 3.11
5. `USER.md` — console steps that match this folder’s runtime

## Cost illustration

Figures use `daroga/cost_estimator.py` (730 hours, 30 GB gp3 at `$0.08/GB-month`). This sample does not call AWS, so the rows are an illustration for a `t3.small`, which is the estimator’s rate for that type (`$0.0208/hour`).

| | Amount |
|---|---|
| EC2 compute `t3.small` | `0.0208 * 730` = **$15.18/month** |
| EBS 30 GB gp3 | **$2.40/month** |
| EC2 baseline | **$17.58/month** |
| Lambda under 1,000,000 requests | **$0.00/month** (permanent free tier in the estimator) |
| Lambda at 2,500,000 requests | **$1.80/month** (`$0.30` invocations + `$1.50` HTTP API) in the estimator |
| Savings at low traffic vs this baseline | **$17.58/month** (100% of the EC2 baseline). The estimator only prints a percent when a live instance was returned; with no instance the report says **ESTIMATE** |

HTTP API’s own 1,000,000 free calls are a 12-month allowance in the report text, separate from the permanent Lambda request allowance.
