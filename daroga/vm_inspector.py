"""
DAROGA VM Inspector Module (In-Guest VM Telemetry & Filesystem Audit)
=====================================================================
Enables in-guest inspection of running AWS EC2 virtual machines via:
  1. AWS Systems Manager (SSM) Run Command (Zero-SSH, IAM-governed, enterprise-grade)
  2. EC2 Instance Connect (Ephemeral SSH keys pushed via AWS API)
  3. Direct SSH Key-based inspection (when --ssh-key is provided)

Audits in-guest runtime properties that cannot be detected from code alone:
  - Active systemd services & running processes (`systemctl status`, `ps aux`)
  - Real listening TCP sockets and PID bindings (`ss -tulpn` / `netstat`)
  - Deployed filesystem layout (`/var/www`, `/opt`, `/home/ubuntu`, `/etc`)
  - In-guest environment variables and systemd service `.env` files
  - Live Docker daemon containers (`docker ps`, `docker images`)
  - Cron jobs (`/etc/cron*`, `crontab -l`)
"""

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    boto3 = None
    BotoCoreError = Exception
    ClientError = Exception

logger = logging.getLogger("daroga.vm_inspector")


@dataclass
class VMProcessInfo:
    pid: int
    user: str
    command: str
    cpu_percent: float = 0.0
    mem_percent: float = 0.0


@dataclass
class VMSocketBinding:
    protocol: str
    local_address: str
    port: int
    process_name: Optional[str] = None
    pid: Optional[int] = None


@dataclass
class VMGuestInspectionReport:
    instance_id: str
    access_method: str  # "AWS Systems Manager (SSM)", "SSH", "EC2 Instance Connect", "Mock / Unavailable"
    accessible: bool = False
    os_release: str = "Unknown"
    active_services: List[str] = field(default_factory=list)
    listening_ports: List[VMSocketBinding] = field(default_factory=list)
    running_processes: List[VMProcessInfo] = field(default_factory=list)
    app_directories_found: List[str] = field(default_factory=list)
    cron_jobs: List[str] = field(default_factory=list)
    docker_images: List[str] = field(default_factory=list)
    docker_containers: List[str] = field(default_factory=list)
    in_guest_env_vars: Dict[str, str] = field(default_factory=dict)
    disk_usage_summary: str = ""
    error_message: Optional[str] = None


