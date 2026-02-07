#!/usr/bin/env python3
"""
Run S3 or Fargate deployment against mock boto3, then tear it down.
Validates that deploy + destroy work together.
Usage (from repo root):
  python run_deploy_mock.py [config_file]
Default config: test_site/deploy.yaml
"""
import os
import sys
import yaml

# Repo root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch, MagicMock

# Resolve config path
config_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "test_site", "deploy.yaml")
if not os.path.isabs(config_path):
    config_path = os.path.join(os.path.dirname(__file__), config_path)


def _platform_from_config(path):
    """Load YAML and return platform (s3, fargate, etc.)."""
    with open(path, "r") as f:
        cfg = yaml.safe_load(f)
    return (cfg.get("platform") or "s3").lower()


# --- Fargate mock ---

try:
    from botocore.exceptions import ClientError
except ImportError:
    class ClientError(Exception):
        def __init__(self, error_response, operation_name=None):
            self.response = error_response
            self.operation_name = operation_name


def _make_fargate_mock_session(region="us-east-2", account_id="123456789012"):
    """Build a mock boto3 Session that returns mock clients for Fargate deploy + destroy."""
    session = MagicMock()
    session.region_name = region

    # Stateful Route53 records so deploy-created A records exist during teardown
    route53_records = {}  # hosted_zone_id -> list of ResourceRecordSet dicts

    def route53_list_resource_record_sets(HostedZoneId, StartRecordName=None, StartRecordType=None, MaxItems="1", **kwargs):
        records = list(route53_records.get(HostedZoneId, []))
        if StartRecordName is not None:
            sn = StartRecordName.rstrip(".")
            records = [r for r in records if r["Name"].rstrip(".") == sn]
        if StartRecordType is not None:
            records = [r for r in records if r["Type"] == StartRecordType]
        n = int(MaxItems) if isinstance(MaxItems, str) else (MaxItems or 1)
        return {"ResourceRecordSets": records[:n]}

    def route53_change_resource_record_sets(HostedZoneId, ChangeBatch=None, **kwargs):
        for change in (ChangeBatch or {}).get("Changes", []):
            action = change["Action"]
            rrset = change["ResourceRecordSet"]
            if HostedZoneId not in route53_records:
                route53_records[HostedZoneId] = []
            key = (rrset["Name"].rstrip("."), rrset["Type"])
            if action in ("CREATE", "UPSERT"):
                route53_records[HostedZoneId] = [
                    r for r in route53_records[HostedZoneId]
                    if (r["Name"].rstrip("."), r["Type"]) != key
                ]
                route53_records[HostedZoneId].append(rrset)
            elif action == "DELETE":
                route53_records[HostedZoneId] = [
                    r for r in route53_records[HostedZoneId]
                    if (r["Name"].rstrip("."), r["Type"]) != key
                ]
        return {}

    def client(name):
        m = MagicMock()
        if name == "sts":
            m.get_caller_identity.return_value = {"Account": account_id}
            return m
        if name == "ec2":
            m.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-mock"}]}
            m.describe_subnets.return_value = {"Subnets": [{"SubnetId": "subnet-1"}, {"SubnetId": "subnet-2"}]}
            m.describe_security_groups.return_value = {"SecurityGroups": []}
            m.create_security_group.return_value = {"GroupId": "sg-mock"}
            m.authorize_security_group_ingress.return_value = {}
            # lightweight path: describe by GroupIds, then describe_network_interfaces
            m.describe_security_groups.side_effect = lambda **kw: (
                {"SecurityGroups": [{"GroupId": "sg-mock", "IpPermissions": []}]}
                if kw.get("GroupIds") else {"SecurityGroups": []}
            )
            m.describe_network_interfaces.return_value = {
                "NetworkInterfaces": [{"Association": {"PublicIp": "1.2.3.4"}}]
            }
            m.exceptions = type("Exceptions", (), {"ClientError": ClientError})()
            return m
        if name == "iam":
            m.exceptions = type("Exceptions", (), {"NoSuchEntityException": ClientError})()
            m.get_role.side_effect = m.exceptions.NoSuchEntityException({}, "GetRole")
            m.create_role.return_value = {"Role": {"Arn": "arn:aws:iam::123456789012:role/ecsTaskExecutionRole"}}
            m.list_attached_role_policies.return_value = {"AttachedPolicies": []}
            m.attach_role_policy.return_value = {}
            m.put_role_policy.return_value = {}
            m.get_role_policy.side_effect = m.exceptions.NoSuchEntityException({}, "GetRolePolicy")
            m.delete_role_policy.return_value = {}
            return m
        if name == "logs":
            m.describe_log_groups.return_value = {"logGroups": []}
            m.create_log_group.return_value = {}
            m.put_retention_policy.return_value = {}
            m.put_resource_policy.return_value = {}
            m.exceptions = type("Exceptions", (), {"ResourceAlreadyExistsException": ClientError})()
            return m
        if name == "ecr":
            m.exceptions = type("Exceptions", (), {"RepositoryNotFoundException": ClientError})()
            m.describe_repositories.side_effect = m.exceptions.RepositoryNotFoundException({}, "DescribeRepositories")
            m.create_repository.return_value = {}
            m.delete_repository.return_value = {}
            return m
        if name == "ecs":
            m.describe_clusters.return_value = {"clusters": []}
            m.create_cluster.return_value = {}
            m.put_cluster_capacity_providers.return_value = {}
            m.update_cluster_settings.return_value = {}
            m.register_task_definition.return_value = {
                "taskDefinition": {"taskDefinitionArn": "arn:aws:ecs:us-east-2:123456789012:task-definition/deploytest-fargate-site-task:1"}
            }
            m.describe_services.return_value = {
                "services": [{"status": "RUNNING", "serviceName": "deploytest-fargate-site-service"}]
            }
            m.list_tasks.return_value = {"taskArns": ["arn:aws:ecs:us-east-2:123456789012:task/abc"]}
            m.describe_tasks.return_value = {
                "tasks": [{
                    "lastStatus": "RUNNING",
                    "attachments": [{
                        "type": "ElasticNetworkInterface",
                        "details": [
                            {"name": "networkInterfaceId", "value": "eni-mock"},
                            {"name": "publicIPv4Address", "value": "1.2.3.4"},
                        ],
                    }],
                }]
            }
            m.create_service.return_value = {"service": {"serviceName": "x"}}
            m.update_service.return_value = {"service": {"serviceName": "x"}}
            m.delete_service.return_value = {}
            paginator = MagicMock()
            paginator.paginate.return_value = []  # list_task_definitions
            m.get_paginator.return_value = paginator
            m.exceptions = type("Exceptions", (), {
                "ClusterNotFoundException": ClientError,
                "ServiceNotFoundException": ClientError,
            })()
            return m
        if name == "events":
            m.exceptions = type("Exceptions", (), {"ResourceNotFoundException": ClientError})()
            m.describe_rule.side_effect = m.exceptions.ResourceNotFoundException({"Error": {"Code": "ResourceNotFoundException"}}, "DescribeRule")
            m.put_rule.return_value = {}
            m.list_targets_by_rule.return_value = {"Targets": []}
            m.put_targets.return_value = {}
            m.remove_targets.return_value = {}
            return m
        if name == "route53":
            paginator = MagicMock()
            paginator.paginate.return_value = [{"HostedZones": [{"Id": "/hostedzone/ZMOCK", "Name": "fanpierlabs.com."}]}]
            m.get_paginator.return_value = paginator
            m.list_resource_record_sets.side_effect = route53_list_resource_record_sets
            m.change_resource_record_sets.side_effect = route53_change_resource_record_sets
            m.create_hosted_zone.return_value = {"DelegationSet": {"NameServers": ["ns-1.awsdns-1.com"]}}
            return m
        if name == "cloudfront":
            paginator = MagicMock()
            paginator.paginate.return_value = [{"DistributionList": {"Items": []}}]
            m.get_paginator.return_value = paginator
            m.get_distribution_config.return_value = {"ETag": "E1", "DistributionConfig": {"Enabled": True}}
            m.update_distribution.return_value = {}
            m.delete_distribution.return_value = {}
            m.get_distribution.return_value = {"Distribution": {"Status": "Deployed"}}
            return m
        if name == "elbv2":
            m.describe_load_balancers.return_value = {"LoadBalancers": []}
            m.describe_listeners.return_value = {"Listeners": []}
            m.describe_target_groups.return_value = {"TargetGroups": []}
            m.exceptions = type("Exceptions", (), {
                "LoadBalancerNotFoundException": ClientError,
                "TargetGroupNotFoundException": ClientError,
            })()
            return m
        return MagicMock()

    session.client = client
    return session


