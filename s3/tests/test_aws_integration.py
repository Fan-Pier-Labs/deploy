"""Unit tests for aws modules (route53, acm, cloudfront) using mock boto3 clients."""
import os
import sys
from unittest.mock import patch
import pytest

_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from s3.mock_boto3 import (
    MockRoute53Client,
    MockACMClient,
    MockCloudFrontClient,
    MockSession,
    ResourceNotFoundException,
)


# Import aws modules from repo root
import aws.route53 as route53
import aws.acm as acm
import aws.cloudfront as cloudfront


class TestRoute53WithMock:
    """Tests for aws.route53 using MockRoute53Client."""

    def test_find_hosted_zone_exact_match(self):
        client = MockRoute53Client()
        client.add_hosted_zone("/hostedzone/Z123", "example.com")
        zone_id, record_name, zone_name = route53.find_hosted_zone(client, "example.com")
        assert zone_id == "/hostedzone/Z123"
        assert zone_name == "example.com"
        assert record_name == "example.com"

    def test_find_hosted_zone_subdomain(self):
        client = MockRoute53Client()
        client.add_hosted_zone("/hostedzone/Z123", "example.com")
        zone_id, record_name, zone_name = route53.find_hosted_zone(client, "app.example.com")
        assert zone_id == "/hostedzone/Z123"
        assert zone_name == "example.com"
        assert record_name == "app"

    def test_find_hosted_zone_not_found(self):
        client = MockRoute53Client()
        zone_id, record_name, zone_name = route53.find_hosted_zone(client, "unknown.com")
        assert zone_id is None
        assert record_name is None
        assert zone_name is None

    def test_create_or_update_dns_record_create_new(self):
        client = MockRoute53Client()
        client.add_hosted_zone("/hostedzone/Z123", "example.com")
        route53.create_or_update_dns_record(
            client, "app.example.com", "d123.cloudfront.net",
            record_type="A", ttl=300, allow_create=True
        )
        records = client.state["record_sets"].get("/hostedzone/Z123", [])
        assert len(records) == 1
        assert records[0]["Type"] == "A"
        assert "AliasTarget" in records[0] or "d123.cloudfront.net" in str(records[0])

    def test_create_or_update_dns_record_no_zone_exits(self):
        client = MockRoute53Client()
        with pytest.raises(SystemExit):
            route53.create_or_update_dns_record(
                client, "app.unknown.com", "d123.cloudfront.net",
                record_type="A", allow_create=True
            )

    def test_create_validation_record(self):
        client = MockRoute53Client()
        client.add_hosted_zone("/hostedzone/Z123", "example.com")
        route53.create_validation_record(
            client,
            {"name": "_abc123.example.com", "type": "CNAME", "value": "xyz.acm-validations.aws."},
            allow_create=True,
        )
        records = client.state["record_sets"].get("/hostedzone/Z123", [])
        assert len(records) == 1
        assert records[0]["Type"] == "CNAME"

    def test_get_hosted_zone_ns(self):
        client = MockRoute53Client()
        client.add_hosted_zone("/hostedzone/Z123", "example.com", ns_list=["ns-1.awsdns-1.com", "ns-2.awsdns-2.com"])
        ns = route53.get_hosted_zone_ns(client, "/hostedzone/Z123", "example.com")
        assert sorted(ns) == ["ns-1.awsdns-1.com", "ns-2.awsdns-2.com"]

    def test_get_hosted_zone_ns_empty_when_no_ns_record(self):
        client = MockRoute53Client()
        client.add_hosted_zone("/hostedzone/Z123", "example.com")
        ns = route53.get_hosted_zone_ns(client, "/hostedzone/Z123", "example.com")
        assert ns == []

    def test_validate_ns_delegation_match(self):
        client = MockRoute53Client()
        client.add_hosted_zone("/hostedzone/Z123", "example.com", ns_list=["ns-1.awsdns-1.com", "ns-2.awsdns-2.com"])
        with patch("aws.route53.get_public_ns_for_domain", return_value=["ns-1.awsdns-1.com", "ns-2.awsdns-2.com"]):
            ok, msg, r53_ns, public_ns = route53.validate_ns_delegation(client, "app.example.com")
        assert ok is True
        assert "match" in msg.lower() or "ok" in msg.lower()
        assert set(r53_ns) == {"ns-1.awsdns-1.com", "ns-2.awsdns-2.com"}

    def test_validate_ns_delegation_mismatch(self):
        client = MockRoute53Client()
        client.add_hosted_zone("/hostedzone/Z123", "example.com", ns_list=["ns-1.awsdns-1.com", "ns-2.awsdns-2.com"])
        with patch("aws.route53.get_public_ns_for_domain", return_value=["other-ns.registrar.com"]):
            ok, msg, r53_ns, public_ns = route53.validate_ns_delegation(client, "app.example.com")
        assert ok is False
        assert "mismatch" in msg.lower() or "not pointing" in msg.lower()
        assert r53_ns == ["ns-1.awsdns-1.com", "ns-2.awsdns-2.com"]
        assert public_ns == ["other-ns.registrar.com"]