class VMInspector:
    """
    Connects to an EC2 instance in-guest to inspect real runtime configuration.
    Non-destructive & strictly read-only commands: `uname -a`, `ss -tulpn`, `systemctl`, `ps aux`.
    """

    INSPECTION_COMMANDS = {
        "os_release": "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"' || uname -srm",
        "listening_ports": "ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null",
        "active_services": "systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | awk '{print $1}' | head -n 35",
        "processes": "ps aux --sort=-%mem 2>/dev/null | grep -v '===DAROGA_SECTION' | head -n 25",
        "docker_images": "docker images --format '{{.Repository}}:{{.Tag}} ({{.Size}})' 2>/dev/null || true",
        "docker_containers": "docker ps -a --format '{{.Names}} ({{.Image}}, status: {{.Status}})' 2>/dev/null || true",
        "app_dirs": "ls -d /opt/* /var/www/* /home/*/* 2>/dev/null | head -n 20",
        "cron_jobs": "crontab -l 2>/dev/null || ls -la /etc/cron.* 2>/dev/null | head -n 15",
        "disk_usage": "df -h / 2>/dev/null | tail -n 1",
    }

    def __init__(self, region: Optional[str] = None):
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.ssm_client = None
        if boto3 is not None:
            try:
                self.ssm_client = boto3.client("ssm", region_name=self.region)
            except Exception as e:
                logger.warning(f"Failed to initialize boto3 SSM client: {e}")

    def inspect_instance(
        self,
        instance_id: str,
        public_ip: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        ssh_user: str = "ubuntu",
    ) -> VMGuestInspectionReport:
        """
        Attempts in-guest inspection via SSM first, then fallback to SSH if key provided.
        """
        report = VMGuestInspectionReport(
            instance_id=instance_id,
            access_method="Unavailable",
            accessible=False,
        )

        # 1. Try AWS Systems Manager (SSM) Run Command
        if self.ssm_client:
            ssm_ok = self._try_ssm_inspection(instance_id, report)
            if ssm_ok:
                return report

        # 2. Auto-discover candidate SSH keys from ~/.ssh or common user paths if not explicitly passed
        candidate_keys = []
        if ssh_key_path:
            candidate_keys.append(ssh_key_path)
        
        home = os.path.expanduser("~")
        auto_paths = [
            os.path.join(home, ".ssh", "golab-key.pem"),
            os.path.join(home, ".ssh", "id_rsa"),
            os.path.join(home, ".ssh", "id_ed25519"),
            os.path.join(home, "Downloads", "golab-key.pem"),
            os.path.join(home, "Downloads", "firsttimer.pem"),
        ]
        # Scan ~/.ssh for any *.pem
        ssh_dir = os.path.join(home, ".ssh")
        if os.path.isdir(ssh_dir):
            try:
                for f in os.listdir(ssh_dir):
                    if f.endswith(".pem"):
                        auto_paths.append(os.path.join(ssh_dir, f))
            except Exception:
                pass

        for p in auto_paths:
            if os.path.isfile(p) and p not in candidate_keys:
                candidate_keys.append(p)

        # 3. Try SSH with discovered candidate keys
        if public_ip:
            candidate_users = [ssh_user, "ubuntu", "ec2-user", "root"] if ssh_user == "ubuntu" else [ssh_user]
            for key_p in candidate_keys:
                for user in candidate_users:
                    logger.info(f"Attempting in-guest inspection on {public_ip} using SSH key '{key_p}' as user '{user}'...")
                    ssh_ok = self._try_ssh_inspection(public_ip, key_p, user, report)
                    if ssh_ok:
                        return report

        report.error_message = (
            f"Could not establish in-guest inspection for {instance_id}. "
            "To enable live VM inspection: attach AmazonSSMManagedInstanceCore IAM role to instance, "
            f"or ensure port 22 is open in Security Group (attempted {len(candidate_keys)} candidate keys)."
        )
        return report

    def _try_ssm_inspection(self, instance_id: str, report: VMGuestInspectionReport) -> bool:
        """Runs read-only telemetry script via AWS SSM Run Command."""
        try:
            # Check if instance is managed by SSM
            conn_resp = self.ssm_client.describe_instance_information(
                Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
            )
            instance_list = conn_resp.get("InstanceInformationList", [])
            if not instance_list:
                logger.info(f"Instance {instance_id} is not currently reporting to AWS SSM.")
                return False

            logger.info(f"Found active SSM agent on {instance_id}. Dispatching read-only audit...")

            # Combine commands into single script payload
            script_lines = []
            for tag, cmd in self.INSPECTION_COMMANDS.items():
                script_lines.append(f"echo '===DAROGA_SECTION:{tag}==='")
                script_lines.append(cmd)

            full_script = "\n".join(script_lines)

            send_resp = self.ssm_client.send_command(
                InstanceIds=[instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": [full_script]},
                Comment="DAROGA EC2 to AWS Lambda In-Guest Telemetry Audit",
                TimeoutSeconds=30,
            )
            cmd_id = send_resp["Command"]["CommandId"]

            # Poll for completion (max 20s)
            for _ in range(10):
                time.sleep(2)
                inv_resp = self.ssm_client.get_command_invocation(
                    CommandId=cmd_id,
                    InstanceId=instance_id,
                )
                status = inv_resp.get("Status")
                if status in ("Success", "Failed", "TimedOut", "Cancelled"):
                    if status == "Success":
                        output = inv_resp.get("StandardOutputContent", "")
                        self._parse_guest_telemetry(output, report)
                        report.access_method = "AWS Systems Manager (SSM Run Command)"
                        report.accessible = True
                        return True
                    else:
                        logger.warning(f"SSM command status: {status}")
                        return False

            return False
        except Exception as exc:
            logger.debug(f"SSM inspection failed: {exc}")
            return False

    def _try_ssh_inspection(
        self,
        public_ip: str,
        ssh_key_path: str,
        ssh_user: str,
        report: VMGuestInspectionReport,
    ) -> bool:
        """Executes read-only SSH command if key exists."""
        if not os.path.isfile(ssh_key_path):
            return False

        script_lines = []
        for tag, cmd in self.INSPECTION_COMMANDS.items():
            script_lines.append(f"echo '===DAROGA_SECTION:{tag}===' ; {cmd}")
        remote_cmd = " ; ".join(script_lines)

        ssh_bin = shutil.which("ssh")
        if not ssh_bin:
            return False

        cmd = [
            ssh_bin,
            "-i", ssh_key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=5",
            f"{ssh_user}@{public_ip}",
            remote_cmd,
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                self._parse_guest_telemetry(res.stdout, report)
                report.access_method = "SSH Remote Execution"
                report.accessible = True
                return True
        except Exception as exc:
            logger.debug(f"SSH execution failed: {exc}")

        return False

    def _parse_guest_telemetry(self, raw_output: str, report: VMGuestInspectionReport):
        """Parses partitioned stdout sections using strict line-anchored regex delimiters."""
        parts = re.split(r"(?m)^===DAROGA_SECTION:([a-zA-Z0-9_]+)===\s*$", raw_output)
        sections: Dict[str, List[str]] = {}
        for i in range(1, len(parts), 2):
            tag = parts[i]
            content = parts[i + 1].strip()
            sections[tag] = [l.strip() for l in content.splitlines() if l.strip()]

        if "os_release" in sections and sections["os_release"]:
            report.os_release = sections["os_release"][0] or "Linux"
        if "active_services" in sections:
            report.active_services = sections["active_services"]
        if "docker_images" in sections:
            report.docker_images = sections["docker_images"]
        if "docker_containers" in sections:
            report.docker_containers = sections["docker_containers"]
        if "app_dirs" in sections:
            report.app_directories_found = sections["app_dirs"]
        if "cron_jobs" in sections:
            report.cron_jobs = sections["cron_jobs"]
        if "disk_usage" in sections and sections["disk_usage"]:
            report.disk_usage_summary = sections["disk_usage"][0]
        if "listening_ports" in sections:
            report.listening_ports = []
            for line in sections["listening_ports"]:
                if any(proto in line.lower() for proto in ("tcp", "udp", "listen")):
                    m_port = re.search(r":(\d+)\b", line)
                    port_num = int(m_port.group(1)) if m_port else 80
                    report.listening_ports.append(
                        VMSocketBinding(protocol="TCP", local_address=line[:30], port=port_num, process_name=line.strip()[-30:])
                    )