def run_fargate_mock(config_path):
    """Run Fargate deploy + destroy with mocked boto3 and no real Docker build."""
    from aws.config import load_config
    from aws.deploy import deploy_to_fargate
    from aws.destroy import destroy_fargate_infra

    config_dict = load_config(config_path)
    config_dict["_config_file"] = config_path

    mock_session = _make_fargate_mock_session(
        region=config_dict.get("region", "us-east-2"),
    )

    fake_image = "123456789012.dkr.ecr.us-east-2.amazonaws.com/deploytest-fargate-site:latest-mock"

    # ---- Phase 1: Deploy ----
    print("\n" + "=" * 60)
    print("PHASE 1: FARGATE DEPLOY (mock)")
    print("=" * 60)
    with patch("aws.deploy.boto3.Session", return_value=mock_session):
        with patch("aws.ecr.build_and_push_image", return_value=fake_image):
            with patch("aws.cloudfront.wait_for_cloudfront_deployment", return_value=True):
                with patch("aws.deploy.time.sleep", return_value=None):  # avoid wait loops in lightweight path
                    with patch("aws.deploy.test_deployment_http_requests", MagicMock()):  # skip real HTTP test in mock
                        deploy_to_fargate(config_dict=config_dict)

    # ---- Phase 2: Destroy ----
    print("\n" + "=" * 60)
    print("PHASE 2: FARGATE DESTROY (mock)")
    print("=" * 60)
    with patch("aws.destroy.boto3.Session", return_value=mock_session):
        with patch("aws.cloudfront.wait_for_cloudfront_deployment", return_value=True):
            with patch("aws.destroy.time.sleep", return_value=None):  # avoid wait in destroy
                destroy_fargate_infra(config_dict, confirm_callback=lambda _: True)

    print("\n" + "=" * 60)
    print("OK: Fargate deploy + destroy (mock) completed.")
    print("=" * 60)


