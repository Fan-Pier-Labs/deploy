#!/usr/bin/env python3
"""
Route53 domain and DNS record management.
"""
import sys


def find_hosted_zone(route53_client, domain):
    """
    Find the hosted zone for a given domain or subdomain.
    Returns the hosted zone ID and the record name to create.
    
    For example:
    - domain='sub.example.com' -> finds zone for 'example.com', returns record_name='sub'
    - domain='example.com' -> finds zone for 'example.com', returns record_name='@' or ''
    """
    # Split domain into parts
    parts = domain.split('.')
    
    # Try to find hosted zone starting from full domain, then parent domains
    for i in range(len(parts)):
        # Try domain at this level (e.g., 'sub.example.com', then 'example.com', then 'com')
        test_domain = '.'.join(parts[i:])
        
        # List hosted zones
        paginator = route53_client.get_paginator('list_hosted_zones')
        for page in paginator.paginate():
            for zone in page['HostedZones']:
                zone_name = zone['Name'].rstrip('.')
                
                # Check if this zone matches our domain
                if zone_name == test_domain:
                    # Determine the record name
                    if i == 0:
                        # Exact match - this is the apex domain
                        record_name = domain
                    else:
                        # Subdomain - record name is the subdomain part
                        record_name = '.'.join(parts[:i])
                    
                    return zone['Id'], record_name, zone_name
    
    # No hosted zone found
    return None, None, None


def get_existing_record(route53_client, hosted_zone_id, record_name, record_type):
    """
    Get existing DNS record if it exists.
    Returns the record or None.
    """
    try:
        response = route53_client.list_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            StartRecordName=record_name,
            StartRecordType=record_type,
            MaxItems='1'
        )
        
        for record_set in response.get('ResourceRecordSets', []):
            if record_set['Name'].rstrip('.') == record_name.rstrip('.') and record_set['Type'] == record_type:
                return record_set
        
        return None
    except Exception as e:
        print(f"Error checking existing record: {e}")
        return None


def create_or_update_dns_record(route53_client, domain, target_value, record_type='CNAME', ttl=0, allow_create=False):
    """
    Create or update a DNS record for the given domain.
    Only modifies CNAME, A, or AAAA records for the specific domain/subdomain.
    
    Args:
        domain: The domain or subdomain (e.g., 'sub.example.com' or 'example.com')
        target_value: The value to point to (e.g., CloudFront distribution domain or ALB DNS name)
        record_type: 'CNAME', 'A', or 'AAAA'
        ttl: TTL in seconds
        allow_create: Whether to create or modify DNS records. If False, will exit if record needs to be created or updated.
    """
    # Find the hosted zone
    hosted_zone_id, record_name, zone_name = find_hosted_zone(route53_client, domain)
    
    if not hosted_zone_id:
        print(f"Error: Could not find Route53 hosted zone for domain: {domain}")
        print("Please ensure the domain is managed by Route53 in this AWS account.")
        sys.exit(1)
    
    print(f"Found hosted zone: {zone_name} (ID: {hosted_zone_id})")
    
    # Normalize record name
    if record_name == domain:
        # Apex domain - use '@' notation
        full_record_name = zone_name
    else:
        # Subdomain - append to zone name
        full_record_name = f"{record_name}.{zone_name}"
    
    # Ensure it ends with a dot
    if not full_record_name.endswith('.'):
        full_record_name += '.'
    
    # Check if record already exists
    existing_record = get_existing_record(route53_client, hosted_zone_id, full_record_name, record_type)
    
    if existing_record:
        # Check if resource creation/modification is allowed
        if not allow_create:
            print(f"DNS record '{full_record_name}' exists but resource modification is disabled.")
            sys.exit(1)
        
        # Update existing record
        print(f"Updating existing {record_type} record: {full_record_name}")
        
        # Prepare the change
        change_batch = {
            'Changes': [
                {
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': full_record_name,
                        'Type': record_type,
                        'TTL': ttl,
                        'ResourceRecords': [
                            {'Value': target_value}
                        ]
                    }
                }
            ]
        }
        
        # For A records pointing to CloudFront, use ALIAS instead
        if record_type == 'A' and 'cloudfront.net' in target_value:
            # Ensure DNS name ends with dot for ALIAS
            dns_name = target_value.rstrip('.')
            if not dns_name.endswith('.'):
                dns_name += '.'
            change_batch['Changes'][0]['ResourceRecordSet'] = {
                'Name': full_record_name,
                'Type': 'A',
                'AliasTarget': {
                    'HostedZoneId': 'Z2FDTNDATAQYW2',  # CloudFront hosted zone ID
                    'DNSName': dns_name,
                    'EvaluateTargetHealth': False
                }
            }
        
        route53_client.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch=change_batch
        )
        print(f"Updated {record_type} record: {full_record_name} -> {target_value}")
    else:
        if not allow_create:
            print(f"DNS record '{full_record_name}' does not exist and resource creation is disabled.")
            sys.exit(1)
        
        # Create new record
        print(f"Creating new {record_type} record: {full_record_name}")
        
        change_batch = {
            'Changes': [
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'Name': full_record_name,
                        'Type': record_type,
                        'TTL': ttl,
                        'ResourceRecords': [
                            {'Value': target_value}
                        ]
                    }
                }
            ]
        }
        
        # For A records pointing to CloudFront, use ALIAS instead
        if record_type == 'A' and 'cloudfront.net' in target_value:
            # Ensure DNS name ends with dot for ALIAS
            dns_name = target_value.rstrip('.')
            if not dns_name.endswith('.'):
                dns_name += '.'
            change_batch['Changes'][0]['ResourceRecordSet'] = {
                'Name': full_record_name,
                'Type': 'A',
                'AliasTarget': {
                    'HostedZoneId': 'Z2FDTNDATAQYW2',  # CloudFront hosted zone ID
                    'DNSName': dns_name,
                    'EvaluateTargetHealth': False
                }
            }
        
        route53_client.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch=change_batch
        )
        print(f"Created {record_type} record: {full_record_name} -> {target_value}")


