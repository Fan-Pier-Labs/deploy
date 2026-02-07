"""Unit tests for s3_bucket module using mock boto3 client."""
import os
import sys
import tempfile
from unittest.mock import patch
import pytest
from botocore.exceptions import ClientError

# Add repo root so we can import s3 and mock_boto3
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from s3.mock_boto3 import MockS3Client
from s3 import s3_bucket


class TestCreateS3Bucket:
    """Tests for create_s3_bucket."""

    def test_bucket_already_exists(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        result = s3_bucket.create_s3_bucket(client, "my-bucket", "us-east-1", allow_create=False)
        assert result == "my-bucket"
        assert "my-bucket" in client.state

    def test_bucket_does_not_exist_allow_create_true_us_east_1(self):
        client = MockS3Client()
        result = s3_bucket.create_s3_bucket(client, "new-bucket", "us-east-1", allow_create=True)
        assert result == "new-bucket"
        assert "new-bucket" in client.state
        assert client.state["new-bucket"]["region"] == "us-east-1"

    def test_bucket_does_not_exist_allow_create_true_other_region(self):
        client = MockS3Client()
        result = s3_bucket.create_s3_bucket(client, "new-bucket", "us-west-2", allow_create=True)
        assert result == "new-bucket"
        assert "new-bucket" in client.state
        assert client.state["new-bucket"]["region"] == "us-west-2"

    def test_bucket_does_not_exist_allow_create_false_exits(self):
        client = MockS3Client()
        with pytest.raises(SystemExit):
            s3_bucket.create_s3_bucket(client, "missing-bucket", "us-east-1", allow_create=False)

    def test_head_bucket_other_client_error_exits(self):
        """Non-404 ClientError from head_bucket should exit (e.g. 403 Forbidden)."""
        client = MockS3Client()
        with patch.object(client, "head_bucket", side_effect=ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadBucket")):
            with pytest.raises(SystemExit):
                s3_bucket.create_s3_bucket(client, "some-bucket", "us-east-1", allow_create=True)


class TestConfigureS3BucketForWebsite:
    """Tests for configure_s3_bucket_for_website."""

    def test_already_configured(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        client.put_bucket_website(
            Bucket="my-bucket",
            WebsiteConfiguration={"IndexDocument": {"Suffix": "index.html"}, "ErrorDocument": {"Key": "index.html"}},
        )
        s3_bucket.configure_s3_bucket_for_website(client, "my-bucket", allow_create=False)
        assert client.state["my-bucket"]["website"] is not None

    def test_not_configured_allow_create_true(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        s3_bucket.configure_s3_bucket_for_website(client, "my-bucket", allow_create=True)
        assert client.state["my-bucket"]["website"] is not None

    def test_not_configured_allow_create_false_exits(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with pytest.raises(SystemExit):
            s3_bucket.configure_s3_bucket_for_website(client, "my-bucket", allow_create=False)


class TestDisableBlockPublicAccess:
    """Tests for disable_block_public_access."""

    def test_already_disabled(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        client.put_public_access_block(
            Bucket="my-bucket",
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        s3_bucket.disable_block_public_access(client, "my-bucket", allow_create=False)

    def test_not_set_allow_create_true(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        s3_bucket.disable_block_public_access(client, "my-bucket", allow_create=True)
        assert client.state["my-bucket"]["public_access_block"] is not None
        assert client.state["my-bucket"]["public_access_block"]["BlockPublicAcls"] is False

    def test_not_set_allow_create_false_exits(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with pytest.raises(SystemExit):
            s3_bucket.disable_block_public_access(client, "my-bucket", allow_create=False)


class TestSetBucketPolicyForCloudfront:
    """Tests for set_bucket_policy_for_cloudfront."""

    def test_policy_already_exists(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        client.put_bucket_policy(Bucket="my-bucket", Policy='{"Version":"2012-10-17"}')
        s3_bucket.set_bucket_policy_for_cloudfront(client, "my-bucket", allow_create=False)
        assert client.state["my-bucket"]["policy"] is not None

    def test_no_policy_allow_create_true(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        s3_bucket.set_bucket_policy_for_cloudfront(client, "my-bucket", allow_create=True)
        assert client.state["my-bucket"]["policy"] is not None
        assert "PublicReadGetObject" in client.state["my-bucket"]["policy"]
        assert "my-bucket" in client.state["my-bucket"]["policy"]

    def test_no_policy_allow_create_false_exits(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with pytest.raises(SystemExit):
            s3_bucket.set_bucket_policy_for_cloudfront(client, "my-bucket", allow_create=False)


class TestUploadFolderToS3:
    """Tests for upload_folder_to_s3."""

    def test_folder_does_not_exist_exits(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with pytest.raises(SystemExit):
            s3_bucket.upload_folder_to_s3(client, "my-bucket", "/nonexistent/path")

    def test_path_not_directory_exits(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"x")
            path = f.name
        try:
            with pytest.raises(SystemExit):
                s3_bucket.upload_folder_to_s3(client, "my-bucket", path)
        finally:
            os.unlink(path)

    def test_no_index_html_exits(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with tempfile.TemporaryDirectory() as d:
            # Empty dir, no index.html
            with pytest.raises(SystemExit):
                s3_bucket.upload_folder_to_s3(client, "my-bucket", d)

    def test_upload_single_file(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            s3_bucket.upload_folder_to_s3(client, "my-bucket", d)
        assert "index.html" in client.state["my-bucket"]["objects"]
        assert client.state["my-bucket"]["objects"]["index.html"]["ContentType"] == "text/html"

    def test_upload_multiple_files_content_types(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            with open(os.path.join(d, "app.js"), "w") as f:
                f.write("console.log(1);")
            with open(os.path.join(d, "style.css"), "w") as f:
                f.write("body {}")
            with open(os.path.join(d, "data.json"), "w") as f:
                f.write("{}")
            s3_bucket.upload_folder_to_s3(client, "my-bucket", d)
        objs = client.state["my-bucket"]["objects"]
        assert objs["index.html"]["ContentType"] == "text/html"
        assert objs["app.js"]["ContentType"] == "application/javascript"
        assert objs["style.css"]["ContentType"] == "text/css"
        assert objs["data.json"]["ContentType"] == "application/json"

    def test_upload_subdirectory_structure(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            sub = os.path.join(d, "assets")
            os.makedirs(sub)
            with open(os.path.join(sub, "script.js"), "w") as f:
                f.write("x")
            s3_bucket.upload_folder_to_s3(client, "my-bucket", d)
        assert "index.html" in client.state["my-bucket"]["objects"]
        assert "assets/script.js" in client.state["my-bucket"]["objects"]

    def test_incremental_skips_unchanged_files(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html></html>")
            s3_bucket.upload_folder_to_s3(client, "my-bucket", d, incremental=True)
            assert "index.html" in client.state["my-bucket"]["objects"]
            # Second run with same content: should skip (no duplicate upload)
            s3_bucket.upload_folder_to_s3(client, "my-bucket", d, incremental=True)
            # Object still present once
            assert list(client.state["my-bucket"]["objects"].keys()) == ["index.html"]

    def test_incremental_uploads_changed_file(self):
        client = MockS3Client()
        client.create_bucket(Bucket="my-bucket")
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html>v1</html>")
            s3_bucket.upload_folder_to_s3(client, "my-bucket", d, incremental=True)
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<html>v2</html>")
            s3_bucket.upload_folder_to_s3(client, "my-bucket", d, incremental=True)
            assert client.state["my-bucket"]["objects"]["index.html"]["Body"] == b"<html>v2</html>"


class TestGetBucketWebsiteEndpoint:
    """Tests for get_bucket_website_endpoint."""

    def test_returns_correct_format(self):
        client = MockS3Client()
        result = s3_bucket.get_bucket_website_endpoint(client, "my-bucket", "us-west-2")
        assert result == "my-bucket.s3.us-west-2.amazonaws.com"
