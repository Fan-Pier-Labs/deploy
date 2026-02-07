#!/usr/bin/env python3
"""
Main deployment orchestrator for AWS S3 static website hosting.
"""
import sys
import boto3
import urllib.request
import urllib.error
import time

# Import AWS modules (route53, acm, cloudfront) from parent aws directory
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from aws import route53
from aws import acm
from aws import cloudfront
from . import s3_bucket
from . import cloudfront_s3


def deploy_to_s3(config_dict=None, **kwargs):
    """
    Deploy static website to AWS S3 with CloudFront and Route53.
    
    If config_dict is provided, it will be used. Otherwise, kwargs will be used.
    """
    # Merge config_dict and kwargs
    if config_dict:
        params = {**config_dict, **kwargs}
    else:
        params = kwargs
    
    # Extract parameters
    app_name = params.get('app_name')
    region = params.get('region')
    allow_create = params.get('allow_create', False)
    yes_flag = params.get('yes', False)
    folder_path = params.get('folder')
    bucket_name = params.get('bucket_name')  # Optional: user-specified bucket name
    public_config = params.get('public')
    profile = params.get('profile', 'personal')
    certificate_id = params.get('certificate_id')
    
    print("Starting deployment to AWS S3...")
    
    # Validate required parameters
    if app_name is None:
        print("Error: 'app_name' parameter is required")
        sys.exit(1)
    if region is None:
        print("Error: 'region' parameter is required")
        sys.exit(1)
    if folder_path is None:
        print("Error: 'folder' parameter is required")
        sys.exit(1)
    
    # Use the specified profile for AWS credentials and region
    session = boto3.Session(profile_name=profile, region_name=region)
    
    # Initialize AWS clients
    s3_client = session.client('s3')
    route53_client = session.client('route53')
    cloudfront_client = session.client('cloudfront')
    
    # Configuration
    # Use user-specified bucket name, or generate one from app_name
    if not bucket_name:
        # S3 bucket names must be globally unique and follow DNS naming rules:
        # - 3-63 characters long
        # - Lowercase letters, numbers, dots, and hyphens only
        # - Must start and end with a letter or number
        # - Cannot be formatted as an IP address
        bucket_name = f"{app_name}-static-site".lower().replace('_', '-')
        # Remove any invalid characters (keep only alphanumeric, dots, and hyphens)
        bucket_name = ''.join(c for c in bucket_name if c.isalnum() or c in ['-', '.'])
        # Ensure it starts and ends with alphanumeric
        bucket_name = bucket_name.strip('.-')
        # Limit length to 63 characters
        if len(bucket_name) > 63:
            bucket_name = bucket_name[:63].rstrip('.-')
        # Ensure it's at least 3 characters
        if len(bucket_name) < 3:
            bucket_name = f"{bucket_name}-site"[:63]
    else:
        # Validate user-specified bucket name
        bucket_name = bucket_name.lower().strip()
        if len(bucket_name) < 3 or len(bucket_name) > 63:
            print(f"Error: Bucket name must be between 3 and 63 characters (got {len(bucket_name)})")
            sys.exit(1)
        if not all(c.isalnum() or c in ['-', '.'] for c in bucket_name):
            print("Error: Bucket name can only contain lowercase letters, numbers, dots, and hyphens")
            sys.exit(1)
        if bucket_name.startswith('.') or bucket_name.endswith('.') or bucket_name.startswith('-') or bucket_name.endswith('-'):
            print("Error: Bucket name must start and end with a letter or number")
            sys.exit(1)
    
    try:
        # Step 1: Create S3 bucket
        print(f"\n=== Creating S3 Bucket ===")
        s3_bucket.create_s3_bucket(s3_client, bucket_name, region, allow_create)
        
        # Step 2: Configure bucket for website hosting
        print(f"\n=== Configuring S3 Bucket for Website Hosting ===")
        s3_bucket.configure_s3_bucket_for_website(s3_client, bucket_name, allow_create)
        
        # Step 3: Disable Block Public Access
        print(f"\n=== Configuring Block Public Access ===")
        s3_bucket.disable_block_public_access(s3_client, bucket_name, allow_create)
        
        # Step 4: Set bucket policy for public read (for CloudFront)
        print(f"\n=== Setting Bucket Policy ===")
        s3_bucket.set_bucket_policy_for_cloudfront(s3_client, bucket_name, allow_create)
        
        # Step 5: Upload folder contents to S3
        print(f"\n=== Uploading Files to S3 ===")
        s3_bucket.upload_folder_to_s3(s3_client, bucket_name, folder_path)
        
        # Step 6: Handle public domain setup if configured
        if public_config:
            domain = public_config['domain']
            
            print(f"\n=== Setting up Public Domain ===")
            print(f"Domain: {domain}")
            print("Architecture: Route53 -> CloudFront (10 min cache) -> S3")

            # Validate Route53 hosted zone NS delegation before creating any DNS records
            # (avoids ACM validation hanging when registrar points to wrong nameservers)
            route53.ensure_domain_ready_for_dns(route53_client, domain, allow_create=allow_create, yes_flag=yes_flag)

            # Step 5.1: Request/get ACM certificate for CloudFront
            # CloudFront requires certificates to be in us-east-1
            acm_region = 'us-east-1'
            acm_session = boto3.Session(profile_name=profile, region_name=acm_region)
            acm_client = acm_session.client('acm')
            
            print(f"\n=== Setting up SSL Certificate ===")
            
            cert_arn = None
            if certificate_id:
                # Get account ID to construct the full ARN
                sts_client = session.client('sts')
                account_id = sts_client.get_caller_identity().get('Account')
                
                # Construct certificate ARN from ID
                cert_arn = f"arn:aws:acm:{acm_region}:{account_id}:certificate/{certificate_id}"
                
                # Verify the certificate exists and is valid
                try:
                    cert_details = acm_client.describe_certificate(CertificateArn=cert_arn)
                    cert_status = cert_details['Certificate'].get('Status', '')
                    cert_domain = cert_details['Certificate'].get('DomainName', '')
                    
                    print(f"Using specified certificate: {cert_arn}")
                    print(f"  Domain: {cert_domain}")
                    print(f"  Status: {cert_status}")
                    
                    if cert_status != 'ISSUED':
                        print(f"Waiting for certificate to become issued (current status: {cert_status})...")
                        if not acm.wait_for_certificate_validation(acm_client, cert_arn, timeout_minutes=30):
                            print("Error: Certificate did not validate in time. Cannot set up CDN.")
                            sys.exit(1)
                    else:
                        print("Certificate is issued and ready to use!")
                except acm_client.exceptions.ResourceNotFoundException:
                    print(f"Error: Certificate {cert_arn} not found!")
                    sys.exit(1)
                except Exception as e:
                    print(f"Error verifying certificate: {e}")
                    sys.exit(1)
            else:
                # Fall back to requesting/finding certificate by domain
                cert_arn = acm.request_certificate(acm_client, domain, acm_region, allow_create)
                
                # Get validation records
                validation_records = acm.get_certificate_validation_records(acm_client, cert_arn)
                
                if validation_records:
                    print(f"Creating DNS validation records in Route53...")
                    for validation_record in validation_records:
                        if validation_record['status'] != 'SUCCESS':
                            route53.create_validation_record(route53_client, validation_record, allow_create)
                    
                    # Wait for certificate validation
                    print(f"Waiting for certificate validation...")
                    acm.wait_for_certificate_validation(acm_client, cert_arn, timeout_minutes=30)
                else:
                    cert_details = acm_client.describe_certificate(CertificateArn=cert_arn)
                    cert_status = cert_details['Certificate'].get('Status', '')
                    if cert_status == 'ISSUED':
                        print("Certificate is already issued and ready to use!")
                    else:
                        print(f"Waiting for certificate validation (current status: {cert_status})...")
                        if not acm.wait_for_certificate_validation(acm_client, cert_arn, timeout_minutes=30):
                            print("Error: Certificate did not validate in time. Cannot set up CDN.")
                            sys.exit(1)
            
            # Step 5.2: Create CloudFront distribution pointing to S3
            print(f"\n=== Creating CloudFront Distribution ===")
            cf_domain, cf_id = cloudfront_s3.create_cloudfront_distribution_for_s3(
                cloudfront_client, bucket_name, region, domain, region, 
                allow_create, certificate_arn=cert_arn
            )
            
            # Step 5.2.1: Invalidate CloudFront cache after S3 upload
            print(f"\n=== Invalidating CloudFront Cache ===")
            try:
                cloudfront.invalidate_cloudfront_cache(cloudfront_client, cf_id)
            except Exception as e:
                print(f"Warning: Failed to invalidate CloudFront cache: {e}")
                print("  You may need to manually invalidate the cache or wait for TTL to expire")
            
            # Step 5.3: Create Route53 record pointing to CloudFront
            print(f"\n=== Setting up Route53 DNS ===")
            route53.create_or_update_dns_record(
                route53_client, domain, cf_domain, 
                record_type='A', allow_create=allow_create
            )
            
            print(f"\nS3 deployment complete!")
            print(f"  Domain: {domain}")
            print(f"  S3 Bucket: {bucket_name}")
            print(f"  CloudFront: {cf_domain}")
            print(f"  Cache TTL: 10 minutes")
            print(f"  Note: CloudFront may take 15-20 minutes to fully deploy")
            
            # Store CloudFront info for later display
            params['_cloudfront_domain'] = cf_domain
            params['_cloudfront_id'] = cf_id
        else:
            # No public domain - just show S3 bucket info
            print(f"\nS3 deployment complete!")
            print(f"  S3 Bucket: {bucket_name}")
            print(f"  Note: No public domain configured. Access bucket directly or configure 'public' section.")
        
        # Print AWS Console links
        print("\n" + "="*80)
        print("AWS Console Links:")
        print("="*80)
        s3_url = f"https://s3.console.aws.amazon.com/s3/buckets/{bucket_name}?region={region}"
        print(f"\nS3 Bucket:")
        print(f"  {s3_url}")
        
        if public_config:
            print(f"\nPublic Domain:")
            domain_url = f"https://{public_config['domain']}"
            print(f"  {domain_url}")
            # Show CloudFront URL if available
            if '_cloudfront_domain' in params:
                print(f"\nCloudFront Distribution URL:")
                print(f"  https://{params['_cloudfront_domain']}")
        
        print("\n" + "="*80 + "\n")
        
        # Test HTTP requests to verify deployment
        if public_config:
            test_deployment_http_requests(public_config, params)
        
    except Exception as e:
        print(f"Error during deployment: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def test_deployment_http_requests(public_config, params):
    """
    Test HTTP requests to the deployed domain to verify everything works.
    Retries every 10 seconds for up to 10 minutes if checks fail.
    """
    domain = public_config['domain']
    
    print("\n" + "="*80)
    print("Testing Deployment with HTTP Requests")
    print("="*80)
    
    # Wait a bit for CloudFront to be ready
    print("\nWaiting 30 seconds for CloudFront distribution to propagate...")
    time.sleep(30)
    
    # Test URLs to try
    test_urls = [
        f"https://{domain}",
        f"http://{domain}"
    ]
    
    # Also test CloudFront domain if available
    if '_cloudfront_domain' in params:
        test_urls.append(f"https://{params['_cloudfront_domain']}")
    
    total_tests = len(test_urls)
    max_retry_time = 600  # 10 minutes in seconds
    retry_interval = 10  # 10 seconds
    start_time = time.time()
    attempt = 1
    
    while True:
        print(f"\n--- Attempt {attempt} ---")
        success_count = 0
        
        for url in test_urls:
            print(f"\nTesting: {url}")
            try:
                # Create request with timeout
                req = urllib.request.Request(url)
                req.add_header('User-Agent', 'Deployment-Test/1.0')
                
                with urllib.request.urlopen(req, timeout=30) as response:
                    status_code = response.getcode()
                    content_length = response.headers.get('Content-Length', 'unknown')
                    content_type = response.headers.get('Content-Type', 'unknown')
                    
                    if 200 <= status_code < 400:
                        print(f"  ✓ SUCCESS - Status: {status_code}")
                        print(f"    Content-Type: {content_type}")
                        print(f"    Content-Length: {content_length}")
                        success_count += 1
                    else:
                        print(f"  ⚠ WARNING - Status: {status_code}")
                        print(f"    Content-Type: {content_type}")
            except urllib.error.HTTPError as e:
                # HTTP errors (4xx, 5xx) - might still indicate the service is up
                print(f"  ⚠ HTTP Error: {e.code} {e.reason}")
                if e.code < 500:
                    # 4xx errors mean the server is responding
                    print(f"    Server is responding (client error)")
                    success_count += 0.5  # Partial success
            except urllib.error.URLError as e:
                print(f"  ✗ FAILED - {e.reason}")
                print(f"    This might be normal if DNS hasn't propagated yet")
            except Exception as e:
                print(f"  ✗ FAILED - {str(e)}")
        
        print("\n" + "-"*80)
        print(f"Test Results: {success_count}/{total_tests} successful")
        
        # Check if tests passed
        if success_count >= total_tests * 0.5:
            print("✓ Deployment appears to be working!")
            print("="*80 + "\n")
            return
        
        # Check if we've exceeded the retry time limit
        elapsed_time = time.time() - start_time
        if elapsed_time >= max_retry_time:
            print("✗ All tests failed after 10 minutes of retrying")
            print("  Please check:")
            print("  1. DNS propagation (can take a few minutes)")
            print("  2. CloudFront deployment status (can take 15-20 minutes)")
            print("  3. S3 bucket configuration and file uploads")
            print("="*80 + "\n")
            return
        
        # Wait before retrying
        remaining_time = max_retry_time - elapsed_time
        print(f"⚠ Some tests failed - retrying in {retry_interval} seconds...")
        print(f"  (Will continue retrying for up to {int(remaining_time)} more seconds)")
        print("  CloudFront can take 15-20 minutes to fully deploy")
        print("  DNS propagation can take a few minutes")
        time.sleep(retry_interval)
        attempt += 1