class TestACMWithMock:
    """Tests for aws.acm using MockACMClient."""

    def test_request_certificate_apex_domain(self):
        client = MockACMClient(region="us-east-1")
        arn = acm.request_certificate(client, "example.com", "us-east-1", allow_create=True)
        assert arn is not None
        assert "arn:aws:acm" in arn
        assert len(client.state["certificates"]) == 1

    def test_request_certificate_subdomain_wildcard(self):
        client = MockACMClient(region="us-east-1")
        arn = acm.request_certificate(client, "app.example.com", "us-east-1", allow_create=True)
        assert arn is not None
        cert = list(client.state["certificates"].values())[0]
        assert cert["DomainName"].startswith("*.")

    def test_find_certificate_exact_match(self):
        client = MockACMClient(region="us-east-1")
        client._certs["arn:aws:acm:us-east-1:123:certificate/1"] = {
            "CertificateArn": "arn:aws:acm:us-east-1:123:certificate/1",
            "DomainName": "example.com",
            "Status": "ISSUED",
            "SubjectAlternativeNames": ["example.com"],
        }
        found = acm.find_certificate(client, "example.com", "us-east-1")
        assert found == "arn:aws:acm:us-east-1:123:certificate/1"

    def test_get_certificate_validation_records(self):
        client = MockACMClient(region="us-east-1")
        response = client.request_certificate(DomainName="example.com", ValidationMethod="DNS")
        arn = response["CertificateArn"]
        records = acm.get_certificate_validation_records(client, arn)
        assert len(records) >= 1, "expected at least one validation record from mock cert"
        assert records[0].get("type") == "CNAME"
        assert "name" in records[0]
        assert "value" in records[0]

    def test_wait_for_certificate_validation_issued_immediately(self):
        client = MockACMClient(region="us-east-1")
        client._certs["arn:test"] = {
            "CertificateArn": "arn:test",
            "DomainName": "example.com",
            "Status": "ISSUED",
            "DomainValidationOptions": [],
            "SubjectAlternativeNames": [],
        }
        result = acm.wait_for_certificate_validation(client, "arn:test", timeout_minutes=1)
        assert result is True

    def test_describe_certificate_not_found_raises(self):
        client = MockACMClient(region="us-east-1")
        with pytest.raises(ResourceNotFoundException):
            client.describe_certificate(CertificateArn="arn:aws:acm:us-east-1:123:certificate/nonexistent")


class TestCloudfrontWithMock:
    """Tests for aws.cloudfront using MockCloudFrontClient."""

    def test_invalidate_cloudfront_cache(self):
        client = MockCloudFrontClient()
        client.create_distribution(DistributionConfig={
            "CallerReference": "test",
            "Aliases": {"Quantity": 1, "Items": ["app.example.com"]},
            "Origins": {"Quantity": 1, "Items": [{"Id": "s3", "DomainName": "bucket.s3.amazonaws.com"}]},
            "DefaultCacheBehavior": {},
            "Enabled": True,
            "Comment": "test",
        })
        dist_id = list(client.state["distributions"].keys())[0]
        inv_id = cloudfront.invalidate_cloudfront_cache(client, dist_id, paths=["/*"])
        assert inv_id is not None
        assert len(client.state["invalidations"]) == 1
        assert client.state["invalidations"][0]["Paths"] == ["/*"]
