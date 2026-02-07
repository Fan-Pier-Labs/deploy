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


# --- Fargate mock: strict AWS mock so real boto3 is never called ---

try:
    from botocore.exceptions import ClientError
except ImportError:
    class ClientError(Exception):
        def __init__(self, error_response, operation_name=None):
            self.response = error_response
            self.operation_name = operation_name


def _strict_error(what):
    """Raise and exit so real boto3 is never used in tests."""
    msg = f"Real boto3 must not be called in tests. {what}"
    raise AssertionError(msg)


def _raise_when_called(exc):
    """Return a callable that raises exc when called (for mock client methods that must raise)."""
    def raiser(*args, **kwargs):
        raise exc
    return raiser


class StrictClient:
    """Client that only allows explicitly defined methods; any other access raises and exits."""

    def __init__(self, service_name, allowed):
        self._service = service_name
        self._allowed = dict(allowed)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._allowed:
            _strict_error(f"Unexpected: client('{self._service}').{name}()")
        return self._allowed[name]


class StrictSession:
    """Session that only allows .client(name) and .region_name; any other access raises."""

    def __init__(self, client_fn, region_name):
        self._client_fn = client_fn
        self.region_name = region_name

    def client(self, name):
        return self._client_fn(name)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        _strict_error(f"Unexpected: Session.{name}")


