#!/usr/bin/env python3
"""
CloudFront distribution management for S3 buckets.
"""
import sys
import time


def create_cloudfront_distribution_for_s3(cloudfront_client, s3_bucket_name, s3_region, domain, region, allow_create=False, certificate_arn=None):
    """
    Create a CloudFront distribution that points to an S3 bucket.
    Configured with 10 minute cache (600 seconds).
    
    Args:
        s3_bucket_name: Name of the S3 bucket
        s3_region: Region where the S3 bucket is located
        domain: Domain name for the distribution
        region: AWS region (for reference)
        certificate_arn: ACM certificate ARN (must be in us-east-1 for CloudFront)
    
    Returns the distribution domain name and ID.
    """
    # Check if distribution already exists (by checking comment/aliases)
    try:
        paginator = cloudfront_client.get_paginator('list_distributions')
        for page in paginator.paginate():
            for dist in page.get('DistributionList', {}).get('Items', []):
                if domain in dist.get('Aliases', {}).get('Items', []):
                    dist_id = dist['Id']
                    print(f"Using existing CloudFront distribution: {dist_id}")
                    
                    # Check if distribution needs updates
                    try:
                        dist_config = cloudfront_client.get_distribution_config(Id=dist_id)
                        config = dist_config['DistributionConfig']
                        needs_update = False
                        etag = dist_config['ETag']
                        
                        # Check and update certificate if needed
                        if certificate_arn:
                            current_cert = config['ViewerCertificate']
                            if current_cert.get('ACMCertificateArn') != certificate_arn:
                                print(f"Updating CloudFront distribution with new certificate...")
                                config['ViewerCertificate'] = {
                                    'ACMCertificateArn': certificate_arn,
                                    'SSLSupportMethod': 'sni-only',
                                    'MinimumProtocolVersion': 'TLSv1.2_2021',
                                }
                                needs_update = True
                        
                        # Check and update cache TTL to 10 minutes (600 seconds)
                        cache_behavior = config.get('DefaultCacheBehavior', {})
                        if cache_behavior.get('DefaultTTL', 0) != 600:
                            print(f"Updating CloudFront distribution cache TTL to 10 minutes...")
                            cache_behavior['DefaultTTL'] = 600
                            cache_behavior['MinTTL'] = 0
                            cache_behavior['MaxTTL'] = 600
                            config['DefaultCacheBehavior'] = cache_behavior
                            needs_update = True
                        
                        if needs_update:
                            cloudfront_client.update_distribution(
                                Id=dist_id,
                                DistributionConfig=config,
                                IfMatch=etag
                            )
                            print("CloudFront distribution updated successfully")
                            print("Note: Distribution update may take 15-20 minutes to deploy")
                    except Exception as e:
                        print(f"Note: Could not update existing distribution: {e}")
                    
                    return dist['DomainName'], dist_id
    except Exception as e:
        print(f"Note: Could not check for existing distributions: {e}")
    
    if not allow_create:
        print(f"CloudFront distribution does not exist and resource creation is disabled.")
        sys.exit(1)
    
    print(f"Creating CloudFront distribution for S3 bucket: {s3_bucket_name}")
    
    # S3 origin domain name
    s3_origin_domain = f"{s3_bucket_name}.s3.{s3_region}.amazonaws.com"
    
    # Create distribution configuration
    # 10 minute cache: set TTL to 600 seconds
    distribution_config = {
        'CallerReference': f"{domain}-{int(time.time())}",
        'Aliases': {
            'Quantity': 1,
            'Items': [domain]
        },
        'DefaultRootObject': 'index.html',
        'Origins': {
            'Quantity': 1,
            'Items': [
                {
                    'Id': 's3-origin',
                    'DomainName': s3_origin_domain,
                    'S3OriginConfig': {
                        'OriginAccessIdentity': ''  # Empty for public bucket access
                    }
                }
            ]
        },
        'DefaultCacheBehavior': {
            'TargetOriginId': 's3-origin',
            'ViewerProtocolPolicy': 'redirect-to-https',
            'AllowedMethods': {
                'Quantity': 2,
                'Items': ['GET', 'HEAD'],
                'CachedMethods': {
                    'Quantity': 2,
                    'Items': ['GET', 'HEAD']
                }
            },
            'ForwardedValues': {
                'QueryString': False,
                'Cookies': {
                    'Forward': 'none'
                },
                'Headers': {
                    'Quantity': 0,
                    'Items': []
                }
            },
            'MinTTL': 0,
            'DefaultTTL': 600,  # 10 minutes cache
            'MaxTTL': 600,  # 10 minutes cache
            'Compress': True,
            'SmoothStreaming': False,
            'FieldLevelEncryptionId': ''
        },
        'Comment': f'CloudFront distribution for S3 bucket {s3_bucket_name}',
        'Enabled': True,
        'PriceClass': 'PriceClass_All',  # Use all edge locations worldwide
        'ViewerCertificate': (
            {
                'ACMCertificateArn': certificate_arn,
                'SSLSupportMethod': 'sni-only',
                'MinimumProtocolVersion': 'TLSv1.2_2021',
            } if certificate_arn else {
                'CloudFrontDefaultCertificate': True
            }
        ),
        'Restrictions': {
            'GeoRestriction': {
                'RestrictionType': 'none',
                'Quantity': 0
            }
        },
        'HttpVersion': 'http2and3',
        'IsIPV6Enabled': True
    }
    
    try:
        response = cloudfront_client.create_distribution(DistributionConfig=distribution_config)
        distribution_id = response['Distribution']['Id']
        distribution_domain = response['Distribution']['DomainName']
        
        print(f"Created CloudFront distribution: {distribution_id}")
        print(f"  Domain: {distribution_domain}")
        print(f"  Cache TTL: 10 minutes (600 seconds)")
        print(f"  Note: Distribution may take 15-20 minutes to deploy")
        
        return distribution_domain, distribution_id
    except Exception as e:
        print(f"Error creating CloudFront distribution: {e}")
        sys.exit(1)
