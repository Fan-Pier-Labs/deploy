#!/usr/bin/env python3
"""
CloudFront distribution management.
"""
import sys
import time


def create_cloudfront_distribution(cloudfront_client, alb_dns_name, domain, region, allow_create=False, certificate_arn=None):
    """
    Create a CloudFront distribution that points to an ALB.
    Configured with no caching and forward all headers.
    
    Args:
        certificate_arn: ACM certificate ARN (must be in us-east-1 for CloudFront)
    
    Returns the distribution domain name and ID.
    """
    distribution_name = f"{domain.replace('.', '-')}-cf"
    
    # Check if distribution already exists (by checking comment/aliases)
    # Note: CloudFront doesn't have a direct "get by name" API, so we'll list and search
    try:
        paginator = cloudfront_client.get_paginator('list_distributions')
        for page in paginator.paginate():
            for dist in page.get('DistributionList', {}).get('Items', []):
                if domain in dist.get('Aliases', {}).get('Items', []):
                    dist_id = dist['Id']
                    print(f"Using existing CloudFront distribution: {dist_id}")
                    
                    # Check if distribution needs updates (certificate or origin protocol)
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
                        
                        # Check and update PriceClass to use all edge locations
                        current_price_class = config.get('PriceClass', 'PriceClass_100')
                        if current_price_class != 'PriceClass_All':
                            print(f"Updating CloudFront distribution to use all edge locations (PriceClass_All)...")
                            config['PriceClass'] = 'PriceClass_All'
                            needs_update = True
                        
                        # Check and fix origin protocol policy (should be http-only for ALB with HTTP listener)
                        origins = config.get('Origins', {}).get('Items', [])
                        for origin in origins:
                            if origin.get('Id') == 'alb-origin' or 'alb' in origin.get('Id', '').lower():
                                custom_config = origin.get('CustomOriginConfig', {})
                                current_policy = custom_config.get('OriginProtocolPolicy', '')
                                
                                # Fix if it's set to https-only but ALB only has HTTP listener
                                if current_policy == 'https-only':
                                    print(f"Fixing origin protocol policy: changing from https-only to http-only")
                                    custom_config['OriginProtocolPolicy'] = 'http-only'
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
    
    print(f"Creating CloudFront distribution for domain: {domain}")
    
    # Create distribution configuration
    # No caching: set TTL to 0 and forward all headers
    distribution_config = {
        'CallerReference': f"{domain}-{int(time.time())}",
        'Aliases': {
            'Quantity': 1,
            'Items': [domain]
        },
        'DefaultRootObject': '',
        'Origins': {
            'Quantity': 1,
            'Items': [
                {
                    'Id': 'alb-origin',
                    'DomainName': alb_dns_name,
                    'CustomOriginConfig': {
                        'HTTPPort': 80,
                        'HTTPSPort': 443,
                        'OriginProtocolPolicy': 'http-only',  # Use HTTP since ALB only has HTTP listener
                        'OriginSslProtocols': {
                            'Quantity': 1,
                            'Items': ['TLSv1.2']
                        },
                        'OriginReadTimeout': 60,
                        'OriginKeepaliveTimeout': 5
                    }
                }
            ]
        },
        'DefaultCacheBehavior': {
            'TargetOriginId': 'alb-origin',
            'ViewerProtocolPolicy': 'redirect-to-https',
            'AllowedMethods': {
                'Quantity': 7,
                'Items': ['GET', 'HEAD', 'OPTIONS', 'PUT', 'POST', 'PATCH', 'DELETE'],
                'CachedMethods': {
                    'Quantity': 2,
                    'Items': ['GET', 'HEAD']
                }
            },
            'ForwardedValues': {
                'QueryString': True,
                'Cookies': {
                    'Forward': 'all'
                },
                'Headers': {
                    'Quantity': 1,
                    'Items': ['*']  # Forward all headers
                },
                'QueryStringCacheKeys': {
                    'Quantity': 0,
                    'Items': []
                }
            },
            'MinTTL': 0,
            'DefaultTTL': 0,  # No caching
            'MaxTTL': 0,  # No caching
            'Compress': True,
            'SmoothStreaming': False,
            'FieldLevelEncryptionId': ''
        },
        'Comment': f'CloudFront distribution for {domain}',
        'Enabled': True,
        'PriceClass': 'PriceClass_All',  # Use all edge locations worldwide for best performance
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
        print(f"  Note: Distribution may take 15-20 minutes to deploy")
        
        return distribution_domain, distribution_id
    except Exception as e:
        print(f"Error creating CloudFront distribution: {e}")
        sys.exit(1)


def wait_for_cloudfront_deployment(cloudfront_client, distribution_id, timeout_minutes=20):
    """
    Wait for CloudFront distribution to be deployed.
    """
    print(f"Waiting for CloudFront distribution {distribution_id} to deploy...")
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60
    
    while time.time() - start_time < timeout_seconds:
        try:
            response = cloudfront_client.get_distribution(Id=distribution_id)
            status = response['Distribution']['Status']
            
            if status == 'Deployed':
                print("CloudFront distribution is deployed!")
                return True
            
            print(f"  Status: {status} (waiting...)")
            time.sleep(30)  # Check every 30 seconds
        except Exception as e:
            print(f"Error checking CloudFront status: {e}")
            time.sleep(30)
    
    print(f"Warning: CloudFront distribution did not deploy within {timeout_minutes} minutes")
    print("You may need to wait longer or check the AWS Console")
    return False


def invalidate_cloudfront_cache(cloudfront_client, distribution_id, paths=None):
    """
    Invalidate CloudFront cache for a distribution.
    
    Args:
        cloudfront_client: Boto3 CloudFront client
        distribution_id: CloudFront distribution ID
        paths: List of paths to invalidate. Defaults to ['/*'] to invalidate everything.
    
    Returns the invalidation ID.
    """
    if paths is None:
        paths = ['/*']  # Invalidate entire cache by default
    
    # Create a unique caller reference using timestamp
    caller_reference = f"invalidation-{int(time.time())}"
    
    try:
        print(f"Invalidating CloudFront cache for distribution {distribution_id}...")
        print(f"  Paths: {', '.join(paths)}")
        
        response = cloudfront_client.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                'Paths': {
                    'Quantity': len(paths),
                    'Items': paths
                },
                'CallerReference': caller_reference
            }
        )
        
        invalidation_id = response['Invalidation']['Id']
        status = response['Invalidation']['Status']
        
        print(f"✓ Cache invalidation created: {invalidation_id}")
        print(f"  Status: {status}")
        print(f"  Note: Invalidation typically completes within 1-2 minutes")
        
        return invalidation_id
    except Exception as e:
        print(f"Error creating cache invalidation: {e}")
        raise
