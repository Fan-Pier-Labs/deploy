#!/usr/bin/env python3
"""
Route53 domain and DNS record management.
"""
import sys
import subprocess


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


def get_hosted_zone_ns(route53_client, hosted_zone_id, zone_name):
    """
    Get the NS records for a hosted zone (what the zone delegates to).
    zone_name should be the zone name as returned by find_hosted_zone (no trailing dot).
    Returns a sorted list of NS hostnames (lowercase, no trailing dot).
    """
    zone_name_dot = zone_name.rstrip('.') + '.'
    try:
        response = route53_client.list_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            StartRecordName=zone_name_dot,
            StartRecordType='NS',
            MaxItems='1'
        )
        for record_set in response.get('ResourceRecordSets', []):
            if record_set['Name'].rstrip('.') == zone_name.rstrip('.') and record_set['Type'] == 'NS':
                ns_values = [
                    rr['Value'].rstrip('.').lower()
                    for rr in record_set.get('ResourceRecords', [])
                ]
                return sorted(ns_values)
        return []
    except Exception as e:
        print(f"Error getting hosted zone NS records: {e}")
        return []


def get_public_ns_for_domain(domain):
    """
    Perform a public DNS lookup for the domain's NS records.
    Returns a sorted list of NS hostnames (lowercase, no trailing dot), or [] if lookup fails.
    """
    domain_clean = domain.rstrip('.')
    # Prefer dig (clean one-name-per-line output)
    try:
        result = subprocess.run(
            ['dig', 'NS', domain_clean, '+short'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            ns_list = [
                line.strip().rstrip('.').lower()
                for line in result.stdout.strip().splitlines()
                if line.strip() and not line.strip().startswith(';')
            ]
            return sorted(set(ns_list))
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    # Fallback: nslookup (output has "nameserver = host" lines)
    try:
        result = subprocess.run(
            ['nslookup', '-type=NS', domain_clean],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and (result.stdout.strip() or result.stderr.strip()):
            out = (result.stdout or '') + (result.stderr or '')
            ns_list = []
            for line in out.splitlines():
                line = line.strip()
                if 'nameserver' in line.lower() and '=' in line:
                    # e.g. "example.com	nameserver = ns-123.awsdns-12.com."
                    part = line.split('=', 1)[-1].strip().rstrip('.').lower()
                    if part and not part.startswith('#'):
                        ns_list.append(part)
            if ns_list:
                return sorted(set(ns_list))
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return []


def validate_ns_delegation(route53_client, domain, hosted_zone_id=None, zone_name=None):
    """
    Check that the domain's public NS records match the Route53 hosted zone's NS records.
    This prevents ACM validation from hanging when the registrar points to stale/wrong nameservers.

    Returns:
        (ok: bool, message: str, route53_ns: list, public_ns: list)
    """
    if hosted_zone_id is None or zone_name is None:
        hosted_zone_id, _, zone_name = find_hosted_zone(route53_client, domain)
    if not hosted_zone_id or not zone_name:
        return False, f"No Route53 hosted zone found for {domain}", [], []

    route53_ns = get_hosted_zone_ns(route53_client, hosted_zone_id, zone_name)
    if not route53_ns:
        return False, f"Could not read NS records from Route53 hosted zone for {zone_name}", [], []

    # Public NS is for the zone (apex), e.g. example.com for app.example.com
    public_ns = get_public_ns_for_domain(zone_name)
    if not public_ns:
        return False, (
            f"Could not perform public DNS lookup for {zone_name}. "
            "Ensure 'dig' or 'nslookup' is available and the domain resolves."
        ), route53_ns, []

    if set(route53_ns) == set(public_ns):
        return True, "NS delegation matches.", route53_ns, public_ns

    return False, (
        f"NS delegation mismatch: your registrar is not pointing {zone_name} to this Route53 hosted zone. "
        "ACM DNS validation will hang until the domain delegates to this zone's nameservers."
    ), route53_ns, public_ns


def ensure_hosted_zone_for_domain(route53_client, domain, allow_create=False):
    """
    Ensure a Route53 hosted zone exists for the domain (uses apex zone for subdomains).
    If none exists and allow_create is True, create a public hosted zone for the apex domain.

    Returns:
        (hosted_zone_id, zone_name, created: bool, route53_ns_list)
    """
    hosted_zone_id, _, zone_name = find_hosted_zone(route53_client, domain)
    if hosted_zone_id:
        ns_list = get_hosted_zone_ns(route53_client, hosted_zone_id, zone_name)
        return hosted_zone_id, zone_name, False, ns_list

    if not allow_create:
        return None, None, False, []

    # Determine apex domain (e.g. sub.example.com -> example.com)
    parts = domain.split('.')
    if len(parts) < 2:
        print(f"Error: Cannot create hosted zone for invalid domain: {domain}")
        sys.exit(1)
    apex = '.'.join(parts[-2:])  # example.com
    apex_with_dot = apex if apex.endswith('.') else apex + '.'

    import uuid
    caller_ref = str(uuid.uuid4())
    try:
        response = route53_client.create_hosted_zone(
            Name=apex_with_dot,
            CallerReference=caller_ref,
        )
        zone = response['HostedZone']
        hosted_zone_id = zone['Id']
        # Zone name from API has trailing dot
        zone_name = zone['Name'].rstrip('.')
        delegation = response.get('DelegationSet', {})
        ns_list = [ns.rstrip('.').lower() for ns in delegation.get('NameServers', [])]
        print(f"Created Route53 hosted zone for {zone_name}: {hosted_zone_id}")
        print(f"Nameservers for this zone: {', '.join(ns_list)}")
        return hosted_zone_id, zone_name, True, sorted(ns_list)
    except Exception as e:
        print(f"Error creating hosted zone for {apex}: {e}")
        sys.exit(1)


def confirm_ns_delegation_changes(route53_ns_list, zone_name, yes_flag=False):
    """
    Ask the user to confirm they will update (or have updated) their registrar
    to use the given nameservers. If yes_flag is True, skip prompt and return True.
    Returns True if user confirms, False otherwise.
    """
    if yes_flag:
        return True
    print(f"\nUpdate your domain registrar for {zone_name} to use these nameservers:")
    for ns in route53_ns_list:
        print(f"  {ns}")
    print("\nAfter updating, DNS may take a few minutes to propagate.")
    try:
        reply = input("Type 'yes' to continue (we will create DNS records and wait for ACM validation): ").strip().lower()
        return reply == 'yes'
    except EOFError:
        return False


def ensure_domain_ready_for_dns(route53_client, domain, allow_create=False, yes_flag=False):
    """
    Validate Route53 hosted zone NS delegation before creating any DNS records.
    If no hosted zone exists and allow_create is True, create one. If NS delegation
    does not match (registrar pointing elsewhere), prompt user to update registrar
    and confirm before proceeding. This avoids ACM validation hanging.

    Call this before create_validation_record or create_or_update_dns_record when
    using a public domain.
    """
    hosted_zone_id, zone_name, created, route53_ns = ensure_hosted_zone_for_domain(
        route53_client, domain, allow_create
    )
    if not hosted_zone_id:
        print(f"Error: No Route53 hosted zone for {domain}. Create one or set allow_create=True.")
        sys.exit(1)

    ok, message, r53_ns, public_ns = validate_ns_delegation(
        route53_client, domain, hosted_zone_id=hosted_zone_id, zone_name=zone_name
    )
    if ok:
        print(f"NS delegation OK for {zone_name}.")
        return

    print(f"\nWarning: {message}")
    print(f"  Route53 hosted zone NS: {r53_ns}")
    if public_ns:
        print(f"  Current public NS:    {public_ns}")
    if created:
        print("  (We just created this hosted zone; point your registrar to the Route53 nameservers above.)")
    if not confirm_ns_delegation_changes(r53_ns, zone_name, yes_flag=yes_flag):
        print("Aborted. Update your registrar nameservers and run deploy again.")
        sys.exit(1)
    print("Continuing with DNS record creation...")


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
