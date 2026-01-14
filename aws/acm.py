#!/usr/bin/env python3
"""
AWS Certificate Manager (ACM) certificate management.
"""
import sys
import time


def find_certificate(acm_client, domain, region):
    """
    Find an existing ACM certificate for the domain.
    Checks for both exact matches and wildcard certificates.
    Returns the certificate ARN if found, None otherwise.
    """
    # ACM certificates are region-specific
    # For CloudFront, certificates must be in us-east-1
    # For ALB, certificates can be in any region
    
    # Determine if this is a subdomain and what the wildcard would be
    parts = domain.split('.')
    is_subdomain = len(parts) > 2
    wildcard_domain = None
    if is_subdomain:
        # For sub.example.com, wildcard would be *.example.com
        wildcard_domain = '*.' + '.'.join(parts[1:])
        parent_domain = '.'.join(parts[1:])
    else:
        parent_domain = domain
    
    try:
        paginator = acm_client.get_paginator('list_certificates')
        for page in paginator.paginate():
            for cert_summary in page.get('CertificateSummaryList', []):
                cert_arn = cert_summary['CertificateArn']
                
                # Get certificate details to check domain
                try:
                    cert_details = acm_client.describe_certificate(CertificateArn=cert_arn)
                    cert = cert_details['Certificate']
                    
                    # Check certificate status first
                    status = cert.get('Status', '')
                    if status not in ['ISSUED', 'PENDING_VALIDATION']:
                        continue
                    
                    # Get all domain names covered by this certificate
                    cert_domain = cert.get('DomainName', '')
                    domain_names = cert.get('SubjectAlternativeNames', [])
                    all_domains = [cert_domain] + domain_names
                    
                    # Check for exact match
                    if domain in all_domains:
                        print(f"Found existing certificate (exact match): {cert_arn} (Status: {status})")
                        return cert_arn
                    
                    # Check for wildcard match
                    for cert_domain_name in all_domains:
                        if cert_domain_name.startswith('*.'):
                            # Extract the base domain from wildcard (e.g., *.example.com -> example.com)
                            cert_base = cert_domain_name[2:]  # Remove '*.'
                            if domain.endswith('.' + cert_base) or domain == cert_base:
                                print(f"Found existing wildcard certificate: {cert_arn} (covers {domain}, Status: {status})")
                                return cert_arn
                    
                    # Check if this is a wildcard certificate that would cover our domain
                    if wildcard_domain and wildcard_domain in all_domains:
                        print(f"Found existing wildcard certificate: {cert_arn} (covers {domain}, Status: {status})")
                        return cert_arn
                        
                except Exception as e:
                    print(f"Note: Could not describe certificate {cert_arn}: {e}")
                    continue
    except Exception as e:
        print(f"Note: Error listing certificates: {e}")
    
    return None


def request_certificate(acm_client, domain, region, allow_create=False):
    """
    Request an ACM certificate for the domain.
    For subdomains, requests a wildcard certificate (*.example.com) to cover all subdomains.
    Returns the certificate ARN.
    """
    # Check if certificate already exists
    existing_cert = find_certificate(acm_client, domain, region)
    if existing_cert:
        return existing_cert
    
    if not allow_create:
        print(f"Certificate for '{domain}' does not exist and resource creation is disabled.")
        sys.exit(1)
    
    # Determine if this is a subdomain and request wildcard certificate
    parts = domain.split('.')
    is_subdomain = len(parts) > 2
    
    if is_subdomain:
        # For subdomains, request wildcard certificate for parent domain
        # e.g., test.example.com -> *.example.com
        parent_domain = '.'.join(parts[1:])
        wildcard_domain = '*.' + parent_domain
        
        print(f"Subdomain detected: {domain}")
        print(f"Requesting wildcard certificate: {wildcard_domain} (covers all {parent_domain} subdomains)")
        
        try:
            # Request wildcard certificate
            # Don't include SubjectAlternativeNames if empty - AWS doesn't allow empty arrays
            response = acm_client.request_certificate(
                DomainName=wildcard_domain,
                ValidationMethod='DNS'  # Use DNS validation
                # Wildcard covers all subdomains, no need for SubjectAlternativeNames
            )
            
            cert_arn = response['CertificateArn']
            print(f"Wildcard certificate requested: {cert_arn}")
            print(f"This certificate will cover {domain} and all other {parent_domain} subdomains")
            print("Certificate is pending validation. DNS records will be created for validation.")
            
            return cert_arn
        except Exception as e:
            print(f"Error requesting wildcard certificate: {e}")
            sys.exit(1)
    else:
        # For apex domains, request certificate for the domain itself
        print(f"Requesting ACM certificate for domain: {domain}")
        
        try:
            # Request certificate with domain validation
            # Don't include SubjectAlternativeNames if empty - AWS doesn't allow empty arrays
            response = acm_client.request_certificate(
                DomainName=domain,
                ValidationMethod='DNS'  # Use DNS validation
                # Can add SubjectAlternativeNames=['www.' + domain] if needed for www subdomain
            )
            
            cert_arn = response['CertificateArn']
            print(f"Certificate requested: {cert_arn}")
            print("Certificate is pending validation. DNS records will be created for validation.")
            
            return cert_arn
        except Exception as e:
            print(f"Error requesting certificate: {e}")
            sys.exit(1)


def get_certificate_validation_records(acm_client, cert_arn):
    """
    Get the DNS validation records needed for certificate validation.
    Returns a list of validation records.
    """
    try:
        cert_details = acm_client.describe_certificate(CertificateArn=cert_arn)
        cert = cert_details['Certificate']
        
        validation_records = []
        domain_validation_options = cert.get('DomainValidationOptions', [])
        
        for option in domain_validation_options:
            validation_status = option.get('ValidationStatus', '')
            resource_record = option.get('ResourceRecord')
            
            if resource_record:
                validation_records.append({
                    'domain': option.get('DomainName'),
                    'name': resource_record.get('Name'),
                    'type': resource_record.get('Type'),
                    'value': resource_record.get('Value'),
                    'status': validation_status
                })
        
        return validation_records
    except Exception as e:
        print(f"Error getting certificate validation records: {e}")
        return []


def wait_for_certificate_validation(acm_client, cert_arn, timeout_minutes=30):
    """
    Wait for certificate to be validated and issued.
    Returns True if validated, False if timeout.
    """
    print(f"Waiting for certificate validation (up to {timeout_minutes} minutes)...")
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60
    
    while time.time() - start_time < timeout_seconds:
        try:
            cert_details = acm_client.describe_certificate(CertificateArn=cert_arn)
            cert = cert_details['Certificate']
            status = cert.get('Status', '')
            
            if status == 'ISSUED':
                print("Certificate is now issued and ready to use!")
                return True
            elif status == 'FAILED':
                print("Certificate validation failed!")
                return False
            elif status == 'PENDING_VALIDATION':
                print(f"  Status: {status} (waiting for DNS validation...)")
                time.sleep(30)  # Check every 30 seconds
            else:
                print(f"  Status: {status} (waiting...)")
                time.sleep(30)
        except Exception as e:
            print(f"Error checking certificate status: {e}")
            time.sleep(30)
    
    print(f"Warning: Certificate did not validate within {timeout_minutes} minutes")
    print("You may need to wait longer or check DNS records manually")
    return False
