#!/usr/bin/env python3
"""
S3 bucket management and file upload.
"""
import hashlib
import sys
import os
import boto3
from botocore.exceptions import ClientError


def create_s3_bucket(s3_client, bucket_name, region, allow_create=False):
    """
    Create an S3 bucket if it doesn't exist.
    Returns the bucket name.
    """
    try:
        # Check if bucket exists
        s3_client.head_bucket(Bucket=bucket_name)
        print(f"S3 bucket {bucket_name} already exists")
        return bucket_name
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            # Bucket doesn't exist
            if not allow_create:
                print(f"S3 bucket '{bucket_name}' does not exist and resource creation is disabled.")
                sys.exit(1)
            
            print(f"Creating S3 bucket: {bucket_name}")
            try:
                # Create bucket
                if region == 'us-east-1':
                    # us-east-1 doesn't need LocationConstraint
                    s3_client.create_bucket(Bucket=bucket_name)
                else:
                    s3_client.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={'LocationConstraint': region}
                    )
                print(f"Created S3 bucket: {bucket_name}")
            except ClientError as create_error:
                print(f"Error creating S3 bucket: {create_error}")
                sys.exit(1)
        else:
            print(f"Error checking S3 bucket: {e}")
            sys.exit(1)
    
    return bucket_name


def configure_s3_bucket_for_website(s3_client, bucket_name, allow_create=False):
    """
    Configure S3 bucket for static website hosting.
    """
    try:
        # Check if website configuration already exists
        s3_client.get_bucket_website(Bucket=bucket_name)
        print(f"S3 bucket {bucket_name} is already configured for website hosting")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchWebsiteConfiguration':
            if not allow_create:
                print(f"S3 bucket '{bucket_name}' is not configured for website hosting and resource creation is disabled.")
                sys.exit(1)
            
            print(f"Configuring S3 bucket {bucket_name} for website hosting...")
            try:
                s3_client.put_bucket_website(
                    Bucket=bucket_name,
                    WebsiteConfiguration={
                        'IndexDocument': {'Suffix': 'index.html'},
                        'ErrorDocument': {'Key': 'index.html'}  # SPA support - redirect errors to index.html
                    }
                )
                print(f"Configured S3 bucket for website hosting with index.html")
            except ClientError as config_error:
                print(f"Error configuring S3 bucket for website: {config_error}")
                sys.exit(1)
        else:
            print(f"Error checking S3 bucket website configuration: {e}")
            sys.exit(1)


def disable_block_public_access(s3_client, bucket_name, allow_create=False):
    """
    Disable S3 Block Public Access settings to allow public read access.
    """
    try:
        # Check current Block Public Access settings
        try:
            response = s3_client.get_public_access_block(Bucket=bucket_name)
            settings = response.get('PublicAccessBlockConfiguration', {})
            
            # Check if all settings are already disabled
            if not any([
                settings.get('BlockPublicAcls', False),
                settings.get('IgnorePublicAcls', False),
                settings.get('BlockPublicPolicy', False),
                settings.get('RestrictPublicBuckets', False)
            ]):
                print(f"S3 bucket {bucket_name} Block Public Access is already disabled")
                return
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchPublicAccessBlockConfiguration':
                raise
        
        if not allow_create:
            print(f"S3 bucket '{bucket_name}' has Block Public Access enabled and resource creation is disabled.")
            sys.exit(1)
        
        print(f"Disabling Block Public Access for {bucket_name}...")
        s3_client.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': False,
                'IgnorePublicAcls': False,
                'BlockPublicPolicy': False,
                'RestrictPublicBuckets': False
            }
        )
        print(f"Disabled Block Public Access for {bucket_name}")
    except ClientError as e:
        print(f"Error disabling Block Public Access: {e}")
        sys.exit(1)


def set_bucket_policy_for_cloudfront(s3_client, bucket_name, allow_create=False):
    """
    Set bucket policy to allow CloudFront access (via OAI or public read).
    For now, we'll use public read access for simplicity.
    """
    try:
        # Check current bucket policy
        try:
            current_policy = s3_client.get_bucket_policy(Bucket=bucket_name)
            print(f"S3 bucket {bucket_name} already has a policy configured")
            return
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchBucketPolicy':
                raise
        
        if not allow_create:
            print(f"S3 bucket '{bucket_name}' does not have a policy and resource creation is disabled.")
            sys.exit(1)
        
        print(f"Setting bucket policy for {bucket_name} to allow public read access...")
        
        # Public read policy for CloudFront
        bucket_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PublicReadGetObject",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket_name}/*"
                }
            ]
        }
        
        import json
        s3_client.put_bucket_policy(
            Bucket=bucket_name,
            Policy=json.dumps(bucket_policy)
        )
        print(f"Set bucket policy for public read access")
    except ClientError as e:
        print(f"Error setting bucket policy: {e}")
        sys.exit(1)


