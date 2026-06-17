#!/usr/bin/env python3
"""
Create (or reuse) a dev RDS PostgreSQL instance in ap-south-1 and wire .env to it.

Usage:
  python scripts/aws/create_rds_dev.py --dry-run
  python scripts/aws/create_rds_dev.py --create
  python scripts/aws/create_rds_dev.py --status
  python scripts/aws/create_rds_dev.py --apply-env   # update .env from existing instance

Requires AWS credentials in repo .env (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY).
"""
from __future__ import annotations

import argparse
import re
import secrets
import string
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"

DEFAULT_REGION = "ap-south-1"
INSTANCE_ID = "statathon-dev"
DB_NAME = "statathon"
MASTER_USER = "statathon"
ENGINE = "postgres"
ENGINE_VERSION = ""  # auto-pick latest 16.x in region
INSTANCE_CLASS = "db.t4g.micro"
ALLOCATED_STORAGE = 20


def load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def public_ip() -> str:
    try:
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=5) as resp:
            return resp.read().decode().strip()
    except Exception:
        return "0.0.0.0/0"


def rds_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pwd) and any(c.isupper() for c in pwd) and any(c.isdigit() for c in pwd):
            return pwd


def get_boto_session(env: dict[str, str]):
    import boto3

    region = env.get("AWS_REGION") or env.get("RDS_REGION") or DEFAULT_REGION
    if env.get("AWS_REGION") == "us-east-1" and not env.get("RDS_REGION"):
        region = DEFAULT_REGION
    return boto3.Session(
        aws_access_key_id=env.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=env.get("AWS_SECRET_ACCESS_KEY"),
        region_name=region,
    ), region


def find_instance(rds, identifier: str):
    resp = rds.describe_db_instances(DBInstanceIdentifier=identifier)
    return resp["DBInstances"][0]


def instance_exists(rds, identifier: str) -> bool:
    try:
        find_instance(rds, identifier)
        return True
    except rds.exceptions.DBInstanceNotFoundFault:
        return False
    except Exception as exc:
        msg = str(exc).lower()
        if "dbinstancenotfound" in msg:
            return False
        raise


def default_vpc_subnets(ec2):
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise RuntimeError("No default VPC in region — create RDS via AWS Console (see docs/deploy/aws/10-rds-only-laptop.md)")
    vpc_id = vpcs[0]["VpcId"]
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]
    subnet_ids = [s["SubnetId"] for s in subnets]
    if len(subnet_ids) < 2:
        raise RuntimeError("Default VPC needs at least 2 subnets for RDS")
    return vpc_id, subnet_ids


def ensure_security_group(ec2, vpc_id: str, my_ip: str) -> str:
    name = "statathon-rds-dev"
    existing = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [name]}, {"Name": "vpc-id", "Values": [vpc_id]}]
    )["SecurityGroups"]
    cidr = f"{my_ip}/32" if "/" not in my_ip else my_ip
    if existing:
        sg_id = existing[0]["GroupId"]
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 5432,
                    "ToPort": 5432,
                    "IpRanges": [{"CidrIp": cidr, "Description": "Statathon dev laptop"}],
                }
            ],
        ) if not _has_pg_rule(existing[0], cidr) else None
        return sg_id

    sg = ec2.create_security_group(
        GroupName=name,
        Description="Statathon dev RDS - PostgreSQL from developer IP",
        VpcId=vpc_id,
    )
    sg_id = sg["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
                "IpRanges": [{"CidrIp": cidr, "Description": "Statathon dev laptop"}],
            }
        ],
    )
    return sg_id


def _has_pg_rule(sg: dict, cidr: str) -> bool:
    for perm in sg.get("IpPermissions", []):
        if perm.get("FromPort") == 5432:
            for r in perm.get("IpRanges", []):
                if r.get("CidrIp") == cidr:
                    return True
    return False


