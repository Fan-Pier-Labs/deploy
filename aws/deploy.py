#!/usr/bin/env python3
"""
Main deployment orchestrator for AWS Fargate.
Supports both internal deployments and public-facing web apps.
"""
import sys
import time
import boto3
import urllib.request
import urllib.error
from . import (
    vpc, iam, logs, events, ecr, ecs, route53, cloudfront, alb, acm
)
import boto3


def deploy_lightweight_public_app(session, config, subnet_ids, security_group_id, 
                                   task_definition_arn, cluster_name, service_name,
                                   desired_count, use_spot, allow_create, port=8080):
    """
    Deploy a lightweight public app where domain points directly to Fargate service.
    This requires the service to have a public IP and the domain to point to it.
    Note: Fargate tasks get ephemeral IPs, so this is only suitable for testing/internal use.
    """
    domain = config['public']['domain']
    route53_client = session.client('route53')
    ec2_client = session.client('ec2')
    
    print(f"\n=== Deploying Lightweight Public App ===")
    print(f"Domain: {domain}")
    print("Note: This setup points domain directly to Fargate service.")
    print("Warning: Fargate tasks have ephemeral IPs, so DNS updates may be needed on each deployment.")
    
    # Ensure security group allows inbound traffic on the container port
    print(f"Ensuring security group allows inbound traffic on port {port}...")
    try:
        # Check current security group rules
        sg_info = ec2_client.describe_security_groups(GroupIds=[security_group_id])
        if sg_info['SecurityGroups']:
            sg = sg_info['SecurityGroups'][0]
            existing_rules = sg.get('IpPermissions', [])
            
            # Check if port is already allowed
            port_allowed = False
            for rule in existing_rules:
                if rule.get('FromPort') == port and rule.get('ToPort') == port:
                    if rule.get('IpProtocol') in ['tcp', '-1']:
                        port_allowed = True
                        break
            
            if not port_allowed:
                print(f"Adding inbound rule for port {port} to security group...")
                ec2_client.authorize_security_group_ingress(
                    GroupId=security_group_id,
                    IpPermissions=[
                        {
                            'IpProtocol': 'tcp',
                            'FromPort': port,
                            'ToPort': port,
                            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                        }
                    ]
                )
                print(f"Security group updated to allow inbound traffic on port {port}")
            else:
                print(f"Security group already allows inbound traffic on port {port}")
    except ec2_client.exceptions.ClientError as e:
        if 'InvalidPermission.Duplicate' in str(e):
            print(f"Security group already allows inbound traffic on port {port}")
        else:
            print(f"Warning: Could not update security group: {e}")
    
    # Get the service to find its public IPs
    ecs_client = session.client('ecs')
    services = ecs_client.describe_services(cluster=cluster_name, services=[service_name])
    
    if not services['services']:
        print("Error: Service not found")
        sys.exit(1)
    
    service = services['services'][0]
    
    # Wait for tasks to be running with public IPs
    print("Waiting for tasks to start and get public IPs...")
    timeout_minutes = 10
    timeout_seconds = timeout_minutes * 60
    start_time = time.time()
    check_interval = 15  # Check every 15 seconds
    
    while time.time() - start_time < timeout_seconds:
        # Get running tasks
        tasks = ecs_client.list_tasks(cluster=cluster_name, serviceName=service_name)
        
        if tasks['taskArns']:
            # Get task details to find public IPs
            task_details = ecs_client.describe_tasks(cluster=cluster_name, tasks=tasks['taskArns'])
            
            # Look for a task with a public IP
            for task in task_details.get('tasks', []):
                task_status = task.get('lastStatus', '')
                
                # Only check running tasks
                if task_status == 'RUNNING':
                    public_ip = None
                    attachments = task.get('attachments', [])
                    
                    # Method 1: Check attachment details
                    for attachment in attachments:
                        if attachment['type'] == 'ElasticNetworkInterface':
                            for detail in attachment.get('details', []):
                                if detail['name'] == 'publicIPv4Address':
                                    public_ip = detail['value']
                                    break
                            if public_ip:
                                break
                    
                    # Method 2: If not found, try to get from network interfaces
                    if not public_ip:
                        # Get ENI ID from attachments
                        eni_id = None
                        for attachment in attachments:
                            if attachment['type'] == 'ElasticNetworkInterface':
                                for detail in attachment.get('details', []):
                                    if detail['name'] == 'networkInterfaceId':
                                        eni_id = detail['value']
                                        break
                                if eni_id:
                                    break
                        
                        # Query EC2 for the ENI's public IP
                        if eni_id:
                            try:
                                ec2_client = session.client('ec2')
                                enis = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
                                if enis.get('NetworkInterfaces'):
                                    eni = enis['NetworkInterfaces'][0]
                                    if 'Association' in eni and 'PublicIp' in eni['Association']:
                                        public_ip = eni['Association']['PublicIp']
                            except Exception as e:
                                print(f"  Note: Could not query ENI for public IP: {e}")
                    
                    if public_ip:
                        print(f"Found running task with public IP: {public_ip}")
                        
                        # Create A record pointing to this IP
                        route53.create_or_update_dns_record(
                            route53_client, domain, public_ip, 
                            record_type='A', allow_create=allow_create
                        )
                        print(f"DNS record created: {domain} -> {public_ip}")
                        return
                    else:
                        print(f"  Task is RUNNING but no public IP found yet (checking attachments...)")
                elif task_status in ['PENDING', 'PROVISIONING', 'ACTIVATING']:
                    print(f"  Task status: {task_status} (waiting for RUNNING...)")
        
        # If we get here, no running task with public IP found yet
        elapsed = int(time.time() - start_time)
        remaining = timeout_seconds - elapsed
        print(f"  No running tasks with public IPs yet. Waiting... ({elapsed}s elapsed, {remaining}s remaining)")
        time.sleep(check_interval)
    
    # Timeout reached
    print(f"\nWarning: No running tasks with public IPs found within {timeout_minutes} minutes.")
    print("The service may still be starting. You may need to:")
    print("  1. Check the ECS service status in AWS Console")
    print("  2. Wait longer and manually update DNS once tasks are running")
    print("  3. Check CloudWatch logs for task startup errors")


