"""
DAROGA EC2 & AWS Infrastructure Inspector Module
================================================
Inspects actual AWS infrastructure using boto3 and the AWS CLI with strictly read-only calls.
Discovers caller identity, EC2 instances, EBS storage, VPCs, subnets, security groups,
load balancers, and attached IAM instance profiles.
"""

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    boto3 = None
    BotoCoreError = Exception
    ClientError = Exception

logger = logging.getLogger("daroga.ec2_inspector")


@dataclass
class AWSIdentity:
    account_id: Optional[str] = None
    arn: Optional[str] = None
    user_id: Optional[str] = None
    region: Optional[str] = None
    configured: bool = False
    error: Optional[str] = None


@dataclass
class EC2InstanceDetail:
    instance_id: str
    instance_type: str
    state: str
    ami_id: str
    platform_or_os: str
    launch_time: str
    vpc_id: Optional[str] = None
    subnet_id: Optional[str] = None
    private_ip: Optional[str] = None
    public_ip: Optional[str] = None
    security_group_ids: List[str] = field(default_factory=list)
    ebs_volume_ids: List[str] = field(default_factory=list)
    iam_instance_profile: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class SecurityGroupRule:
    direction: str  # inbound / outbound
    protocol: str
    from_port: Optional[int]
    to_port: Optional[int]
    cidr: Optional[str]
    description: Optional[str] = None


@dataclass
class SecurityGroupDetail:
    group_id: str
    group_name: str
    vpc_id: str
    description: str
    rules: List[SecurityGroupRule] = field(default_factory=list)


@dataclass
class AWSInfrastructureReport:
    identity: AWSIdentity = field(default_factory=AWSIdentity)
    instances: List[EC2InstanceDetail] = field(default_factory=list)
    security_groups: List[SecurityGroupDetail] = field(default_factory=list)
    vpcs: List[Dict[str, Any]] = field(default_factory=list)
    subnets: List[Dict[str, Any]] = field(default_factory=list)
    load_balancers: List[Dict[str, Any]] = field(default_factory=list)
    iam_roles: List[Dict[str, Any]] = field(default_factory=list)
    related_services: Dict[str, Any] = field(default_factory=dict)
    inspection_successful: bool = False
    errors_or_notes: List[str] = field(default_factory=list)


