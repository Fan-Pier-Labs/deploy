#!/usr/bin/env python3
"""
Generate CloudFormation template for S3 static website with optional CloudFront + Route53.
"""
import copy


def _ref(logical_id):
    return {"Ref": logical_id}


def _get_att(logical_id, attr):
    return {"Fn::GetAtt": [logical_id, attr]}


def _sub(template, **kwargs):
    return {"Fn::Sub": [template, kwargs] if kwargs else template}


def build_s3_template(config):
    """
    Build CloudFormation template dict for S3 deployment.
    config: parsed user YAML (platform, app_name, aws, s3, public, allow_create).
    """
    app_name = config["app_name"]
    aws_cfg = config.get("aws", {})
    s3_cfg = config.get("s3", {})
    public = config.get("public") or {}
    region = aws_cfg.get("region", "us-east-2")
    # Do not set BucketName: CloudFormation assigns a unique name and avoids
    # ResourceExistenceCheck failures when a bucket with that name already exists.
    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": f"S3 static website and optional CDN for {app_name}",
        "Parameters": {},
        "Resources": {},
        "Outputs": {
            "BucketName": {"Value": _ref("WebsiteBucket"), "Description": "S3 bucket name"},
        },
    }

    # S3 bucket (no BucketName = CF generates unique name)
    template["Resources"]["WebsiteBucket"] = {
        "Type": "AWS::S3::Bucket",
        "Properties": {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
            "WebsiteConfiguration": {
                "IndexDocument": "index.html",
                "ErrorDocument": "index.html",
            },
        },
    }

    # Bucket policy: allow public read (for CloudFront / website)
    template["Resources"]["WebsiteBucketPolicy"] = {
        "Type": "AWS::S3::BucketPolicy",
        "Properties": {
            "Bucket": _ref("WebsiteBucket"),
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "PublicReadGetObject",
                        "Effect": "Allow",
                        "Principal": "*",
                        "Action": "s3:GetObject",
                        "Resource": _sub("arn:aws:s3:::${BucketName}/*", BucketName=_ref("WebsiteBucket")),
                    }
                ],
            },
        },
    }

    domain = public.get("domain") if public else None
    cert_arn_param = public.get("certificate_id")  # optional: existing cert id
    hosted_zone_id = public.get("hosted_zone_id")  # optional: for Route53

    if domain:
        template["Outputs"]["Domain"] = {"Value": domain, "Description": "Public domain"}

        # ACM cert: use parameter if provided, else create one (requires validation in us-east-1)
        # CloudFront requires cert in us-east-1. We add a parameter for CertificateArn (us-east-1).
        template["Parameters"]["CertificateArn"] = {
            "Type": "String",
            "Description": "ACM certificate ARN (must be in us-east-1 for CloudFront). Create in ACM and validate via DNS, then pass here.",
        }
        if cert_arn_param and isinstance(cert_arn_param, str) and not cert_arn_param.isdigit():
            template["Parameters"]["CertificateArn"]["Default"] = cert_arn_param

        # CloudFront origin access identity (optional; we use public bucket for simplicity to match current behavior)
        s3_origin_domain = _sub("${BucketName}.s3.${AWS::Region}.amazonaws.com", BucketName=_ref("WebsiteBucket"))

        template["Resources"]["CloudFrontDistribution"] = {
            "Type": "AWS::CloudFront::Distribution",
            "Properties": {
                "DistributionConfig": {
                    "Aliases": [domain],
                    "DefaultRootObject": "index.html",
                    "Origins": [
                        {
                            "Id": "S3Origin",
                            "DomainName": _get_att("WebsiteBucket", "RegionalDomainName"),
                            "S3OriginConfig": {"OriginAccessIdentity": ""},
                        }
                    ],
                    "DefaultCacheBehavior": {
                        "TargetOriginId": "S3Origin",
                        "ViewerProtocolPolicy": "redirect-to-https",
                        "AllowedMethods": ["GET", "HEAD", "OPTIONS"],
                        "CachedMethods": ["GET", "HEAD"],
                        "Compress": True,
                        "ForwardedValues": {
                            "QueryString": False,
                            "Cookies": {"Forward": "none"},
                            "Headers": [],
                        },
                        "DefaultTTL": 600,
                        "MinTTL": 0,
                        "MaxTTL": 600,
                    },
                    "Enabled": True,
                    "PriceClass": "PriceClass_All",
                    "ViewerCertificate": {
                        "AcmCertificateArn": _ref("CertificateArn"),
                        "SslSupportMethod": "sni-only",
                        "MinimumProtocolVersion": "TLSv1.2_2021",
                    },
                    "HttpVersion": "http2and3",
                },
            },
        }

        template["Outputs"]["CloudFrontDomain"] = {
            "Value": _get_att("CloudFrontDistribution", "DomainName"),
            "Description": "CloudFront distribution domain",
        }
        template["Outputs"]["CloudFrontId"] = {
            "Value": _ref("CloudFrontDistribution"),
            "Description": "CloudFront distribution ID (for cache invalidation)",
        }

        # Route53 A record (alias to CloudFront). HostedZoneId can be in config or passed as stack parameter.
        template["Parameters"]["HostedZoneId"] = {
            "Type": "String",
            "Description": "Route53 hosted zone ID for the domain (e.g. Z1234...). Required for DNS record.",
        }
        if isinstance(hosted_zone_id, str) and hosted_zone_id.strip():
            template["Parameters"]["HostedZoneId"]["Default"] = hosted_zone_id.strip()

        template["Resources"]["DNSRecord"] = {
            "Type": "AWS::Route53::RecordSet",
            "Properties": {
                "HostedZoneId": _ref("HostedZoneId"),
                "Name": domain if domain.endswith(".") else f"{domain}.",
                "Type": "A",
                "AliasTarget": {
                    "DNSName": _get_att("CloudFrontDistribution", "DomainName"),
                    "HostedZoneId": "Z2FDTNDATAQYW2",  # CloudFront hosted zone ID
                    "EvaluateTargetHealth": False,
                },
            },
        }
    else:
        # No public domain: no CertificateArn or HostedZoneId params
        pass

    # Clean up empty Parameters only if we never added any
    if "Parameters" in template and not template["Parameters"]:
        del template["Parameters"]

    return template
