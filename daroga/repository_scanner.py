"""
DAROGA Repository Scanner Module
================================
Inspects an existing application repository deterministically without modifying source files.
Detects programming languages, frameworks, entrypoints, exposed ports, dependencies,
and stateful application behaviors (WebSockets, local disk persistence, background workers).
"""

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class RepoInspectionResult:
    repo_name: str
    repo_path: str
    primary_language: str
    languages: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    entrypoints: List[str] = field(default_factory=list)
    exposed_ports: List[int] = field(default_factory=list)
    package_managers: List[str] = field(default_factory=list)
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    dockerfiles: List[str] = field(default_factory=list)
    docker_compose_files: List[str] = field(default_factory=list)
    nginx_configs: List[str] = field(default_factory=list)
    cicd_configs: List[str] = field(default_factory=list)
    env_files: List[str] = field(default_factory=list)
    has_websockets: bool = False
    websocket_evidence: List[str] = field(default_factory=list)
    has_background_workers: bool = False
    worker_evidence: List[str] = field(default_factory=list)
    has_local_storage: bool = False
    storage_evidence: List[str] = field(default_factory=list)
    has_scheduled_jobs: bool = False
    job_evidence: List[str] = field(default_factory=list)
    database_types: List[str] = field(default_factory=list)
    database_evidence: List[str] = field(default_factory=list)
    has_docker_execution: bool = False
    docker_exec_evidence: List[str] = field(default_factory=list)
    total_files_scanned: int = 0
    directory_structure: Dict[str, Any] = field(default_factory=dict)
    backend_directory: Optional[str] = None