def _make_fargate_mock_session(region="us-east-2", account_id="123456789012"):
    """Build a strict mock boto3 Session: only defined clients/methods allowed; real boto3 never used."""
    # Stateful Route53 records so deploy-created A records exist during teardown
    route53_records = {}
    _mock_zone_ns_record = {
        "Name": "fanpierlabs.com.",
        "Type": "NS",
        "ResourceRecords": [{"Value": "ns-1.awsdns-1.com."}, {"Value": "ns-2.awsdns-2.com."}],
        "TTL": 172800,
    }

    def route53_list(HostedZoneId, StartRecordName=None, StartRecordType=None, MaxItems="1", **kwargs):
        records = list(route53_records.get(HostedZoneId, []))
        if HostedZoneId == "/hostedzone/ZMOCK" and StartRecordType == "NS":
            records = [_mock_zone_ns_record] + records
        if StartRecordName is not None:
            sn = StartRecordName.rstrip(".")
            records = [r for r in records if r["Name"].rstrip(".") == sn]
        if StartRecordType is not None:
            records = [r for r in records if r["Type"] == StartRecordType]
        n = int(MaxItems) if isinstance(MaxItems, str) else (MaxItems or 1)
        return {"ResourceRecordSets": records[:n]}

    def route53_change(HostedZoneId, ChangeBatch=None, **kwargs):
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
        if name == "sts":
            return StrictClient("sts", {
                "get_caller_identity": lambda **kw: {"Account": account_id},
            })
        if name == "ec2":
            return StrictClient("ec2", {
                "describe_vpcs": lambda **kw: {"Vpcs": [{"VpcId": "vpc-mock"}]},
                "describe_subnets": lambda **kw: {"Subnets": [{"SubnetId": "subnet-1"}, {"SubnetId": "subnet-2"}]},
                "describe_security_groups": lambda **kw: (
                    {"SecurityGroups": [{"GroupId": "sg-mock", "IpPermissions": []}]}
                    if kw.get("GroupIds") else {"SecurityGroups": []}
                ),
                "create_security_group": lambda **kw: {"GroupId": "sg-mock"},
                "authorize_security_group_ingress": lambda **kw: {},
                "describe_network_interfaces": lambda **kw: {"NetworkInterfaces": [{"Association": {"PublicIp": "1.2.3.4"}}]},
                "delete_security_group": lambda **kw: {},
                "exceptions": type("Exceptions", (), {"ClientError": ClientError})(),
            })
        if name == "iam":
            exc_ns = type("Exceptions", (), {"NoSuchEntityException": ClientError})()
            no_such_entity = ClientError({"Error": {"Code": "NoSuchEntity"}}, "GetRole")
            return StrictClient("iam", {
                "get_role": _raise_when_called(no_such_entity),
                "create_role": lambda **kw: {"Role": {"Arn": "arn:aws:iam::123456789012:role/ecsTaskExecutionRole"}},
                "list_attached_role_policies": lambda **kw: {"AttachedPolicies": []},
                "attach_role_policy": lambda **kw: {},
                "put_role_policy": lambda **kw: {},
                "get_role_policy": _raise_when_called(ClientError({"Error": {"Code": "NoSuchEntity"}}, "GetRolePolicy")),
                "delete_role_policy": lambda **kw: {},
                "exceptions": exc_ns,
            })
        if name == "logs":
            return StrictClient("logs", {
                "describe_log_groups": lambda **kw: {"logGroups": []},
                "create_log_group": lambda **kw: {},
                "put_retention_policy": lambda **kw: {},
                "put_resource_policy": lambda **kw: {},
                "filter_log_events": lambda **kw: {"events": []},
                "exceptions": type("Exceptions", (), {"ResourceAlreadyExistsException": ClientError})(),
            })
        if name == "ecr":
            exc_ns = type("Exceptions", (), {"RepositoryNotFoundException": ClientError})()
            return StrictClient("ecr", {
                "describe_repositories": _raise_when_called(ClientError({"Error": {"Code": "RepositoryNotFoundException"}}, "DescribeRepositories")),
                "create_repository": lambda **kw: {},
                "delete_repository": lambda **kw: {},
                "exceptions": exc_ns,
            })
        if name == "ecs":
            paginator = MagicMock()
            paginator.paginate.return_value = []
            exc = type("Exceptions", (), {"ClusterNotFoundException": ClientError, "ServiceNotFoundException": ClientError})()
            return StrictClient("ecs", {
                "describe_clusters": lambda *a, **kw: {"clusters": []},
                "create_cluster": lambda *a, **kw: {},
                "put_cluster_capacity_providers": lambda *a, **kw: {},
                "update_cluster_settings": lambda *a, **kw: {},
                "register_task_definition": lambda *a, **kw: {
                    "taskDefinition": {"taskDefinitionArn": "arn:aws:ecs:us-east-2:123456789012:task-definition/deploytest-fargate-site-task:1"}
                },
                "describe_services": lambda *a, **kw: {"services": [{"status": "RUNNING", "serviceName": "deploytest-fargate-site-service"}]},
                "list_tasks": lambda *a, **kw: {"taskArns": ["arn:aws:ecs:us-east-2:123456789012:task/abc"]},
                "describe_tasks": lambda *a, **kw: {
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
                },
                "create_service": lambda *a, **kw: {"service": {"serviceName": "x"}},
                "update_service": lambda *a, **kw: {"service": {"serviceName": "x"}},
                "delete_service": lambda *a, **kw: {},
                "delete_cluster": lambda *a, **kw: {},
                "deregister_task_definition": lambda *a, **kw: {},
                "get_paginator": lambda *a, **kw: paginator,
                "exceptions": exc,
            })
        if name == "events":
            exc_ns = type("Exceptions", (), {"ResourceNotFoundException": ClientError})()
            return StrictClient("events", {
                "describe_rule": _raise_when_called(ClientError({"Error": {"Code": "ResourceNotFoundException"}}, "DescribeRule")),
                "put_rule": lambda **kw: {},
                "list_targets_by_rule": lambda **kw: {"Targets": []},
                "put_targets": lambda **kw: {},
                "remove_targets": lambda **kw: {},
                "exceptions": exc_ns,
            })
        if name == "route53":
            paginator = MagicMock()
            paginator.paginate.return_value = [{"HostedZones": [{"Id": "/hostedzone/ZMOCK", "Name": "fanpierlabs.com."}]}]
            return StrictClient("route53", {
                "get_paginator": lambda *a, **kw: paginator,
                "list_resource_record_sets": route53_list,
                "change_resource_record_sets": route53_change,
                "create_hosted_zone": lambda *a, **kw: {"DelegationSet": {"NameServers": ["ns-1.awsdns-1.com"]}},
            })
        if name == "cloudfront":
            paginator = MagicMock()
            paginator.paginate.return_value = [{"DistributionList": {"Items": []}}]
            return StrictClient("cloudfront", {
                "get_paginator": lambda *a, **kw: paginator,
                "get_distribution_config": lambda **kw: {"ETag": "E1", "DistributionConfig": {"Enabled": True}},
                "update_distribution": lambda **kw: {},
                "delete_distribution": lambda **kw: {},
                "get_distribution": lambda **kw: {"Distribution": {"Status": "Deployed"}},
                "create_distribution": lambda **kw: {"Distribution": {"Id": "E1", "DomainName": "d123.cloudfront.net"}},
                "create_invalidation": lambda **kw: {"Invalidation": {"Id": "I1", "Status": "Completed"}},
            })
        if name == "elbv2":
            exc = type("Exceptions", (), {"LoadBalancerNotFoundException": ClientError, "TargetGroupNotFoundException": ClientError})()
            waiter = type("Waiter", (), {"wait": lambda self, **kw: None})()
            return StrictClient("elbv2", {
                "describe_load_balancers": lambda **kw: {"LoadBalancers": []},
                "describe_listeners": lambda **kw: {"Listeners": []},
                "describe_target_groups": lambda **kw: {"TargetGroups": []},
                "create_load_balancer": lambda **kw: {"LoadBalancers": [{"LoadBalancerArn": "arn:alb", "DNSName": "alb-mock.example.com"}]},
                "create_target_group": lambda **kw: {"TargetGroups": [{"TargetGroupArn": "arn:tg"}]},
                "create_listener": lambda **kw: {"Listeners": [{"ListenerArn": "arn:listener"}]},
                "get_waiter": lambda *a, **kw: waiter,
                "modify_target_group": lambda **kw: {},
                "describe_target_health": lambda **kw: {"TargetHealthDescriptions": []},
                "describe_services": lambda **kw: {"services": [{"status": "ACTIVE"}]},
                "delete_listener": lambda **kw: {},
                "delete_load_balancer": lambda **kw: {},
                "delete_target_group": lambda **kw: {},
                "exceptions": exc,
            })
        if name == "acm":
            acm_paginator = MagicMock()
            acm_paginator.paginate.return_value = []
            return StrictClient("acm", {
                "request_certificate": lambda *a, **kw: {"CertificateArn": "arn:aws:acm:us-east-1:123456789012:certificate/mock-1"},
                "describe_certificate": lambda *a, **kw: {"Certificate": {"Status": "ISSUED", "DomainName": "*.fanpierlabs.com"}},
                "get_paginator": lambda *a, **kw: acm_paginator,
                "exceptions": type("Exceptions", (), {"ResourceNotFoundException": ClientError})(),
            })
        _strict_error(f"Unexpected: client('{name}')")

    return StrictSession(client, region)