def deploy_production_public_app(session, config, subnet_ids, security_group_id, vpc_id,
                                 task_definition_arn, cluster_name, service_name,
                                 desired_count, use_spot, allow_create, region, account_id, port, profile,
                                 certificate_id=None):
    """
    Deploy a production-ready public app with CloudFront -> ALB -> Fargate.
    """
    domain = config['public']['domain']
    route53_client = session.client('route53')
    elbv2_client = session.client('elbv2')
    # CloudFront client can be in any region, but we'll use the deployment region
    cloudfront_client = session.client('cloudfront')
    ec2_client = session.client('ec2')
    ecs_client = session.client('ecs')
    
    print(f"\n=== Deploying Production Public App ===")
    print(f"Domain: {domain}")
    print("Architecture: Route53 -> CloudFront -> ALB -> Fargate")
    
    # Step 1: Create ALB security group
    alb_sg_id = vpc.create_alb_security_group(ec2_client, vpc_id, config['app_name'], allow_create)
    
    # Step 2: Update Fargate security group to allow traffic from ALB
    vpc.update_fargate_security_group_for_alb(ec2_client, security_group_id, alb_sg_id, port)
    
    # Step 3: Create ALB
    alb_arn, alb_dns = alb.create_application_load_balancer(
        elbv2_client, ec2_client, config['app_name'], vpc_id, 
        subnet_ids, alb_sg_id, allow_create
    )
    
    # Step 4: Create target group
    tg_arn = alb.create_target_group(
        elbv2_client, vpc_id, config['app_name'], 
        port=port, health_check_path='/api/health', allow_create=allow_create
    )
    
    # Step 5: Create ALB listener
    alb.create_listener(elbv2_client, alb_arn, tg_arn, allow_create)
    
    # Step 6: Prepare load balancer config (service will be created/updated in main function)
    load_balancer_config = {
        'targetGroupArn': tg_arn,
        'containerName': config['app_name'],
        'containerPort': port
    }
    
    print(f"Load balancer configuration prepared:")
    print(f"  Target Group: {tg_arn}")
    print(f"  Container Name: {config['app_name']}")
    print(f"  Container Port: {port}")
    print(f"  Note: Service will be created/updated with this configuration")
    
    # Step 7: Request/get ACM certificate for CloudFront
    # CloudFront requires certificates to be in us-east-1
    import boto3
    acm_region = 'us-east-1'  # CloudFront requires us-east-1
    acm_session = boto3.Session(profile_name=profile, region_name=acm_region)
    acm_client = acm_session.client('acm')
    
    print(f"\n=== Setting up SSL Certificate ===")
    
    # Check if a specific certificate ID was provided
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
                print(f"Warning: Certificate status is {cert_status}. It may not be ready for use.")
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
                print(f"Warning: Certificate status is {cert_status}. It may need manual validation.")
    
    # Step 8: Create CloudFront distribution with certificate
    # Use ALB DNS name (without http://)
    alb_dns_clean = alb_dns.rstrip('/')
    cf_domain, cf_id = cloudfront.create_cloudfront_distribution(
        cloudfront_client, alb_dns_clean, domain, region, allow_create, certificate_arn=cert_arn
    )
    
    # Step 9: Create Route53 record pointing to CloudFront
    # CloudFront distributions should use A record with ALIAS
    route53.create_or_update_dns_record(
        route53_client, domain, cf_domain, 
        record_type='A', allow_create=allow_create
    )
    
    print(f"\nProduction infrastructure setup complete!")
    print(f"  Domain: {domain}")
    print(f"  CloudFront: {cf_domain}")
    print(f"  ALB: {alb_dns}")
    print(f"  Note: CloudFront may take 15-20 minutes to fully deploy")
    
    # Store CloudFront info for later display
    config['_cloudfront_domain'] = cf_domain
    config['_cloudfront_id'] = cf_id
    
    # Return load balancer config for service creation
    return load_balancer_config


