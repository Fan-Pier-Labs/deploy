#!/usr/bin/env python3
"""
Script to fix existing CloudFront distribution origin protocol policy.
Run this to update an existing distribution to use HTTP instead of HTTPS for ALB origin.
"""
import sys
import boto3
import argparse

def fix_cloudfront_origin_protocol(distribution_id, region='us-east-2', profile='personal'):
    """
    Fix CloudFront distribution to use HTTP instead of HTTPS for ALB origin.
    """
    session = boto3.Session(profile_name=profile, region_name=region)
    cloudfront_client = session.client('cloudfront')
    
    try:
        # Get current distribution config
        dist_config = cloudfront_client.get_distribution_config(Id=distribution_id)
        config = dist_config['DistributionConfig']
        etag = dist_config['ETag']
        
        # Find and update origin protocol policy
        origins = config.get('Origins', {}).get('Items', [])
        updated = False
        
        for origin in origins:
            custom_config = origin.get('CustomOriginConfig', {})
            if custom_config:
                current_policy = custom_config.get('OriginProtocolPolicy', '')
                if current_policy == 'https-only':
                    print(f"Found origin '{origin.get('Id')}' with https-only policy")
                    print("Updating to http-only...")
                    custom_config['OriginProtocolPolicy'] = 'http-only'
                    updated = True
        
        if updated:
            # Update the distribution
            cloudfront_client.update_distribution(
                Id=distribution_id,
                DistributionConfig=config,
                IfMatch=etag
            )
            print(f"Successfully updated CloudFront distribution: {distribution_id}")
            print("Note: Changes may take 15-20 minutes to deploy")
        else:
            print("No changes needed - origin protocol policy is already correct")
            
    except Exception as e:
        print(f"Error updating CloudFront distribution: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Fix CloudFront origin protocol policy')
    parser.add_argument('--distribution-id', required=True, help='CloudFront distribution ID')
    parser.add_argument('--region', default='us-east-2', help='AWS region')
    parser.add_argument('--profile', default='personal', help='AWS profile')
    
    args = parser.parse_args()
    fix_cloudfront_origin_protocol(args.distribution_id, args.region, args.profile)