def create_validation_record(route53_client, validation_record, allow_create=False):
    """
    Create a DNS validation record for ACM certificate validation.
    
    Args:
        validation_record: Dict with 'name', 'type', and 'value' keys
        allow_create: Whether to create the record if it doesn't exist
    """
    record_name = validation_record['name'].rstrip('.')
    record_type = validation_record['type']
    record_value = validation_record['value']
    
    # Extract domain from record name (validation records are like _abc123.example.com)
    # Find the hosted zone
    parts = record_name.split('.')
    domain_found = False
    
    for i in range(len(parts)):
        test_domain = '.'.join(parts[i:])
        hosted_zone_id, _, zone_name = find_hosted_zone(route53_client, test_domain)
        
        if hosted_zone_id:
            domain_found = True
            # The record name should be relative to the zone
            if i == 0:
                full_record_name = record_name
            else:
                # This shouldn't happen for validation records, but handle it
                full_record_name = record_name
            
            if not full_record_name.endswith('.'):
                full_record_name += '.'
            
            # Check if record already exists
            existing = get_existing_record(route53_client, hosted_zone_id, full_record_name, record_type)
            
            if existing:
                # Record already exists, no modification needed
                print(f"Validation record already exists: {full_record_name}")
                return
            
            if not allow_create:
                print(f"Validation record '{full_record_name}' does not exist and resource creation is disabled.")
                sys.exit(1)
            
            print(f"Creating ACM validation record: {full_record_name}")
            
            change_batch = {
                'Changes': [
                    {
                        'Action': 'UPSERT',
                        'ResourceRecordSet': {
                            'Name': full_record_name,
                            'Type': record_type,
                            'TTL': 0,
                            'ResourceRecords': [
                                {'Value': record_value}
                            ]
                        }
                    }
                ]
            }
            
            route53_client.change_resource_record_sets(
                HostedZoneId=hosted_zone_id,
                ChangeBatch=change_batch
            )
            print(f"Created validation record: {full_record_name}")
            return
    
    if not domain_found:
        print(f"Error: Could not find Route53 hosted zone for validation record: {record_name}")
        print("Please ensure the domain is managed by Route53 in this AWS account.")
        sys.exit(1)
