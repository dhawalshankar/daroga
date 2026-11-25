# Product Requirements Document: Cloud Admin Agents

| | |
|---|---|
| **Author** | Cloud Administrator Intern candidate |
| **Status** | Draft v1 |
| **Demo date** | 2 December 2026 (live demo to panel) |
| **Platform** | Python, Groq API (LLM with tool calling), git |

## 1. Summary

Cloud administrators spend a lot of time on repetitive, rule-based work. This project delivers two AI
agents that make that work faster. Each agent reads, decides, acts through a small set of controlled tools,
checks its own output, and reports. Both are built on an existing LLM (Groq). No model is trained.

- **Agent 1: EC2 → Lambda Migration Agent** (specified in detail here)
- **Agent 2: Dockerfile and CI/CD Generator** (proposed, same safety model, to be confirmed)

## 2. Problem

Moving an app from EC2 to Lambda requires an admin to read the code, judge whether it fits serverless
(stateless, under 15 minutes, no background threads, package size), rewrite the entry point, write a SAM
or Terraform template, and document the result. Doing this by hand is slow and error-prone, and a wrong
"yes" wastes days. Automated tools that act directly on the cloud are risky for a junior admin.

## 3. Goals and non-goals

**Goals**
- G1. Produce a correct, reviewable first draft of a Lambda migration in minutes.
- G2. Give an honest verdict, including "do not migrate", with reasons.
- G3. Be safe by design: nothing leaves the local machine, a human reviews everything.
- G4. Show real agent behaviour (tool choice, self-validation, retry), not a single prompt.

**Non-goals**
- Training or fine-tuning a model.
- Deploying to AWS, pushing to remotes, or merging branches.
- Supporting every language and framework (v1 is Python Flask/FastAPI).
- Guaranteeing production-ready output.

## 4. Users

- **Primary:** cloud administrator or intern who must assess and prepare migrations.
- **Secondary:** a senior reviewer who reads the branch diff and the migration report.

## 5. User stories

1. As an admin, I point the agent at a repo and get a verdict on Lambda suitability with reasons.
2. As an admin, I get Lambda code and a SAM template on a separate branch, so my main branch is untouched.
3. As an admin, I get a report listing what still needs manual work (IAM, env vars, secrets, state).
4. As a reviewer, I can run `git diff` and see exactly what the agent changed.
5. As a team lead, I am confident the agent cannot deploy, push, or spend money.

## 6. Functional requirements: Agent 1

| ID | Requirement | Priority |
|---|---|---|
| F1 | Accept a local repo path and verify it is a git repo with a clean working tree | Must |
| F2 | Analyze framework, routes, threads, local file/DB use, long-running work, dependencies | Must |
| F3 | Return verdict `migrate` / `partial` / `do_not_migrate` with reasons | Must |
| F4 | Create a new local branch `lambda-migration-<timestamp>` | Must |
| F5 | Generate `lambda_function.py`, updated `requirements.txt`, `template.yaml` (SAM) | Must |
| F6 | Validate output with `py_compile` and `sam validate` (if installed); fix errors and retry | Must |
| F7 | Write `MIGRATION_REPORT.md` (verdict, changes, manual steps, rough cost note) | Must |
| F8 | Commit on the new branch only, then return to the original branch | Must |
| F9 | If verdict is `do_not_migrate`, write only the report | Must |
| F10 | Handle API rate limits and malformed tool calls without crashing | Should |
| F11 | Streamlit UI with diff viewer | Could |
| F12 | Node.js / Express support | Could |

## 7. Safety requirements

| ID | Requirement |
|---|---|
| S1 | No push, merge, or deploy capability exists in the agent's toolset |
| S2 | No AWS or network calls; commands are limited to an allowlist and run without a shell |
| S3 | File access is limited to the target repo; `.git` is not writable |
| S4 | Original branch is never modified |
| S5 | Agent refuses to run on a dirty working tree |
| S6 | Max 30 agent turns per run |

## 8. How it works

```
User ──► agent.py ──► git: create branch
              │
              ▼
        Agent loop (Groq LLM + tools)
        list_files → read_file → write_file → run_command → (fix) → finish
              │
              ▼
        git: add + commit on branch ──► checkout original branch
              │
              ▼
        Summary: verdict + `git diff` command to review
```

## 9. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.10+ | Simple, readable, good for tooling |
| LLM | Groq API (default `openai/gpt-oss-120b`, configurable) | Very fast inference, supports tool calling |
| Version control | git via subprocess | Safe, reviewable output |
| Validation | `py_compile`, AWS SAM CLI (`sam validate`) | Deterministic checks of the generated code |
| Target runtime | AWS Lambda + API Gateway (SAM) | The migration being automated |

## 10. Success metrics

Measure these before the demo and report the real numbers.

| Metric | Target | How measured |
|---|---|---|
| Time to a reviewable draft | Minutes vs. hours manually | Stopwatch: manual vs. agent on `sample_app` |
| Verdict correctness | Correct on both sample apps | `sample_app` → migrate; `sample_bad_app` → do_not_migrate/partial |
| Validation pass rate | Generated code passes `py_compile` | Count over several runs |
| Safety | 0 pushes, 0 cloud calls, 0 edits to original branch | Verified by `git branch`, `git log`, no remotes |

## 11. Demo plan (about 4 minutes per agent)

1. Problem in one sentence.
2. Live run on `sample_app`, then show the branch diff and report.
3. Live run on `sample_bad_app` to show the agent says no.
4. Tools used and why Groq.
5. Time saved: manual vs. agent (use measured numbers).

Backup: a recorded successful run and pre-generated branches, in case of network or API failure.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Groq API down or rate-limited during demo | Built-in retry; pre-recorded run; a pre-generated branch to show |
| Model produces malformed tool calls | Auto-retry (3x) with a corrective message; test several runs beforehand |
| Model ID removed or renamed | `GROQ_MODEL` env var; check Groq's model list before the demo |
| Output looks correct but is wrong | Validation step plus mandatory human review; report lists manual steps |
| Over-claiming generality | State scope clearly: small Python Flask/FastAPI apps |

## 13. Agent 2 (proposed, to be confirmed): Dockerfile and CI/CD Generator

Same model: read the repo, create a local branch, write `Dockerfile`, `.dockerignore`, and a GitHub Actions
workflow, validate (for example, YAML lint and `docker build` if Docker is available), write a report, commit locally.
Reuses the guardrails and git flow from Agent 1. Requirements will be detailed once the agent is confirmed.

## 14. Timeline

| Day | Work |
|---|---|
| 1 | Finalize scope, prepare sample repos, run Agent 1 end to end on Groq |
| 2 | Tune prompts, fix failures, install SAM CLI, measure time saved |
| 3 | Build Agent 2 on the same structure |
| 4 | Test both agents repeatedly, handle edge cases, record backup videos |
| 5 | Rehearse the demo, prepare answers on limitations and scaling |

## 15. Open questions

- Which Groq model gives the most reliable tool calling on the day? (Test 2–3 models.)
- Is Agent 2 the Dockerfile/CI-CD generator, or another cloud admin task?
- Will the panel want a UI, or is a terminal demo with a branch diff enough?
