#!/usr/bin/env python3
"""
Resolve ACM certificate ARN using Python (boto3) outside CloudFormation.
- Finds existing cert (exact or wildcard match).
- If not found and allow_create: requests cert, creates Route53 validation records, waits for validation.
CloudFront requires certs in us-east-1.
"""
import sys

# ACM + Route53 use boto3
try:
    import boto3
except ImportError:
    boto3 = None


def _session(profile):
    if not boto3:
        raise RuntimeError("boto3 is required for automatic ACM/Route53. Install with: pip install boto3")
    if profile and profile != "default":
        return boto3.Session(profile_name=profile)
    return boto3.Session()


def _acm_client(profile, region="us-east-1"):
    return _session(profile).client("acm", region_name=region)


def _route53_client(profile, region=None):
    kwargs = {}
    if region:
        kwargs["region_name"] = region
    return _session(profile).client("route53", **kwargs)


def find_certificate(acm_client, domain):
    """
    Find an existing ACM certificate for the domain (exact or wildcard).
    Returns certificate ARN if found, None otherwise.
    """
    from aws.acm import find_certificate as _find
    return _find(acm_client, domain, acm_client.meta.region_name)


def request_and_validate_certificate(acm_client, route53_client, domain, allow_create, timeout_minutes=30):
    """
    Request ACM cert for domain (wildcard for subdomains), create Route53 validation records, wait for validation.
    Returns certificate ARN.
    """
    from aws.acm import (
        request_certificate,
        get_certificate_validation_records,
        wait_for_certificate_validation,
    )
    from aws.route53 import create_validation_record

    cert_arn = request_certificate(acm_client, domain, acm_client.meta.region_name, allow_create=allow_create)
    records = get_certificate_validation_records(acm_client, cert_arn)
    for rec in records:
        if rec.get("status") != "SUCCESS":
            create_validation_record(route53_client, rec, allow_create=allow_create)
    wait_for_certificate_validation(acm_client, cert_arn, timeout_minutes=timeout_minutes)
    return cert_arn


def resolve_cert_arn(profile, domain, allow_create=True, region_hint="us-east-2"):
    """
    Resolve ACM certificate ARN for CloudFront (must be us-east-1).
    1. Try to find existing cert (exact or wildcard) in us-east-1.
    2. If not found and allow_create: request cert, create Route53 validation records, wait for validation.
    Returns certificate ARN (string).
    """
    acm_region = "us-east-1"  # CloudFront requirement
    acm = _acm_client(profile, acm_region)
    route53 = _route53_client(profile, region_hint)

    existing = find_certificate(acm, domain)
    if existing:
        return existing

    if not allow_create:
        print("Error: No certificate found for domain and allow_create is false.", file=sys.stderr)
        sys.exit(1)

    return request_and_validate_certificate(acm, route53, domain, allow_create=True)
