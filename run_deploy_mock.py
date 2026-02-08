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

from contextlib import contextmanager
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
    # Stateful ECS clusters: shared across client("ecs") calls so delete_cluster keeps cluster INACTIVE for a bit
    ecs_clusters = {}
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
            # Use session-scoped ecs_clusters so state persists across deploy -> destroy -> deploy

            def describe_clusters(*a, **kw):
                names = kw.get("clusters", [])
                result = []
                for cn in names:
                    if cn in ecs_clusters:
                        entry = ecs_clusters[cn]
                        result.append({"clusterName": cn, "status": entry["status"]})
                        if entry.get("describe_until_gone", 0) > 0:
                            entry["describe_until_gone"] -= 1
                            if entry["describe_until_gone"] == 0:
                                del ecs_clusters[cn]
                return {"clusters": result}

            def create_cluster(*a, **kw):
                cn = kw.get("clusterName")
                if cn:
                    ecs_clusters[cn] = {"status": "ACTIVE", "describe_until_gone": 0}
                return {}

            def delete_cluster(*a, **kw):
                cn = kw.get("cluster")
                if cn and cn in ecs_clusters:
                    ecs_clusters[cn]["status"] = "INACTIVE"
                    ecs_clusters[cn]["describe_until_gone"] = 3  # stay visible as INACTIVE for 3 describe calls
                return {}

            return StrictClient("ecs", {
                "describe_clusters": describe_clusters,
                "create_cluster": create_cluster,
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
                "delete_cluster": delete_cluster,
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


def _make_mock_aws_modules(fake_image, mock_ns, account_id="123456789012"):
    """Build mock aws submodules so deploy/destroy never call real aws code. Any unmocked call errors."""
    # Minimal boto3 session: no real AWS. client() returns mocks; sts.get_caller_identity returns account.
    mock_sts = MagicMock()
    mock_sts.get_caller_identity.return_value = {"Account": account_id}
    mock_acm_client = MagicMock()
    mock_acm_client.describe_certificate.return_value = {"Certificate": {"Status": "ISSUED", "DomainName": "*.fanpierlabs.com"}}
    mock_acm_client.exceptions = type("Exceptions", (), {"ResourceNotFoundException": Exception})()
    mock_session = MagicMock()
    mock_session.region_name = "us-east-2"
    def _client(name, **kw):
        if name == "sts":
            return mock_sts
        if name == "acm":
            return mock_acm_client
        return MagicMock()
    mock_session.client.side_effect = _client

    # Mock aws submodules (only the functions deploy/destroy call; anything else would be real aws → error if we used strict)
    mock_vpc = MagicMock()
    mock_vpc.get_default_vpc_resources.return_value = (["subnet-1", "subnet-2"], "sg-mock", "vpc-mock")
    mock_vpc.create_alb_security_group.return_value = "sg-mock"
    mock_vpc.update_fargate_security_group_for_alb.return_value = None

    mock_iam = MagicMock()
    mock_iam.ensure_ecs_execution_role.return_value = f"arn:aws:iam::{account_id}:role/ecsTaskExecutionRole"

    mock_logs = MagicMock()
    mock_logs.ensure_cloudwatch_log_group.return_value = None
    mock_logs.tail_ecs_logs.return_value = None

    mock_events = MagicMock()
    mock_events.enable_event_capture.return_value = None

    mock_ecr = MagicMock()
    mock_ecr.setup_ecr_repository.return_value = None
    mock_ecr.build_and_push_image.return_value = fake_image

    mock_ecs = MagicMock()
    mock_ecs.ensure_cluster.return_value = None
    mock_ecs.register_task_definition.return_value = f"arn:aws:ecs:us-east-2:{account_id}:task-definition/deploytest-fargate-site-task:1"
    mock_ecs.create_or_update_service.return_value = {"service": {"serviceName": "deploytest-fargate-site-service"}}

    mock_route53 = MagicMock()
    mock_route53.ensure_domain_ready_for_dns.return_value = None
    mock_route53.create_or_update_dns_record.return_value = None
    mock_route53.create_validation_record.return_value = None
    mock_route53.get_public_ns_for_domain.return_value = mock_ns
    mock_route53.find_hosted_zone.return_value = ("/hostedzone/ZMOCK", "fargatetest", "fanpierlabs.com")
    mock_route53.get_existing_record.return_value = None

    mock_cloudfront = MagicMock()
    mock_cloudfront.create_cloudfront_distribution.return_value = ("d123.cloudfront.net", "E1")
    mock_cloudfront.wait_for_cloudfront_deployment.return_value = True
    mock_cloudfront.invalidate_cloudfront_cache.return_value = None

    mock_alb = MagicMock()
    mock_alb.create_application_load_balancer.return_value = ("arn:alb", "alb-mock.example.com")
    mock_alb.create_target_group.return_value = "arn:tg"
    mock_alb.create_listener.return_value = None
    mock_alb.wait_for_healthy_targets.return_value = None

    mock_acm = MagicMock()
    mock_acm.request_certificate.return_value = f"arn:aws:acm:us-east-1:{account_id}:certificate/mock-1"
    mock_acm.get_certificate_validation_records.return_value = []
    mock_acm.wait_for_certificate_validation.return_value = True

    return {
        "session": mock_session,
        "vpc": mock_vpc,
        "iam": mock_iam,
        "logs": mock_logs,
        "events": mock_events,
        "ecr": mock_ecr,
        "ecs": mock_ecs,
        "route53": mock_route53,
        "cloudfront": mock_cloudfront,
        "alb": mock_alb,
        "acm": mock_acm,
    }


@contextmanager
def fargate_aws_mock(fake_image, mock_ns):
    """
    Single patch: mock out the whole aws package (and boto3) so no real AWS/network is used.
    All boto3.Session() and aws.* calls go through mocks; if something isn't mocked, it would error.
    """
    mocks = _make_mock_aws_modules(fake_image, mock_ns)
    with patch("boto3.Session", return_value=mocks["session"]), \
         patch("time.sleep", return_value=None), \
         patch("aws.deploy.vpc", mocks["vpc"]), \
         patch("aws.deploy.iam", mocks["iam"]), \
         patch("aws.deploy.logs", mocks["logs"]), \
         patch("aws.deploy.events", mocks["events"]), \
         patch("aws.deploy.ecr", mocks["ecr"]), \
         patch("aws.deploy.ecs", mocks["ecs"]), \
         patch("aws.deploy.route53", mocks["route53"]), \
         patch("aws.deploy.cloudfront", mocks["cloudfront"]), \
         patch("aws.deploy.alb", mocks["alb"]), \
         patch("aws.deploy.acm", mocks["acm"]), \
         patch("aws.deploy.test_deployment_http_requests", MagicMock()), \
         patch("aws.destroy.route53", mocks["route53"]), \
         patch("aws.destroy.cloudfront", mocks["cloudfront"]):
        yield


def run_fargate_mock(config_path):
    """Run Fargate deploy + destroy with aws (and boto3) fully mocked; no real network."""
    from aws.config import load_config
    from aws.deploy import deploy_to_fargate
    from aws.destroy import destroy_fargate_infra

    config_dict = load_config(config_path)
    config_dict["_config_file"] = config_path

    fake_image = "123456789012.dkr.ecr.us-east-2.amazonaws.com/deploytest-fargate-site:latest-mock"
    mock_ns = ["ns-1.awsdns-1.com", "ns-2.awsdns-2.com"]

    with fargate_aws_mock(fake_image, mock_ns):
        # ---- Phase 1: Deploy ----
        print("\n" + "=" * 60)
        print("PHASE 1: FARGATE DEPLOY (mock)")
        print("=" * 60)
        deploy_to_fargate(config_dict=config_dict)

        # ---- Phase 2: Destroy ----
        print("\n" + "=" * 60)
        print("PHASE 2: FARGATE DESTROY (mock)")
        print("=" * 60)
        destroy_fargate_infra(config_dict, confirm_callback=lambda _: True)

        # ---- Phase 3: Deploy again (cluster was INACTIVE for a bit after delete; then gone) ----
        print("\n" + "=" * 60)
        print("PHASE 3: FARGATE DEPLOY AGAIN (mock)")
        print("=" * 60)
        deploy_to_fargate(config_dict=config_dict)

    print("\n" + "=" * 60)
    print("OK: Fargate deploy + destroy + deploy (mock) completed.")
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