class EC2Inspector:
    """
    Read-only inspector for live AWS Cloud environments.
    Combines boto3 with AWS CLI fallbacks.
    """

    def __init__(self, region_name: Optional[str] = None, instance_id: Optional[str] = None):
        self.region_name = region_name or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        self.target_instance_id = instance_id
        self._init_clients()

    def _init_clients(self):
        self.boto_available = boto3 is not None
        if self.boto_available:
            try:
                self.session = boto3.Session(region_name=self.region_name)
                self.sts = self.session.client("sts")
                self.ec2 = self.session.client("ec2")
                self.iam = self.session.client("iam")
            except Exception as e:
                logger.warning(f"Failed to initialize boto3 session: {e}")
                self.boto_available = False

    def inspect_caller_identity(self) -> AWSIdentity:
        ident = AWSIdentity(region=self.region_name)
        if self.boto_available:
            try:
                resp = self.sts.get_caller_identity()
                ident.account_id = resp.get("Account")
                ident.arn = resp.get("Arn")
                ident.user_id = resp.get("UserId")
                ident.configured = True
                return ident
            except Exception as e:
                ident.error = str(e)

        # CLI fallback
        if shutil.which("aws"):
            try:
                proc = subprocess.run(
                    ["aws", "sts", "get-caller-identity", "--output", "json"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    ident.account_id = data.get("Account")
                    ident.arn = data.get("Arn")
                    ident.user_id = data.get("UserId")
                    ident.configured = True
                    ident.error = None
                    return ident
                else:
                    ident.error = proc.stderr.strip()
            except Exception as e:
                ident.error = str(e)

        if not ident.configured:
            ident.error = ident.error or "AWS credentials not configured in environment or ~/.aws/credentials"
        return ident

    CANDIDATE_REGIONS = [
        "ap-southeast-2", "us-east-1", "us-east-2", "us-west-2",
        "ap-south-1", "eu-west-1", "eu-central-1", "ap-southeast-1"
    ]

    def inspect_all(self) -> AWSInfrastructureReport:
        report = AWSInfrastructureReport()
        report.identity = self.inspect_caller_identity()

        if not report.identity.configured:
            report.errors_or_notes.append(f"AWS identity unverified: {report.identity.error}. Skipping live API calls.")
            return report

        # 1. EC2 Instances (with multi-region auto-discovery if 0 instances found in current region)
        self._inspect_ec2_instances(report)

        if not report.instances and not self.target_instance_id:
            # Multi-region auto-scan to find instances running in other regions
            other_regions = [r for r in self.CANDIDATE_REGIONS if r != self.region_name]
            for reg in other_regions:
                temp_report = AWSInfrastructureReport()
                self._query_region_instances(reg, temp_report)
                if temp_report.instances:
                    logger.info(f"Auto-discovered {len(temp_report.instances)} instance(s) in region '{reg}'. Switching active region to '{reg}'.")
                    self.region_name = reg
                    self._init_clients()
                    report.identity.region = reg
                    report.instances = temp_report.instances
                    break

        # 2. VPCs & Subnets
        self._inspect_networking(report)

        # 3. Security Groups
        self._inspect_security_groups(report)

        # 4. IAM Roles for EC2
        self._inspect_iam(report)

        report.inspection_successful = len(report.instances) > 0 or len(report.security_groups) > 0
        return report

    def _query_region_instances(self, region: str, report: AWSInfrastructureReport):
        if self.boto_available:
            try:
                client = boto3.client("ec2", region_name=region)
                resp = client.describe_instances()
                for res in resp.get("Reservations", []):
                    for inst in res.get("Instances", []):
                        if inst.get("State", {}).get("Name") == "running" or not report.instances:
                            report.instances.append(EC2InstanceDetail(
                                instance_id=inst.get("InstanceId", ""),
                                instance_type=inst.get("InstanceType", ""),
                                state=inst.get("State", {}).get("Name", "unknown"),
                                ami_id=inst.get("ImageId", ""),
                                platform_or_os=inst.get("PlatformDetails", "Linux/UNIX"),
                                launch_time=str(inst.get("LaunchTime", "")),
                                vpc_id=inst.get("VpcId"),
                                subnet_id=inst.get("SubnetId"),
                                private_ip=inst.get("PrivateIpAddress"),
                                public_ip=inst.get("PublicIpAddress"),
                                security_group_ids=[sg.get("GroupId") for sg in inst.get("SecurityGroups", [])],
                                ebs_volume_ids=[bdm.get("Ebs", {}).get("VolumeId") for bdm in inst.get("BlockDeviceMappings", []) if bdm.get("Ebs")],
                                iam_instance_profile=inst.get("IamInstanceProfile", {}).get("Arn"),
                                tags={t.get("Key"): t.get("Value") for t in inst.get("Tags", [])},
                            ))
                if report.instances:
                    return
            except Exception:
                pass

        if shutil.which("aws"):
            try:
                cmd = ["aws", "ec2", "describe-instances", "--region", region, "--output", "json"]
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    for res in data.get("Reservations", []):
                        for inst in res.get("Instances", []):
                            report.instances.append(EC2InstanceDetail(
                                instance_id=inst.get("InstanceId", ""),
                                instance_type=inst.get("InstanceType", ""),
                                state=inst.get("State", {}).get("Name", "unknown"),
                                ami_id=inst.get("ImageId", ""),
                                platform_or_os=inst.get("PlatformDetails", "Linux/UNIX"),
                                launch_time=str(inst.get("LaunchTime", "")),
                                vpc_id=inst.get("VpcId"),
                                subnet_id=inst.get("SubnetId"),
                                private_ip=inst.get("PrivateIpAddress"),
                                public_ip=inst.get("PublicIpAddress"),
                                security_group_ids=[sg.get("GroupId") for sg in inst.get("SecurityGroups", [])],
                                ebs_volume_ids=[bdm.get("Ebs", {}).get("VolumeId") for bdm in inst.get("BlockDeviceMappings", []) if bdm.get("Ebs")],
                                iam_instance_profile=inst.get("IamInstanceProfile", {}).get("Arn"),
                                tags={t.get("Key"): t.get("Value") for t in inst.get("Tags", [])},
                            ))
            except Exception:
                pass

    def _inspect_ec2_instances(self, report: AWSInfrastructureReport):
        if self.boto_available:
            try:
                kwargs = {}
                if self.target_instance_id:
                    kwargs["InstanceIds"] = [self.target_instance_id]
                resp = self.ec2.describe_instances(**kwargs)
                for res in resp.get("Reservations", []):
                    for inst in res.get("Instances", []):
                        detail = EC2InstanceDetail(
                            instance_id=inst.get("InstanceId", ""),
                            instance_type=inst.get("InstanceType", ""),
                            state=inst.get("State", {}).get("Name", "unknown"),
                            ami_id=inst.get("ImageId", ""),
                            platform_or_os=inst.get("PlatformDetails", "Linux/UNIX"),
                            launch_time=str(inst.get("LaunchTime", "")),
                            vpc_id=inst.get("VpcId"),
                            subnet_id=inst.get("SubnetId"),
                            private_ip=inst.get("PrivateIpAddress"),
                            public_ip=inst.get("PublicIpAddress"),
                            security_group_ids=[sg.get("GroupId") for sg in inst.get("SecurityGroups", [])],
                            ebs_volume_ids=[bdm.get("Ebs", {}).get("VolumeId") for bdm in inst.get("BlockDeviceMappings", []) if bdm.get("Ebs")],
                            iam_instance_profile=inst.get("IamInstanceProfile", {}).get("Arn"),
                            tags={t.get("Key"): t.get("Value") for t in inst.get("Tags", [])},
                        )
                        report.instances.append(detail)
                return
            except Exception as e:
                report.errors_or_notes.append(f"Boto3 EC2 inspection error: {e}")

        # CLI fallback
        if shutil.which("aws"):
            try:
                cmd = ["aws", "ec2", "describe-instances", "--region", self.region_name, "--output", "json"]
                if self.target_instance_id:
                    cmd.extend(["--instance-ids", self.target_instance_id])
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    for res in data.get("Reservations", []):
                        for inst in res.get("Instances", []):
                            report.instances.append(EC2InstanceDetail(
                                instance_id=inst.get("InstanceId", ""),
                                instance_type=inst.get("InstanceType", ""),
                                state=inst.get("State", {}).get("Name", "unknown"),
                                ami_id=inst.get("ImageId", ""),
                                platform_or_os=inst.get("PlatformDetails", "Linux/UNIX"),
                                launch_time=str(inst.get("LaunchTime", "")),
                                vpc_id=inst.get("VpcId"),
                                subnet_id=inst.get("SubnetId"),
                                private_ip=inst.get("PrivateIpAddress"),
                                public_ip=inst.get("PublicIpAddress"),
                                security_group_ids=[sg.get("GroupId") for sg in inst.get("SecurityGroups", [])],
                                ebs_volume_ids=[bdm.get("Ebs", {}).get("VolumeId") for bdm in inst.get("BlockDeviceMappings", []) if bdm.get("Ebs")],
                                iam_instance_profile=inst.get("IamInstanceProfile", {}).get("Arn"),
                                tags={t.get("Key"): t.get("Value") for t in inst.get("Tags", [])},
                            ))
            except Exception as e:
                report.errors_or_notes.append(f"CLI EC2 inspection error: {e}")

    def _inspect_networking(self, report: AWSInfrastructureReport):
        if self.boto_available:
            try:
                vpcs = self.ec2.describe_vpcs().get("Vpcs", [])
                report.vpcs = [{"VpcId": v.get("VpcId"), "CidrBlock": v.get("CidrBlock"), "IsDefault": v.get("IsDefault")} for v in vpcs]
                subnets = self.ec2.describe_subnets().get("Subnets", [])
                report.subnets = [{"SubnetId": s.get("SubnetId"), "VpcId": s.get("VpcId"), "AvailabilityZone": s.get("AvailabilityZone"), "CidrBlock": s.get("CidrBlock")} for s in subnets]
            except Exception as e:
                report.errors_or_notes.append(f"Networking inspection error: {e}")

    def _inspect_security_groups(self, report: AWSInfrastructureReport):
        if self.boto_available:
            try:
                sgs = self.ec2.describe_security_groups().get("SecurityGroups", [])
                for sg in sgs:
                    detail = SecurityGroupDetail(
                        group_id=sg.get("GroupId", ""),
                        group_name=sg.get("GroupName", ""),
                        vpc_id=sg.get("VpcId", ""),
                        description=sg.get("Description", ""),
                    )
                    for perm in sg.get("IpPermissions", []):
                        proto = perm.get("IpProtocol", "-1")
                        from_p = perm.get("FromPort")
                        to_p = perm.get("ToPort")
                        for ip_r in perm.get("IpRanges", []):
                            detail.rules.append(SecurityGroupRule(
                                direction="inbound",
                                protocol=proto,
                                from_port=from_p,
                                to_port=to_p,
                                cidr=ip_r.get("CidrIp"),
                                description=ip_r.get("Description"),
                            ))
                    report.security_groups.append(detail)
            except Exception as e:
                report.errors_or_notes.append(f"Security group inspection error: {e}")

    def _inspect_iam(self, report: AWSInfrastructureReport):
        if self.boto_available:
            try:
                roles = self.iam.list_roles(MaxItems=10).get("Roles", [])
                report.iam_roles = [{"RoleName": r.get("RoleName"), "Arn": r.get("Arn")} for r in roles]
            except Exception as e:
                report.errors_or_notes.append(f"IAM inspection error: {e}")
