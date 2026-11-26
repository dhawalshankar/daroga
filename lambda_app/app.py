import os
from flask import Flask, jsonify, request

app = Flask(__name__)

# Sample in-memory database representing an EC2-hosted service
TASKS = [
    {"id": 1, "title": "Setup EC2 instance and security groups", "status": "completed"},
    {"id": 2, "title": "Configure Nginx reverse proxy and SSL", "status": "completed"},
    {"id": 3, "title": "Migrate workload to AWS Lambda serverless", "status": "completed"},
]


@app.get("/health")
def health():
    return jsonify(
        status="healthy",
        compute="AWS Lambda",
        architecture="serverless",
    )


@app.get("/tasks")
def list_tasks():
    return jsonify(tasks=TASKS, total=len(TASKS))


@app.post("/tasks")
def create_task():
    payload = request.get_json(force=True) or {}
    new_task = {
        "id": len(TASKS) + 1,
        "title": payload.get("title", "Untitled Task"),
        "status": payload.get("status", "pending"),
    }
    TASKS.append(new_task)
    return jsonify(new_task), 201


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