def ensure_subnet_group(rds, name: str, subnet_ids: list[str]) -> None:
    try:
        rds.describe_db_subnet_groups(DBSubnetGroupName=name)
    except rds.exceptions.DBSubnetGroupNotFoundFault:
        rds.create_db_subnet_group(
            DBSubnetGroupName=name,
            DBSubnetGroupDescription="Statathon dev RDS subnets",
            SubnetIds=subnet_ids[:6],
        )


def resolve_engine_version(rds, major: str = "16") -> str:
    if ENGINE_VERSION:
        return ENGINE_VERSION
    versions = rds.describe_db_engine_versions(Engine=ENGINE)["DBEngineVersions"]
    candidates = sorted(
        v["EngineVersion"] for v in versions if v["EngineVersion"].startswith(f"{major}.")
    )
    if not candidates:
        raise RuntimeError(f"No PostgreSQL {major}.x engine available in this region")
    return candidates[-1]


def create_instance(rds, *, password: str, sg_id: str, subnet_group: str) -> None:
    engine_version = resolve_engine_version(rds)
    print(f"  Engine version: {engine_version}")
    rds.create_db_instance(
        DBInstanceIdentifier=INSTANCE_ID,
        DBName=DB_NAME,
        Engine=ENGINE,
        EngineVersion=engine_version,
        DBInstanceClass=INSTANCE_CLASS,
        AllocatedStorage=ALLOCATED_STORAGE,
        MasterUsername=MASTER_USER,
        MasterUserPassword=password,
        VpcSecurityGroupIds=[sg_id],
        DBSubnetGroupName=subnet_group,
        PubliclyAccessible=True,
        BackupRetentionPeriod=1,
        StorageEncrypted=True,
        AutoMinorVersionUpgrade=True,
        Tags=[{"Key": "Project", "Value": "statathon"}, {"Key": "Environment", "Value": "dev"}],
    )


def wait_available(rds, identifier: str, timeout_sec: int = 900) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        inst = find_instance(rds, identifier)
        status = inst["DBInstanceStatus"]
        print(f"  RDS status: {status}")
        if status == "available":
            return inst
        if status in ("failed", "incompatible-restore", "incompatible-parameters"):
            raise RuntimeError(f"RDS instance entered bad state: {status}")
        time.sleep(20)
    raise TimeoutError(f"RDS {identifier} not available after {timeout_sec}s")


def database_url(endpoint: str, password: str) -> str:
    return f"postgresql://{MASTER_USER}:{password}@{endpoint}:5432/{DB_NAME}?sslmode=require"