class RepositoryScanner:
    """
    Deterministic static analysis engine for application repositories.
    Operates strictly read-only.
    """

    IGNORED_DIRS = {
        ".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode",
        "dist", "build", ".next", ".turbo", "coverage", "static", "public", "assets",
        "images", "fonts", "vendor"
    }

    IGNORED_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".lock", ".map",
        ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".pdf", ".zip"
    }

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path.resolve()
        if not self.repo_path.is_dir():
            raise FileNotFoundError(f"Repository directory does not exist: {self.repo_path}")

    def scan(self) -> RepoInspectionResult:
        result = RepoInspectionResult(
            repo_name=self.repo_path.name,
            repo_path=str(self.repo_path),
            primary_language="unknown",
        )

        # 1. Discover all candidate files
        candidate_files: List[Path] = []
        for p in self.repo_path.rglob("*"):
            if not p.is_file():
                continue
            if any(part in self.IGNORED_DIRS for part in p.parts):
                continue
            if p.suffix.lower() in self.IGNORED_EXTENSIONS:
                continue
            candidate_files.append(p)

        result.total_files_scanned = len(candidate_files)

        # 2. Check for Monorepo (frontend / backend separation)
        if (self.repo_path / "backend").is_dir():
            result.backend_directory = "backend"
        elif (self.repo_path / "server").is_dir():
            result.backend_directory = "server"
        elif (self.repo_path / "api").is_dir():
            result.backend_directory = "api"

        # 3. Detect Languages & Package Managers
        lang_scores: Dict[str, int] = {"go": 0, "python": 0, "javascript": 0, "typescript": 0, "java": 0, "rust": 0}
        
        for p in candidate_files:
            rel = p.relative_to(self.repo_path).as_posix()
            name_lower = p.name.lower()
            ext = p.suffix.lower()

            # Infrastructure & Configs
            if "dockerfile" in name_lower:
                result.dockerfiles.append(rel)
                if any(x in name_lower for x in ("compiler", "runtime", "sandbox", "runner", "judge")):
                    result.has_docker_execution = True
                    result.docker_exec_evidence.append(f"Dedicated container runner image definition: {rel}")
            if "docker-compose" in name_lower and ext in (".yml", ".yaml"):
                result.docker_compose_files.append(rel)
            if "nginx" in name_lower and (ext == ".conf" or "nginx" in rel):
                result.nginx_configs.append(rel)
            if ".github/workflows" in rel or ".gitlab-ci.yml" in rel or "jenkinsfile" in name_lower:
                result.cicd_configs.append(rel)
            if name_lower.startswith(".env") and not name_lower.endswith(".example"):
                result.env_files.append(rel)

            # Languages & Manifests
            if p.name == "go.mod" or ext == ".go":
                lang_scores["go"] += 5 if p.name == "go.mod" else 1
                if "go.mod" not in result.package_managers and p.name == "go.mod":
                    result.package_managers.append("go.mod")
            elif p.name in ("requirements.txt", "pyproject.toml", "Pipfile") or ext == ".py":
                lang_scores["python"] += 5 if p.name in ("requirements.txt", "pyproject.toml", "Pipfile") else 1
                if p.name not in result.package_managers and p.name in ("requirements.txt", "pyproject.toml", "Pipfile"):
                    result.package_managers.append(p.name)
            elif p.name == "package.json" or ext in (".js", ".jsx", ".mjs", ".cjs"):
                lang_scores["javascript"] += 5 if p.name == "package.json" else 1
                if "npm/yarn/pnpm" not in result.package_managers and p.name == "package.json":
                    result.package_managers.append("package.json")
            elif ext in (".ts", ".tsx"):
                lang_scores["typescript"] += 1
            elif p.name in ("pom.xml", "build.gradle") or ext in (".java", ".kt"):
                lang_scores["java"] += 5 if p.name in ("pom.xml", "build.gradle") else 1
                if p.name not in result.package_managers and p.name in ("pom.xml", "build.gradle"):
                    result.package_managers.append(p.name)
            elif p.name == "Cargo.toml" or ext == ".rs":
                lang_scores["rust"] += 5 if p.name == "Cargo.toml" else 1
                if "cargo" not in result.package_managers and p.name == "Cargo.toml":
                    result.package_managers.append("Cargo.toml")

        # Determine Primary Language
        sorted_langs = sorted([k for k, v in lang_scores.items() if v > 0], key=lambda k: lang_scores[k], reverse=True)
        result.languages = sorted_langs
        if sorted_langs:
            result.primary_language = sorted_langs[0]

        # 4. Deep Inspection of Manifests & Dependencies
        self._inspect_manifests(result)

        # 5. Locate Entrypoints and Exposed Ports
        self._locate_entrypoints_and_ports(candidate_files, result)

        # 6. Deep AST & Heuristic Pattern Inspection of Source Code
        self._inspect_code_behavior(candidate_files, result)

        return result

    def _inspect_manifests(self, result: RepoInspectionResult):
        # Go manifests
        for go_mod in self.repo_path.rglob("go.mod"):
            try:
                content = go_mod.read_text(encoding="utf-8", errors="ignore")
                deps = []
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("//") and not line.startswith("module") and not line.startswith("go "):
                        pkg = line.split()[0]
                        deps.append(pkg)
                result.dependencies["go"] = deps

                # Frameworks
                if any("gin-gonic/gin" in d for d in deps):
                    result.frameworks.append("Gin (Go)")
                if any("gofiber/fiber" in d for d in deps):
                    result.frameworks.append("Fiber (Go)")
                if any("labstack/echo" in d for d in deps):
                    result.frameworks.append("Echo (Go)")
                if any("gorilla/mux" in d for d in deps):
                    result.frameworks.append("Gorilla Mux (Go)")
                if any("docker/docker/client" in d for d in deps):
                    result.has_docker_execution = True
                    result.docker_exec_evidence.append(f"Docker client SDK dependency in {go_mod.relative_to(self.repo_path)}")
            except Exception:
                pass

        # Python manifests
        for req_txt in self.repo_path.rglob("requirements*.txt"):
            try:
                content = req_txt.read_text(encoding="utf-8", errors="ignore")
                deps = [line.strip().split("==")[0].split(">=")[0] for line in content.splitlines() if line.strip() and not line.startswith("#")]
                result.dependencies["python"] = deps

                if any(x in deps for x in ("flask", "Flask")):
                    result.frameworks.append("Flask (Python)")
                if any(x in deps for x in ("fastapi", "FastAPI")):
                    result.frameworks.append("FastAPI (Python)")
                if any(x in deps for x in ("django", "Django")):
                    result.frameworks.append("Django (Python)")
            except Exception:
                pass

        # Node manifests
        for pkg_json in self.repo_path.rglob("package.json"):
            if "node_modules" in pkg_json.parts:
                continue
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                all_deps = list(data.get("dependencies", {}).keys()) + list(data.get("devDependencies", {}).keys())
                result.dependencies["node"] = all_deps

                if "express" in all_deps:
                    result.frameworks.append("Express (Node.js)")
                if "fastify" in all_deps:
                    result.frameworks.append("Fastify (Node.js)")
                if "next" in all_deps:
                    result.frameworks.append("Next.js (React)")
                if "socket.io" in all_deps or "ws" in all_deps:
                    result.has_websockets = True
                    result.websocket_evidence.append(f"WebSocket client/server package in {pkg_json.relative_to(self.repo_path)}")
            except Exception:
                pass

    def _locate_entrypoints_and_ports(self, files: List[Path], result: RepoInspectionResult):
        port_pattern = re.compile(r'(?:Listen\([":\s]*(\d{2,5})|port\s*=\s*(\d{2,5})|listen\s+(\d{2,5})|PORT\s*=\s*(\d{2,5})|:(\d{4,5}))', re.IGNORECASE)
        common_entry_names = {
            "main.go", "app.py", "main.py", "server.py", "wsgi.py", "asgi.py",
            "server.js", "index.js", "app.js", "main.js", "server.ts", "index.ts"
        }

        for p in files:
            rel = p.relative_to(self.repo_path).as_posix()
            if p.name in common_entry_names or rel.endswith("/main.go") or rel.endswith("/app.py"):
                result.entrypoints.append(rel)

            # Check port mentions in entrypoints, configs, Dockerfiles
            if p.suffix in (".go", ".py", ".js", ".ts", ".conf") or "dockerfile" in p.name.lower():
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                    matches = port_pattern.findall(txt)
                    for groups in matches:
                        for g in groups:
                            if g:
                                port_num = int(g)
                                if 1000 <= port_num <= 65535 and port_num not in (2026, 2025, 2024):
                                    if port_num not in result.exposed_ports:
                                        result.exposed_ports.append(port_num)
                except Exception:
                    pass

    def _inspect_code_behavior(self, files: List[Path], result: RepoInspectionResult):
        for p in files:
            if p.suffix not in (".go", ".py", ".js", ".ts"):
                continue
            rel = p.relative_to(self.repo_path).as_posix()
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            # 1. Docker execution
            if any(k in txt for k in (
                'exec.Command("docker"', "exec.Command('docker'", "docker run",
                "/var/run/docker.sock", "subprocess.run(['docker'", "docker.from_env()"
            )):
                result.has_docker_execution = True
                result.docker_exec_evidence.append(f"Docker invocation detected in {rel}")

            # 2. WebSockets
            if any(k in txt for k in ("gorilla/websocket", "socket.io", "WebSocketServer", "websockets.serve")):
                result.has_websockets = True
                result.websocket_evidence.append(f"WebSocket listener detected in {rel}")

            # 3. Local Storage / Filesystem
            if any(k in txt for k in ("sqlite3", "sqlite.Open", "import sqlite3", "os.Create", "open(", "fs.writeFileSync")):
                if "sqlite" in txt.lower():
                    result.has_local_storage = True
                    result.storage_evidence.append(f"Embedded SQLite database detected in {rel}")
                    if "SQLite" not in result.database_types:
                        result.database_types.append("SQLite")

            # 4. Background workers & Scheduled Jobs
            if any(k in txt for k in ("robfig/cron", "APScheduler", "celery", "time.Tick", "cron.New", "schedule.every")):
                result.has_scheduled_jobs = True
                result.job_evidence.append(f"Scheduled task loop detected in {rel}")

            # 5. Database types
            if any(k in txt for k in ("postgres", "pq", "pgx", "psycopg2", "postgresql")):
                if "PostgreSQL" not in result.database_types:
                    result.database_types.append("PostgreSQL")
                    result.database_evidence.append(f"PostgreSQL driver detected in {rel}")
            if any(k in txt for k in ("mysql", "go-sql-driver/mysql", "pymysql")):
                if "MySQL" not in result.database_types:
                    result.database_types.append("MySQL")
                    result.database_evidence.append(f"MySQL driver detected in {rel}")
            if any(k in txt for k in ("redis", "go-redis", "redis.Client")):
                if "Redis" not in result.database_types:
                    result.database_types.append("Redis")
                    result.database_evidence.append(f"Redis cache detected in {rel}")
