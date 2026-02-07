#!/usr/bin/env python3
"""
Teardown S3 deployment infrastructure so it can be re-built on next deploy.
Destroys: CloudFront distribution (by domain), Route53 A record, S3 bucket and contents.
"""
import sys
import time
import boto3
from botocore.exceptions import ClientError

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from aws import route53
from aws import cloudfront


def _resolve_bucket_name(config_dict):
    """Resolve bucket name from config (same logic as deploy.py)."""
    app_name = config_dict.get('app_name')
    bucket_name = config_dict.get('bucket_name')
    if bucket_name:
        return bucket_name.lower().strip()
    name = f"{app_name}-static-site".lower().replace('_', '-')
    name = ''.join(c for c in name if c.isalnum() or c in ['-', '.'])
    name = name.strip('.-')
    if len(name) > 63:
        name = name[:63].rstrip('.-')
    if len(name) < 3:
        name = f"{name}-site"[:63]
    return name


def _find_cloudfront_by_domain(cloudfront_client, domain):
    """Return (distribution_id, etag) for the distribution with this domain alias, or (None, None)."""
    try:
        paginator = cloudfront_client.get_paginator('list_distributions')
        for page in paginator.paginate():
            for dist in page.get('DistributionList', {}).get('Items', []):
                if domain in dist.get('Aliases', {}).get('Items', []):
                    dist_id = dist['Id']
                    config = cloudfront_client.get_distribution_config(Id=dist_id)
                    return dist_id, config['ETag']
    except Exception as e:
        print(f"Warning: Could not list CloudFront distributions: {e}")
    return None, None


def _disable_cloudfront_and_wait(cloudfront_client, dist_id, timeout_minutes=25):
    """Disable distribution and wait until Status is Deployed (required before delete)."""
    try:
        config_resp = cloudfront_client.get_distribution_config(Id=dist_id)
        etag = config_resp['ETag']
        config = config_resp['DistributionConfig']
        config['Enabled'] = False
        cloudfront_client.update_distribution(Id=dist_id, DistributionConfig=config, IfMatch=etag)
        print(f"  CloudFront distribution {dist_id} disabled; waiting for deployment...")
    except Exception as e:
        print(f"  Warning: Could not disable CloudFront: {e}")
        return False
    return cloudfront.wait_for_cloudfront_deployment(cloudfront_client, dist_id, timeout_minutes=timeout_minutes)


def _delete_route53_record_for_domain(route53_client, domain, record_type='A'):
    """Delete the A (or given type) record for this domain if it exists."""
    hosted_zone_id, record_name, zone_name = route53.find_hosted_zone(route53_client, domain)
    if not hosted_zone_id:
        return False
    if record_name == domain:
        full_record_name = zone_name
    else:
        full_record_name = f"{record_name}.{zone_name}"
    if not full_record_name.endswith('.'):
        full_record_name += '.'
    existing = route53.get_existing_record(route53_client, hosted_zone_id, full_record_name, record_type)
    if not existing:
        return False
    route53_client.change_resource_record_sets(
        HostedZoneId=hosted_zone_id,
        ChangeBatch={'Changes': [{'Action': 'DELETE', 'ResourceRecordSet': existing}]}
    )
    return True


def _empty_and_delete_bucket(s3_client, bucket_name):
    """Delete all object versions (and delete markers) then delete the bucket."""
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        if e.response['Error']['Code'] in ('404', 'NoSuchBucket'):
            return True
        raise
    # List and delete all objects (v2 supports pagination)
    paginator = s3_client.get_paginator('list_objects_v2')
    n = 0
    for page in paginator.paginate(Bucket=bucket_name):
        keys = [{'Key': obj['Key']} for obj in page.get('Contents', [])]
        if keys:
            s3_client.delete_objects(Bucket=bucket_name, Delete={'Objects': keys})
            n += len(keys)
    if n:
        print(f"  Deleted {n} objects from bucket {bucket_name}")
    s3_client.delete_bucket(Bucket=bucket_name)
    return True


def destroy_s3_infra(config_dict, confirm_callback=None):
    """
    Teardown all S3 deploy infrastructure for this config.
    - CloudFront distribution (alias = public domain)
    - Route53 A record for public domain
    - S3 bucket and all objects

    confirm_callback: if provided, called with list of resource descriptions; should return True to proceed.
    If not provided, prompts stdin: "Type 'yes' to confirm destruction:"
    """
    app_name = config_dict.get('app_name')
    region = config_dict.get('region')
    profile = config_dict.get('profile', 'personal')
    public_config = config_dict.get('public')
    bucket_name = _resolve_bucket_name(config_dict)

    session = boto3.Session(profile_name=profile, region_name=region)
    s3_client = session.client('s3')
    route53_client = session.client('route53')
    cloudfront_client = session.client('cloudfront')

    to_destroy = []
    cf_id = None

    # S3 bucket
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        to_destroy.append(f"  - S3 bucket: {bucket_name} (and all objects)")
    except ClientError as e:
        if e.response['Error']['Code'] in ('404', 'NoSuchBucket'):
            to_destroy.append(f"  - S3 bucket: {bucket_name} (not found, skip)")
        else:
            raise

    if public_config:
        domain = public_config.get('domain')
        if domain:
            cf_id, _ = _find_cloudfront_by_domain(cloudfront_client, domain)
            if cf_id:
                to_destroy.append(f"  - CloudFront distribution: {cf_id} (alias: {domain})")
            else:
                to_destroy.append(f"  - CloudFront: none found for domain {domain}")
            to_destroy.append(f"  - Route53 A record: {domain} -> CloudFront")

    print("\n" + "=" * 60)
    print("DESTROY: The following will be permanently removed")
    print("=" * 60)
    for line in to_destroy:
        print(line)
    print("=" * 60)

    if confirm_callback:
        if not confirm_callback(to_destroy):
            print("Aborted.")
            sys.exit(0)
    else:
        try:
            answer = input("Type 'yes' to confirm destruction: ").strip().lower()
        except EOFError:
            answer = ""
        if answer != 'yes':
            print("Aborted.")
            sys.exit(0)

    print("\n=== Tearing down ===\n")

    # 1. CloudFront: disable, wait, delete
    if public_config and cf_id:
        domain = public_config['domain']
        print("Disabling CloudFront distribution...")
        if _disable_cloudfront_and_wait(cloudfront_client, cf_id):
            try:
                etag = cloudfront_client.get_distribution_config(Id=cf_id)['ETag']
                cloudfront_client.delete_distribution(Id=cf_id, IfMatch=etag)
                print(f"  Deleted CloudFront distribution {cf_id}")
            except Exception as e:
                print(f"  Error deleting CloudFront: {e}")
        else:
            print("  CloudFront did not reach Deployed state; skipping delete (run destroy again later)")

    # 2. Route53: delete A record for domain
    if public_config and public_config.get('domain'):
        domain = public_config['domain']
        print(f"Deleting Route53 A record for {domain}...")
        if _delete_route53_record_for_domain(route53_client, domain, 'A'):
            print(f"  Deleted A record for {domain}")
        else:
            print(f"  No A record found for {domain} (or zone not found)")

    # 3. S3: empty bucket and delete
    print(f"Deleting S3 bucket {bucket_name}...")
    try:
        _empty_and_delete_bucket(s3_client, bucket_name)
        print(f"  Deleted bucket {bucket_name}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchBucket':
            print(f"  Bucket {bucket_name} already gone")
        else:
            print(f"  Error: {e}")
            sys.exit(1)

    print("\nTeardown complete. You can re-deploy with the same config to recreate infrastructure.")
