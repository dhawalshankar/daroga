# EC2 → Lambda Migration Agent

An AI agent that reads an app built for EC2, decides whether it is a good fit for AWS Lambda,
and writes a Lambda-ready version on a **separate local git branch**.
It never pushes, merges, or deploys, and it never touches the cloud.

Built with Python and the **Groq API** (tool calling). Intended for cloud administrators who
want a fast first draft of a serverless migration that a human then reviews.

---

## What it does

1. **Analyzes** the repo (framework, routes, background threads, local file or DB state, long-running work).
2. **Gives a verdict:** `migrate`, `partial`, or `do_not_migrate`, with reasons.
3. **Creates a new local branch** `lambda-migration-<timestamp>`.
4. **Writes the Lambda version:** `lambda_function.py`, updated `requirements.txt`, `template.yaml` (AWS SAM).
5. **Validates its own output** (`py_compile`, `sam validate`) and fixes errors it finds.
6. **Writes `MIGRATION_REPORT.md`:** what changed, what needs manual work, rough cost note.
7. **Commits on that branch only,** then returns you to your original branch.

## How the agent loop works

```
 repo ──► list/read files ──► LLM decides ──► write files ──► validate
              ▲                                                 │
              └───────────── fix errors and retry ◄─────────────┘
                                   │
                                   ▼
                        report + local commit (no push)
```

The LLM (via Groq) is given five tools: `list_files`, `read_file`, `write_file`, `run_command`, `finish`.
It decides which to call and in what order. The Python code enforces the safety rules.

## Safety guardrails

| Risk | Guardrail |
|---|---|
| Pushing or merging code | The agent has no git tool. Git is handled only by `agent.py` (branch, add, commit). |
| Cloud changes or cost | No AWS calls, no deploy. `aws`, `curl`, `wget`, `sudo`, `rm`, `git` are blocked in commands. |
| Arbitrary commands | `run_command` only allows `py_compile`, `pytest`, `sam validate`, `node --check` (no shell). |
| Writing outside the project | All paths are resolved and must stay inside the repo. `.git` is off limits. |
| Losing your work | The agent refuses to start if the working tree is not clean. |
| Touching your main code | Works on a new branch. Your original branch is never modified. |

## Folder structure

```
lambda-agent/
├── README.md              # this file
├── requirements.txt       # groq
├── .gitignore
├── agent.py               # the agent: tools, guardrails, agent loop, git flow
├── docs/
│   └── PRD.md             # product requirements document
├── sample_app/            # simple Flask API  → expected verdict: migrate
│   ├── app.py
│   └── requirements.txt
└── sample_bad_app/        # thread + local sqlite → expected verdict: do_not_migrate / partial
    ├── app.py
    └── requirements.txt
```

## Setup

Requirements: Python 3.10+, git, a [Groq API key](https://console.groq.com).
Optional: AWS SAM CLI (`pip install aws-sam-cli`) for `sam validate`.

```bash
pip install -r requirements.txt
export GROQ_API_KEY=gsk_xxxxx          # PowerShell: $env:GROQ_API_KEY="gsk_xxxxx"
# optional: pick another Groq model
export GROQ_MODEL=openai/gpt-oss-120b
```

Check [console.groq.com/docs/models](https://console.groq.com/docs/models) if a model ID is rejected;
Groq's model list changes over time.

## Usage

The target must be a git repo with a clean working tree.

```bash
# prepare the sample once
cd sample_app && git init && git add . && git commit -m "init" && cd ..

# run the agent
python agent.py sample_app

# review the result (use master instead of main if that is your default branch)
cd sample_app
git branch
git diff main..lambda-migration-<timestamp> --stat
git checkout lambda-migration-<timestamp>
```

To discard the result: `git branch -D lambda-migration-<timestamp>`.
To accept it, review it and merge it yourself. The agent will never merge.

## Demo script (about 4 minutes)

1. **Problem:** moving an EC2 app to Lambda takes 1–2 hours of manual analysis and rewriting.
2. **Run on `sample_app`:** show the agent reading files, picking tools, validating. Verdict: `migrate`.
3. **Show the result:** `git diff --stat`, open `lambda_function.py`, `template.yaml`, `MIGRATION_REPORT.md`.
4. **Run on `sample_bad_app`:** the agent refuses to blindly convert and explains why (background thread, local state).
5. **Close:** guardrails (no push, no deploy, human review) and the time saved.

## Limitations

- Best on small Python Flask/FastAPI apps. Other languages and large codebases are not supported yet.
- Output is a **draft for human review**, not production-ready. IAM roles, secrets, VPC, and state migration need manual work.
- The cost comparison is a rough estimate.
- Quality depends on the chosen Groq model. Free-tier rate limits can slow runs down.
- `sam validate` is skipped if the SAM CLI is not installed.

## Roadmap

- Node.js / Express support
- Second agent: Dockerfile and CI/CD generator, using the same branch-and-commit safety model
- Streamlit UI with a diff viewer
- Cost estimate from a fixed pricing table instead of model estimates