def test_deployment_http_requests(public_config, params):
    """
    Test HTTP requests to the deployed domain to verify everything works.
    Retries every 10 seconds for up to 10 minutes if checks fail.
    """
    domain = public_config['domain']
    mode = public_config.get('mode', 'production')
    
    print("\n" + "="*80)
    print("Testing Deployment with HTTP Requests")
    print("="*80)
    
    # Wait a bit for services to be ready (especially for CloudFront)
    if mode == 'production':
        print("\nWaiting 30 seconds for CloudFront distribution to propagate...")
        time.sleep(30)
    else:
        print("\nWaiting 15 seconds for service to be ready...")
        time.sleep(15)
    
    # Test URLs to try
    test_urls = []
    if mode == 'production':
        # Try HTTPS first (production should use HTTPS)
        test_urls.append(f"https://{domain}")
        # Also try HTTP (might redirect)
        test_urls.append(f"http://{domain}")
    else:
        # Lightweight mode - just HTTP
        test_urls.append(f"http://{domain}")
    
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
            print("  3. ECS service health and task status")
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


def deploy_to_fargate(config_dict=None, **kwargs):
    """
    Deploy the application to AWS Fargate with configurable settings.
    
    If config_dict is provided, it will be used. Otherwise, kwargs will be used.
    """
    # Merge config_dict and kwargs
    if config_dict:
        params = {**config_dict, **kwargs}
    else:
        params = kwargs
    
    # Extract parameters
    app_name = params.get('app_name')
    service_name = params.get('service_name')
    replicas = params.get('replicas', 1)
    use_spot = params.get('spot', True)
    region = params.get('region')
    allow_create = params.get('allow_create', False)
    environment_variables = params.get('environment', {})
    cpu = params.get('cpu')
    memory = params.get('memory')
    profile = params.get('profile', 'personal')
    ephemeral_storage = params.get('ephemeral_storage')
    iam_permissions = params.get('iam_permissions')
    custom_iam_policy = params.get('custom_iam_policy')
    dockerfile = params.get('dockerfile', 'Dockerfile')
    public_config = params.get('public')
    port = params.get('port', 8080)
    certificate_id = params.get('certificate_id')
    
    print("Starting deployment to AWS Fargate...")
    
    # Validate required parameters
    if app_name is None:
        print("Error: 'app_name' parameter is required")
        sys.exit(1)
    if region is None:
        print("Error: 'region' parameter is required")
        sys.exit(1)
    
    # Use the specified profile for AWS credentials and region
    session = boto3.Session(profile_name=profile, region_name=region)
    
    # Initialize AWS clients
    ecr_client = session.client('ecr')
    ecs_client = session.client('ecs')
    ec2_client = session.client('ec2')
    iam_client = session.client('iam')
    events_client = session.client('events')
    logs_client = session.client('logs')
    
    # Configuration
    region = session.region_name
    account_id = session.client('sts').get_caller_identity().get('Account')
    cluster_name = f"{app_name}-cluster"
    task_family = f"{app_name}-task"
    if service_name is None:
        service_name = f"{app_name}-service"
    
    # Deployment configuration
    desired_count = replicas
    capacity_provider = 'FARGATE_SPOT' if use_spot else 'FARGATE'
    
    try:
        # Step 0: Get VPC resources and ensure IAM role exists
        subnet_ids, security_group_id, vpc_id = vpc.get_default_vpc_resources(
            ec2_client, app_name, allow_create
        )
        
        # Validate required parameters
        if cpu is None:
            print("Error: 'cpu' parameter is required")
            sys.exit(1)
        if memory is None:
            print("Error: 'memory' parameter is required")
            sys.exit(1)
        if ephemeral_storage is None:
            print("Error: 'ephemeral_storage' parameter is required")
            sys.exit(1)
        
        # Set default IAM permissions if not provided
        if iam_permissions is None:
            iam_permissions = [
                'arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy',
                'arn:aws:iam::aws:policy/AmazonSQSFullAccess',
                'arn:aws:iam::aws:policy/AmazonS3FullAccess'
            ]
        
        execution_role_arn = iam.ensure_ecs_execution_role(
            iam_client, account_id, iam_permissions, custom_iam_policy, allow_create
        )
        
        # Create CloudWatch log group
        log_group_name = f"/ecs/{app_name}"
        logs.ensure_cloudwatch_log_group(logs_client, log_group_name, allow_create)
        
        # Step 1: Setup ECR repository
        repository_name = app_name.lower()
        ecr.setup_ecr_repository(ecr_client, repository_name, allow_create)
        
        # Step 2: Build and push Docker image
        image_name = ecr.build_and_push_image(
            ecr_client, repository_name, region, profile, dockerfile
        )
        
        # Step 3: Setup ECS cluster
        ecs.ensure_cluster(ecs_client, cluster_name, allow_create)
        
        # Enable event capture
        events.enable_event_capture(
            events_client, logs_client, cluster_name, region, account_id, allow_create
        )
        
        # Step 4: Register task definition
        task_definition_arn = ecs.register_task_definition(
            ecs_client, task_family, image_name, app_name, region,
            cpu, memory, ephemeral_storage, execution_role_arn,
            environment_variables, port
        )
        
        # Step 5: Handle public app deployment if configured
        load_balancer_config = None
        if public_config:
            mode = public_config.get('mode', 'lightweight')
            
            if mode == 'production':
                # For production, set up ALB first, then create service with load balancer
                # deploy_production_public_app stores CloudFront info in params
                load_balancer_config = deploy_production_public_app(
                    session, params, subnet_ids, security_group_id, vpc_id,
                    task_definition_arn, cluster_name, service_name,
                    desired_count, use_spot, allow_create, region, account_id, port, profile,
                    certificate_id=certificate_id
                )
        
        # Step 6: Create or update ECS service
        ecs.create_or_update_service(
            ecs_client, cluster_name, service_name, task_definition_arn,
            desired_count, use_spot, subnet_ids, security_group_id,
            allow_create=allow_create, load_balancer_config=load_balancer_config
        )
        
        # Step 6.5: Wait for ALB targets to become healthy (for production mode)
        if load_balancer_config and public_config and public_config.get('mode') == 'production':
            print(f"\nWaiting for ECS tasks to register with ALB and become healthy...")
            elbv2_client = session.client('elbv2')
            alb.wait_for_healthy_targets(
                elbv2_client, ecs_client, cluster_name, service_name,
                load_balancer_config['targetGroupArn'], timeout_minutes=10
            )
        
        # Step 6.6: Invalidate CloudFront cache so users get the new deployment immediately
        if '_cloudfront_id' in params:
            print(f"\n=== Invalidating CloudFront Cache ===")
            try:
                cloudfront_client = session.client('cloudfront')
                cloudfront.invalidate_cloudfront_cache(cloudfront_client, params['_cloudfront_id'])
            except Exception as e:
                print(f"Warning: Failed to invalidate CloudFront cache: {e}")
                print("  You may need to manually invalidate the cache or wait for TTL to expire")
        
        # Step 7: Handle lightweight public app DNS (after service is created)
        if public_config and public_config.get('mode') == 'lightweight':
            deploy_lightweight_public_app(
                session, params, subnet_ids, security_group_id,
                task_definition_arn, cluster_name, service_name,
                desired_count, use_spot, allow_create, port
            )
        
        print("\nDeployment initiated successfully!")
        print("All resources were created or updated automatically.")
        print(f"Using subnets: {', '.join(subnet_ids)}")
        print(f"Using security group: {security_group_id}")
        print(f"Using execution role: {execution_role_arn}")
        print(f"Deploying {desired_count} {'Spot ' if use_spot else ''}instances")
        
        # Print AWS Console links
        print("\n" + "="*80)
        print("AWS Console Links:")
        print("="*80)
        cluster_url = f"https://{region}.console.aws.amazon.com/ecs/v2/clusters/{cluster_name}/services?region={region}"
        service_url = f"https://{region}.console.aws.amazon.com/ecs/v2/clusters/{cluster_name}/services/{service_name}?region={region}"
        logs_url = f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:log-groups/log-group/$252Fecs$252F{app_name}"
        
        print(f"\nCluster Overview:")
        print(f"  {cluster_url}")
        print(f"\nService Details:")
        print(f"  {service_url}")
        print(f"\nCloudWatch Logs:")
        print(f"  {logs_url}")
        
        if public_config:
            print(f"\nPublic Domain:")
            domain_url = f"http://{public_config['domain']}"
            if public_config.get('mode') == 'production':
                # For production, show both HTTP and HTTPS
                print(f"  {domain_url}")
                print(f"  https://{public_config['domain']}")
                # Show CloudFront URL if available
                if '_cloudfront_domain' in params:
                    print(f"\nCloudFront Distribution URL:")
                    print(f"  https://{params['_cloudfront_domain']}")
            else:
                # For lightweight, just show HTTP
                print(f"  {domain_url}")
        
        print("\n" + "="*80 + "\n")
        
        # Test HTTP requests to verify deployment
        if public_config:
            test_deployment_http_requests(public_config, params)
        
    except Exception as e:
        print(f"Error during deployment: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