def update_env_file(url: str, password: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    replaced_url = False
    for line in lines:
        if line.strip().startswith("DATABASE_URL=") and not line.strip().startswith("#"):
            out.append(f"DATABASE_URL={url}")
            replaced_url = True
        elif line.strip().startswith("# DATABASE_URL="):
            out.append(line)
        else:
            out.append(line)
    if not replaced_url:
        out.append(f"DATABASE_URL={url}")

    block = [
        "",
        "# RDS dev (Amazon RDS ap-south-1 — created by scripts/aws/create_rds_dev.py)",
        f"RDS_MASTER_PASSWORD={password}",
        "DB_POOL_SIZE=5",
        "DB_POOL_MAX_OVERFLOW=10",
        "DB_STATEMENT_TIMEOUT_MS=30000",
    ]
    merged = "\n".join(out)
    if "RDS_MASTER_PASSWORD=" not in merged:
        merged += "\n".join(block) + "\n"
    else:
        merged = re.sub(
            r"^RDS_MASTER_PASSWORD=.*$",
            f"RDS_MASTER_PASSWORD={password}",
            merged,
            flags=re.MULTILINE,
        )
    ENV_PATH.write_text(merged if merged.endswith("\n") else merged + "\n", encoding="utf-8")


def cmd_status(session, region: str) -> int:
    rds = session.client("rds")
    if not instance_exists(rds, INSTANCE_ID):
        print(f"No RDS instance '{INSTANCE_ID}' in {region}")
        return 1
    inst = find_instance(rds, INSTANCE_ID)
    ep = inst.get("Endpoint") or {}
    print(f"Instance: {INSTANCE_ID}")
    print(f"Status:   {inst['DBInstanceStatus']}")
    print(f"Engine:   {inst['Engine']} {inst.get('EngineVersion')}")
    print(f"Endpoint: {ep.get('Address')}:{ep.get('Port', 5432)}")
    print(f"Public:   {inst.get('PubliclyAccessible')}")
    return 0


def cmd_dry_run(session, region: str) -> int:
    ec2 = session.client("ec2")
    rds = session.client("rds")
    my_ip = public_ip()
    print(f"Region:     {region}")
    print(f"Instance:   {INSTANCE_ID}")
    print(f"Your IP:    {my_ip}")
    print(f"Exists:     {instance_exists(rds, INSTANCE_ID)}")
    vpc_id, subnets = default_vpc_subnets(ec2)
    print(f"Default VPC: {vpc_id} ({len(subnets)} subnets)")
    return 0


def cmd_create(session, region: str, password: str | None) -> int:
    ec2 = session.client("ec2")
    rds = session.client("rds")
    my_ip = public_ip()
    pwd = password or rds_password()

    if instance_exists(rds, INSTANCE_ID):
        print(f"RDS '{INSTANCE_ID}' already exists — waiting for available...")
        inst = wait_available(rds, INSTANCE_ID, timeout_sec=60)
    else:
        vpc_id, subnet_ids = default_vpc_subnets(ec2)
        sg_id = ensure_security_group(ec2, vpc_id, my_ip)
        subnet_group = "statathon-dev-subnets"
        ensure_subnet_group(rds, subnet_group, subnet_ids)
        print(f"Creating RDS '{INSTANCE_ID}' in {region} (public, IP {my_ip}/32)...")
        print("This takes ~5–10 minutes.")
        create_instance(rds, password=pwd, sg_id=sg_id, subnet_group=subnet_group)
        inst = wait_available(rds, INSTANCE_ID)

    endpoint = inst["Endpoint"]["Address"]
    url = database_url(endpoint, pwd)
    update_env_file(url, pwd)
    print(f"\nUpdated {ENV_PATH}")
    print(f"DATABASE_URL host: {endpoint}")
    print("\nNext: python scripts/migrate_db.py --bootstrap && python scripts/migrate_db.py")
    print("      Restart uvicorn.")
    return 0


def cmd_apply_env(session, region: str) -> int:
    env = load_dotenv(ENV_PATH)
    pwd = env.get("RDS_MASTER_PASSWORD")
    if not pwd:
        print("Set RDS_MASTER_PASSWORD in .env (from when instance was created)", file=sys.stderr)
        return 1
    rds = session.client("rds")
    inst = find_instance(rds, INSTANCE_ID)
    endpoint = inst["Endpoint"]["Address"]
    update_env_file(database_url(endpoint, pwd), pwd)
    print(f"Applied DATABASE_URL for {endpoint}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or configure Statathon dev RDS")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--apply-env", action="store_true")
    parser.add_argument("--password", default="", help="Master password (generated if omitted)")
    parser.add_argument("--region", default="", help=f"AWS region (default {DEFAULT_REGION})")
    args = parser.parse_args()

    env = load_dotenv(ENV_PATH)
    session, region = get_boto_session(env)
    if args.region:
        import boto3
        session = boto3.Session(
            aws_access_key_id=env.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=env.get("AWS_SECRET_ACCESS_KEY"),
            region_name=args.region,
        )
        region = args.region

    if not env.get("AWS_ACCESS_KEY_ID") or not env.get("AWS_SECRET_ACCESS_KEY"):
        print("Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env", file=sys.stderr)
        return 1

    if args.dry_run:
        return cmd_dry_run(session, region)
    if args.status:
        return cmd_status(session, region)
    if args.apply_env:
        return cmd_apply_env(session, region)
    if args.create:
        return cmd_create(session, region, args.password or None)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
