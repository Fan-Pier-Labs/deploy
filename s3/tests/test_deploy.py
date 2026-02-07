"""Unit tests for deploy module using mock boto3 client."""
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock
import pytest

_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from s3.mock_boto3 import MockSession
from s3 import deploy


class TestDeployToS3Validation:
    """Tests for deploy_to_s3 parameter validation and early exits."""

    def test_missing_app_name_exits(self):
        with pytest.raises(SystemExit):
            deploy.deploy_to_s3(
                app_name=None,
                region="us-east-1",
                folder="/tmp/some",
            )

    def test_missing_region_exits(self):
        with pytest.raises(SystemExit):
            deploy.deploy_to_s3(
                app_name="myapp",
                region=None,
                folder="/tmp/some",
            )

    def test_missing_folder_exits(self):
        with pytest.raises(SystemExit):
            deploy.deploy_to_s3(
                app_name="myapp",
                region="us-east-1",
                folder=None,
            )

    def test_config_dict_merged_with_kwargs(self):
        """Params should merge config_dict and kwargs; bucket name comes from app_name in config_dict."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            mock_session = MockSession()
            with patch("s3.deploy.boto3.Session", return_value=mock_session):
                deploy.deploy_to_s3(
                    config_dict={"app_name": "from_dict"},
                    region="us-east-1",
                    folder=d,
                    allow_create=True,
                )
            assert "from-dict-static-site" in mock_session._s3_state

    def test_bucket_name_user_specified_too_short_exits(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            with patch("s3.deploy.boto3.Session", return_value=MockSession()):
                with pytest.raises(SystemExit):
                    deploy.deploy_to_s3(
                        app_name="myapp",
                        region="us-east-1",
                        folder=d,
                        bucket_name="ab",  # < 3 chars
                        allow_create=True,
                    )

    def test_bucket_name_user_specified_too_long_exits(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            with patch("s3.deploy.boto3.Session", return_value=MockSession()):
                with pytest.raises(SystemExit):
                    deploy.deploy_to_s3(
                        app_name="myapp",
                        region="us-east-1",
                        folder=d,
                        bucket_name="a" * 64,
                        allow_create=True,
                    )

    def test_bucket_name_user_specified_invalid_chars_exits(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            with patch("s3.deploy.boto3.Session", return_value=MockSession()):
                with pytest.raises(SystemExit):
                    deploy.deploy_to_s3(
                        app_name="myapp",
                        region="us-east-1",
                        folder=d,
                        bucket_name="my_bucket!!!",
                        allow_create=True,
                    )

    def test_bucket_name_user_specified_starts_with_dot_exits(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            with patch("s3.deploy.boto3.Session", return_value=MockSession()):
                with pytest.raises(SystemExit):
                    deploy.deploy_to_s3(
                        app_name="myapp",
                        region="us-east-1",
                        folder=d,
                        bucket_name=".mybucket",
                        allow_create=True,
                    )


class TestDeployToS3S3Only:
    """Tests for deploy_to_s3 S3-only path (no public domain)."""

    def test_full_s3_only_deploy_success(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            mock_session = MockSession()
            with patch("s3.deploy.boto3.Session", return_value=mock_session):
                deploy.deploy_to_s3(
                    app_name="myapp",
                    region="us-east-1",
                    folder=d,
                    allow_create=True,
                )
            # Bucket name generated from app_name
            assert "myapp-static-site" in mock_session._s3_state
            bucket = mock_session._s3_state["myapp-static-site"]
            assert bucket.get("website") is not None
            assert bucket.get("policy") is not None
            assert "index.html" in bucket.get("objects", {})

    def test_bucket_name_generated_from_app_name_lowercase(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            mock_session = MockSession()
            with patch("s3.deploy.boto3.Session", return_value=mock_session):
                deploy.deploy_to_s3(
                    app_name="MyApp",
                    region="us-east-1",
                    folder=d,
                    allow_create=True,
                )
            # Underscores replaced with hyphens, lowercased
            assert "myapp-static-site" in mock_session._s3_state

    def test_user_specified_bucket_name_used(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            mock_session = MockSession()
            with patch("s3.deploy.boto3.Session", return_value=mock_session):
                deploy.deploy_to_s3(
                    app_name="myapp",
                    region="us-east-1",
                    folder=d,
                    bucket_name="custom-bucket-name",
                    allow_create=True,
                )
            assert "custom-bucket-name" in mock_session._s3_state
            assert "myapp-static-site" not in mock_session._s3_state

    def test_allow_create_false_bucket_missing_exits(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            mock_session = MockSession()
            # No bucket pre-created; allow_create=False
            with patch("s3.deploy.boto3.Session", return_value=mock_session):
                with pytest.raises(SystemExit):
                    deploy.deploy_to_s3(
                        app_name="myapp",
                        region="us-east-1",
                        folder=d,
                        allow_create=False,
                    )


class TestDeployToS3WithPublicDomain:
    """Tests for deploy_to_s3 with public domain (CloudFront, Route53, ACM)."""

    @patch("s3.deploy.test_deployment_http_requests", MagicMock())
    @patch("s3.deploy.acm.wait_for_certificate_validation", return_value=True)
    def test_public_domain_uses_certificate_id_and_issued_cert(self, mock_wait):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            mock_session = MockSession()
            mock_session.seed_route53_hosted_zone("/hostedzone/Z123", "example.com")
            cert_arn = "arn:aws:acm:us-east-1:123456789012:certificate/cert-123"
            mock_session.seed_acm_certificate(cert_arn, "app.example.com", status="ISSUED")
            with patch("s3.deploy.boto3.Session", return_value=mock_session):
                deploy.deploy_to_s3(
                    app_name="myapp",
                    region="us-east-1",
                    folder=d,
                    allow_create=True,
                    public={"domain": "app.example.com"},
                    certificate_id="cert-123",
                )
            # CloudFront and Route53 should have been used (state has "distributions" key)
            assert len(mock_session._cloudfront_state.get("distributions", {})) == 1

    @patch("s3.deploy.test_deployment_http_requests", MagicMock())
    @patch("s3.deploy.acm.wait_for_certificate_validation", return_value=True)
    def test_public_domain_request_certificate_path(self, mock_wait):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            mock_session = MockSession()
            mock_session.seed_route53_hosted_zone("/hostedzone/Z123", "example.com")
            # No certificate_id -> request_certificate path; no cert pre-seeded
            with patch("s3.deploy.boto3.Session", return_value=mock_session):
                deploy.deploy_to_s3(
                    app_name="myapp",
                    region="us-east-1",
                    folder=d,
                    allow_create=True,
                    public={"domain": "app.example.com"},
                )
            # ACM should have been asked to request cert (mock will have one after request)
            assert len(mock_session._acm_state.get("certificates", {})) >= 1
            assert len(mock_session._cloudfront_state.get("distributions", {})) == 1


class TestDeployToS3BucketNameGeneration:
    """Tests for bucket name generation from app_name."""

    def test_app_name_with_underscores_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            mock_session = MockSession()
            with patch("s3.deploy.boto3.Session", return_value=mock_session):
                deploy.deploy_to_s3(
                    app_name="my_app_name",
                    region="us-east-1",
                    folder=d,
                    allow_create=True,
                )
            assert "my-app-name-static-site" in mock_session._s3_state


class TestTestDeploymentHttpRequests:
    """Tests for test_deployment_http_requests helper."""

    @patch("s3.deploy.time.sleep", MagicMock())
    def test_returns_early_on_success(self):
        # Mock urlopen to return 200
        with patch("s3.deploy.urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.headers = {"Content-Type": "text/html", "Content-Length": "0"}
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_resp)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            deploy.test_deployment_http_requests(
                {"domain": "example.com"},
                {"_cloudfront_domain": "d123.cloudfront.net"},
            )
            # Should have tried URLs
            assert mock_open.called

    @patch("s3.deploy.time.sleep", MagicMock())
    def test_retries_on_failure_then_gives_up(self):
        # Simulate URL failures so it eventually returns after max time
        with patch("s3.deploy.urllib.request.urlopen", side_effect=Exception("connection refused")):
            with patch("s3.deploy.time.time", side_effect=[0, 0, 700]):  # elapsed >= 600 after second loop
                deploy.test_deployment_http_requests(
                    {"domain": "example.com"},
                    {},
                )
                # Should return without raising (gives up after timeout)
                pass