def run_fargate_mock(config_path):
    """Run Fargate deploy + destroy with all AWS mocked (strict: real boto3 never called)."""
    from aws.config import load_config
    from aws.deploy import deploy_to_fargate
    from aws.destroy import destroy_fargate_infra

    config_dict = load_config(config_path)
    config_dict["_config_file"] = config_path

    mock_session = _make_fargate_mock_session(
        region=config_dict.get("region", "us-east-2"),
    )
    fake_image = "123456789012.dkr.ecr.us-east-2.amazonaws.com/deploytest-fargate-site:latest-mock"
    mock_ns = ["ns-1.awsdns-1.com", "ns-2.awsdns-2.com"]

    # Single patch: all boto3.Session() calls (deploy, destroy, ecr, etc.) use our strict mock.
    # Any unmocked client or method raises AssertionError so real boto3 is never used.
    with patch("boto3.Session", return_value=mock_session):
        # ---- Phase 1: Deploy ----
        print("\n" + "=" * 60)
        print("PHASE 1: FARGATE DEPLOY (mock)")
        print("=" * 60)
        with patch("aws.ecr.build_and_push_image", return_value=fake_image):
            with patch("aws.cloudfront.wait_for_cloudfront_deployment", return_value=True):
                with patch("aws.acm.wait_for_certificate_validation", return_value=True):
                    with patch("aws.deploy.time.sleep", return_value=None):
                        with patch("aws.deploy.test_deployment_http_requests", MagicMock()):
                            with patch("aws.logs.tail_ecs_logs", MagicMock()):
                                with patch("aws.route53.get_public_ns_for_domain", return_value=mock_ns):
                                    deploy_to_fargate(config_dict=config_dict)

        # ---- Phase 2: Destroy ----
        print("\n" + "=" * 60)
        print("PHASE 2: FARGATE DESTROY (mock)")
        print("=" * 60)
        with patch("aws.cloudfront.wait_for_cloudfront_deployment", return_value=True):
            with patch("aws.destroy.time.sleep", return_value=None):
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