def _file_md5(path):
    """Compute MD5 of file in chunks (S3 single-part ETag is MD5 hex)."""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _should_upload(s3_client, bucket_name, s3_key, local_path, incremental):
    """
    Return True if the file should be uploaded (missing on S3 or content changed).
    When incremental is False, always returns True.
    """
    if not incremental:
        return True
    try:
        head = s3_client.head_object(Bucket=bucket_name, Key=s3_key)
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return True  # object doesn't exist
        raise
    etag = (head.get('ETag') or '').strip('"')
    s3_size = head.get('ContentLength', 0)
    local_size = os.path.getsize(local_path)
    # Single-part upload: S3 ETag is MD5 hex (no hyphen)
    if '-' not in etag:
        local_md5 = _file_md5(local_path)
        if local_md5 == etag:
            return False  # identical content
        return True
    # Multipart upload: ETag is not MD5; compare size as a fast check
    if local_size != s3_size:
        return True
    # Same size but we can't verify content; upload to be safe
    return True


def upload_folder_to_s3(s3_client, bucket_name, folder_path, incremental=True):
    """
    Upload files from a folder to S3 bucket. Maintains directory structure.

    When incremental is True (default), skips files that already exist in S3
    with the same content (compared via MD5/ETag for single-part objects),
    so only changed or new files are uploaded.
    """
    if not os.path.exists(folder_path):
        print(f"Error: Folder '{folder_path}' does not exist")
        sys.exit(1)
    
    if not os.path.isdir(folder_path):
        print(f"Error: '{folder_path}' is not a directory")
        sys.exit(1)
    
    # Validate index.html exists
    index_path = os.path.join(folder_path, 'index.html')
    if not os.path.exists(index_path):
        print(f"Error: index.html not found in folder '{folder_path}'")
        sys.exit(1)
    
    mode = "incremental" if incremental else "full"
    print(f"Uploading files from '{folder_path}' to S3 bucket '{bucket_name}' ({mode})...")
    
    uploaded_count = 0
    skipped_count = 0
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            local_path = os.path.join(root, file)
            
            # Get relative path from folder_path
            relative_path = os.path.relpath(local_path, folder_path)
            # Use forward slashes for S3 keys (S3 always uses /)
            s3_key = relative_path.replace(os.sep, '/')
            
            try:
                if not _should_upload(s3_client, bucket_name, s3_key, local_path, incremental):
                    skipped_count += 1
                    print(f"  Skipped (unchanged): {s3_key}")
                    continue

                # Determine content type
                content_type = 'binary/octet-stream'
                if file.endswith('.html'):
                    content_type = 'text/html'
                elif file.endswith('.css'):
                    content_type = 'text/css'
                elif file.endswith('.js'):
                    content_type = 'application/javascript'
                elif file.endswith('.json'):
                    content_type = 'application/json'
                elif file.endswith('.png'):
                    content_type = 'image/png'
                elif file.endswith('.jpg') or file.endswith('.jpeg'):
                    content_type = 'image/jpeg'
                elif file.endswith('.svg'):
                    content_type = 'image/svg+xml'
                elif file.endswith('.ico'):
                    content_type = 'image/x-icon'
                elif file.endswith('.woff') or file.endswith('.woff2'):
                    content_type = 'font/woff' if file.endswith('.woff') else 'font/woff2'
                elif file.endswith('.ttf'):
                    content_type = 'font/ttf'
                elif file.endswith('.txt'):
                    content_type = 'text/plain'
                
                # Upload file
                s3_client.upload_file(
                    local_path,
                    bucket_name,
                    s3_key,
                    ExtraArgs={'ContentType': content_type}
                )
                uploaded_count += 1
                print(f"  Uploaded: {s3_key}")
            except Exception as e:
                print(f"Error uploading {local_path}: {e}")
                sys.exit(1)
    
    print(f"Successfully uploaded {uploaded_count} files to S3 bucket '{bucket_name}'" +
          (f", skipped {skipped_count} unchanged" if skipped_count else ""))


def get_bucket_website_endpoint(s3_client, bucket_name, region):
    """
    Get the S3 website endpoint URL.
    """
    # S3 website endpoints follow the pattern: bucket-name.s3-website-region.amazonaws.com
    # But for CloudFront, we use the REST API endpoint: bucket-name.s3.region.amazonaws.com
    return f"{bucket_name}.s3.{region}.amazonaws.com"