# --- S3 mock ---

from s3.config import load_config as s3_load_config
from s3.deploy import deploy_to_s3
from s3.destroy import destroy_s3_infra
from s3.mock_boto3 import MockSession


def _print_state(mock_session, label=""):
    buckets = list(mock_session._s3_state.keys())
    dists = mock_session._cloudfront_state.get("distributions", {})
    certs = mock_session._acm_state.get("certificates", {})
    print(f"  {label}S3 buckets: {buckets}")
    print(f"  {label}CloudFront: {list(dists.keys()) if dists else []}")
    print(f"  {label}ACM certs: {len(certs)}")
    return buckets, dists, certs


def run_s3_mock(config_path):
    """Run S3 deploy + destroy with s3 mock boto3."""
    config_dict = s3_load_config(config_path)
    mock_session = MockSession(profile_name=config_dict.get("profile"), region_name=config_dict.get("region"))

    mock_ns = ["ns-1.awsdns-1.com", "ns-2.awsdns-2.com"]
    if config_dict.get("public") and config_dict["public"].get("domain"):
        domain = config_dict["public"]["domain"]
        parts = domain.split(".")
        if len(parts) >= 2:
            zone_name = ".".join(parts[-2:])
            mock_session.seed_route53_hosted_zone("/hostedzone/ZMOCK123", zone_name, ns_list=mock_ns)

    if config_dict.get("public") and config_dict.get("certificate_id"):
        cert_arn = f"arn:aws:acm:us-east-1:123456789012:certificate/{config_dict['certificate_id']}"
        mock_session.seed_acm_certificate(cert_arn, config_dict["public"]["domain"], status="ISSUED")

    print("\n" + "=" * 60)
    print("PHASE 1: DEPLOY")
    print("=" * 60)
    with patch("s3.deploy.boto3.Session", return_value=mock_session):
        with patch("aws.route53.get_public_ns_for_domain", return_value=mock_ns):
            with patch("s3.deploy.test_deployment_http_requests", MagicMock()):
                with patch("s3.deploy.acm.wait_for_certificate_validation", return_value=True):
                    deploy_to_s3(config_dict=config_dict)

    print("\n[After deploy] State:")
    buckets_after_deploy, dists_after_deploy, _ = _print_state(mock_session)
    if not buckets_after_deploy:
        print("ERROR: No S3 bucket created during deploy")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("PHASE 2: DESTROY (teardown)")
    print("=" * 60)
    with patch("s3.destroy.boto3.Session", return_value=mock_session):
        destroy_s3_infra(config_dict, confirm_callback=lambda _: True)

    print("\n[After destroy] State:")
    buckets_after_destroy, dists_after_destroy, _ = _print_state(mock_session)

    ok = True
    if buckets_after_destroy:
        print(f"\nERROR: S3 buckets still present after destroy: {buckets_after_destroy}")
        ok = False
    if dists_after_destroy:
        print(f"\nERROR: CloudFront distributions still present after destroy: {list(dists_after_destroy.keys())}")
        ok = False
    if ok:
        print("\n" + "=" * 60)
        print("OK: Deploy + destroy completed; all resources torn down.")
        print("=" * 60)
    else:
        sys.exit(1)


def main():
    if not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    platform = _platform_from_config(config_path)
    if platform == "fargate":
        run_fargate_mock(config_path)
    else:
        run_s3_mock(config_path)


if __name__ == "__main__":
    main()
