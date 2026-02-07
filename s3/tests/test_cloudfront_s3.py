"""Unit tests for cloudfront_s3 module using mock boto3 client."""
import os
import sys
import pytest

_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from s3.mock_boto3 import MockCloudFrontClient
from s3 import cloudfront_s3


class TestCreateCloudfrontDistributionForS3:
    """Tests for create_cloudfront_distribution_for_s3."""

    def test_create_new_distribution_allow_create_true(self):
        client = MockCloudFrontClient()
        cf_domain, cf_id = cloudfront_s3.create_cloudfront_distribution_for_s3(
            client, "my-bucket", "us-east-1", "app.example.com", "us-east-1",
            allow_create=True, certificate_arn=None
        )
        assert cf_id is not None
        assert "cloudfront.net" in cf_domain
        assert len(client.state["distributions"]) == 1
        dist = list(client.state["distributions"].values())[0]
        assert "app.example.com" in dist["Aliases"]["Items"]
        assert dist["Config"]["DefaultCacheBehavior"]["DefaultTTL"] == 600

    def test_create_new_distribution_with_certificate(self):
        client = MockCloudFrontClient()
        cert_arn = "arn:aws:acm:us-east-1:123456789012:certificate/abc-123"
        cf_domain, cf_id = cloudfront_s3.create_cloudfront_distribution_for_s3(
            client, "my-bucket", "us-east-1", "app.example.com", "us-east-1",
            allow_create=True, certificate_arn=cert_arn
        )
        assert cf_id is not None
        dist = list(client.state["distributions"].values())[0]
        assert dist["Config"]["ViewerCertificate"]["ACMCertificateArn"] == cert_arn

    def test_use_existing_distribution_same_domain_alias(self):
        client = MockCloudFrontClient()
        # Create one distribution first
        cf_domain1, cf_id1 = cloudfront_s3.create_cloudfront_distribution_for_s3(
            client, "my-bucket", "us-east-1", "app.example.com", "us-east-1",
            allow_create=True, certificate_arn=None
        )
        # Call again - should reuse existing (alias matches)
        cf_domain2, cf_id2 = cloudfront_s3.create_cloudfront_distribution_for_s3(
            client, "my-bucket", "us-east-1", "app.example.com", "us-east-1",
            allow_create=True, certificate_arn=None
        )
        assert cf_id1 == cf_id2
        assert cf_domain1 == cf_domain2
        assert len(client.state["distributions"]) == 1

    def test_no_existing_dist_allow_create_false_exits(self):
        client = MockCloudFrontClient()
        with pytest.raises(SystemExit):
            cloudfront_s3.create_cloudfront_distribution_for_s3(
                client, "my-bucket", "us-east-1", "app.example.com", "us-east-1",
                allow_create=False, certificate_arn=None
            )

    def test_origin_domain_format(self):
        client = MockCloudFrontClient()
        cf_domain, cf_id = cloudfront_s3.create_cloudfront_distribution_for_s3(
            client, "my-bucket", "us-west-2", "app.example.com", "us-west-2",
            allow_create=True, certificate_arn=None
        )
        dist = list(client.state["distributions"].values())[0]
        origins = dist["Config"]["Origins"]["Items"]
        assert len(origins) == 1
        assert origins[0]["DomainName"] == "my-bucket.s3.us-west-2.amazonaws.com"
        assert origins[0]["Id"] == "s3-origin"
