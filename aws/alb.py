#!/usr/bin/env python3
"""
Application Load Balancer management.
"""
import sys
import time


def create_application_load_balancer(elbv2_client, ec2_client, app_name, vpc_id, subnet_ids, 
                                    security_group_id, allow_create=False):
    """
    Create an Application Load Balancer for the ECS service.
    Returns the ALB ARN and DNS name.
    """
    alb_name = f"{app_name}-alb"
    
    # Check if ALB already exists
    try:
        response = elbv2_client.describe_load_balancers(Names=[alb_name])
        if response['LoadBalancers']:
            alb = response['LoadBalancers'][0]
            print(f"Using existing ALB: {alb_name}")
            return alb['LoadBalancerArn'], alb['DNSName']
    except elbv2_client.exceptions.LoadBalancerNotFoundException:
        pass  # ALB doesn't exist, will create it
    except Exception as e:
        print(f"Note: Could not check for existing ALB: {e}")
    
    if not allow_create:
        print(f"ALB '{alb_name}' does not exist and resource creation is disabled.")
        sys.exit(1)
    
    print(f"Creating Application Load Balancer: {alb_name}")
    
    # Create ALB
    try:
        response = elbv2_client.create_load_balancer(
            Name=alb_name,
            Subnets=subnet_ids,
            SecurityGroups=[security_group_id],
            Scheme='internet-facing',
            Type='application',
            IpAddressType='ipv4'
        )
        
        alb_arn = response['LoadBalancers'][0]['LoadBalancerArn']
        alb_dns = response['LoadBalancers'][0]['DNSName']
        
        print(f"Created ALB: {alb_arn}")
        print(f"  DNS: {alb_dns}")
        
        # Wait for ALB to be active
        print("Waiting for ALB to become active...")
        waiter = elbv2_client.get_waiter('load_balancer_available')
        waiter.wait(LoadBalancerArns=[alb_arn])
        print("ALB is now active")
        
        return alb_arn, alb_dns
    except Exception as e:
        print(f"Error creating ALB: {e}")
        sys.exit(1)


def create_target_group(elbv2_client, vpc_id, app_name, port=80, protocol='HTTP', 
                       health_check_path='/health', allow_create=False):
    """
    Create a target group for the ECS service.
    Returns the target group ARN.
    """
    # Target group name (without port to keep it under 32 characters)
    tg_name = f"{app_name}-tg"
    
    # Check if target group already exists
    try:
        response = elbv2_client.describe_target_groups(Names=[tg_name])
        if response['TargetGroups']:
            tg = response['TargetGroups'][0]
            tg_arn = tg['TargetGroupArn']
            
            # Check if health check path needs updating
            current_path = tg.get('HealthCheckPath', '/')
            if current_path != health_check_path:
                print(f"Updating target group health check path from '{current_path}' to '{health_check_path}'...")
                elbv2_client.modify_target_group(
                    TargetGroupArn=tg_arn,
                    HealthCheckPath=health_check_path
                )
                print(f"Target group health check path updated")
            
            print(f"Using existing target group: {tg_name}")
            return tg_arn
    except elbv2_client.exceptions.TargetGroupNotFoundException:
        pass  # Target group doesn't exist, will create it
    except Exception as e:
        print(f"Note: Could not check for existing target group: {e}")
    
    if not allow_create:
        print(f"Target group '{tg_name}' does not exist and resource creation is disabled.")
        sys.exit(1)
    
    print(f"Creating target group: {tg_name}")
    
    try:
        response = elbv2_client.create_target_group(
            Name=tg_name,
            Protocol=protocol,
            Port=port,
            VpcId=vpc_id,
            TargetType='ip',  # For Fargate, use IP target type
            HealthCheckProtocol=protocol,
            HealthCheckPath=health_check_path,
            HealthCheckIntervalSeconds=30,
            HealthCheckTimeoutSeconds=5,
            HealthyThresholdCount=2,
            UnhealthyThresholdCount=3,
            Matcher={
                'HttpCode': '200'
            }
        )
        
        tg_arn = response['TargetGroups'][0]['TargetGroupArn']
        print(f"Created target group: {tg_arn}")
        print(f"  Health check path: {health_check_path}")
        
        return tg_arn
    except Exception as e:
        print(f"Error creating target group: {e}")
        sys.exit(1)


def wait_for_healthy_targets(elbv2_client, ecs_client, cluster_name, service_name, target_group_arn, timeout_minutes=10):
    """
    Wait for at least one healthy target in the target group.
    First waits for ECS tasks to be running, then waits for target registration.
    """
    print(f"Waiting for targets to become healthy (up to {timeout_minutes} minutes)...")
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60
    check_interval = 15  # Check every 15 seconds
    
    # First, verify service has load balancer configured
    print("  Step 0: Verifying service configuration...")
    try:
        services = ecs_client.describe_services(cluster=cluster_name, services=[service_name])
        if services['services']:
            service = services['services'][0]
            load_balancers = service.get('loadBalancers', [])
            
            if not load_balancers:
                print(f"  ✗ ERROR: Service does not have a load balancer configured!")
                print(f"  This is why tasks aren't registering. The service needs to be updated with load balancer config.")
                return False
            
            print(f"  ✓ Service has {len(load_balancers)} load balancer(s) configured")
            for lb in load_balancers:
                print(f"    Target Group: {lb.get('targetGroupArn', 'N/A')}")
                print(f"    Container: {lb.get('containerName', 'N/A')}:{lb.get('containerPort', 'N/A')}")
                
                # Verify it matches the expected target group
                if lb.get('targetGroupArn') != target_group_arn:
                    print(f"    ⚠ WARNING: Target group ARN doesn't match expected!")
                    print(f"      Expected: {target_group_arn}")
                    print(f"      Actual:   {lb.get('targetGroupArn')}")
        else:
            print(f"  ✗ ERROR: Service not found!")
            return False
    except Exception as e:
        print(f"  Error checking service configuration: {e}")
        return False
    
    # First, wait for ECS tasks to be running
    print("  Step 1: Waiting for ECS tasks to be running...")
    tasks_running = False
    while time.time() - start_time < timeout_seconds and not tasks_running:
        try:
            services = ecs_client.describe_services(cluster=cluster_name, services=[service_name])
            if services['services']:
                service = services['services'][0]
                running_count = service.get('runningCount', 0)
                desired_count = service.get('desiredCount', 0)
                
                if running_count > 0 and running_count >= desired_count:
                    print(f"  ✓ {running_count} task(s) are running")
                    tasks_running = True
                    break
                else:
                    print(f"  Tasks: {running_count}/{desired_count} running...")
            
            time.sleep(check_interval)
        except Exception as e:
            print(f"  Error checking ECS service: {e}")
            time.sleep(check_interval)
    
    if not tasks_running:
        print(f"  Warning: Tasks not running within timeout")
        return False
    
    # Now wait for targets to register and become healthy
    print("  Step 2: Waiting for targets to register with ALB and become healthy...")
    print(f"  Target Group ARN: {target_group_arn}")
    elapsed = time.time() - start_time
    remaining_timeout = timeout_seconds - elapsed
    
    # Give ECS a moment to start registering tasks (can take 30-60 seconds)
    print("  Waiting for ECS to begin task registration (this can take 30-60 seconds)...")
    time.sleep(30)
    
    while time.time() - start_time < timeout_seconds:
        try:
            response = elbv2_client.describe_target_health(TargetGroupArn=target_group_arn)
            targets = response.get('TargetHealthDescriptions', [])
            
            if targets:
                healthy_count = sum(1 for t in targets if t['TargetHealth']['State'] == 'healthy')
                total_count = len(targets)
                
                # Show status of all targets
                status_summary = {}
                for target in targets:
                    state = target['TargetHealth']['State']
                    reason = target['TargetHealth'].get('Reason', '')
                    status_key = f"{state}" + (f" ({reason})" if reason else "")
                    status_summary[status_key] = status_summary.get(status_key, 0) + 1
                
                status_str = ", ".join([f"{count} {state}" for state, count in status_summary.items()])
                print(f"  Targets: {healthy_count}/{total_count} healthy [{status_str}]")
                
                if healthy_count > 0:
                    print("  ✓ Targets are healthy!")
                    return True
            else:
                print(f"  No targets registered yet (tasks may still be registering)...")
            
            time.sleep(check_interval)
        except Exception as e:
            print(f"  Error checking target health: {e}")
            time.sleep(check_interval)
    
    print(f"  Warning: No healthy targets found within {timeout_minutes} minutes")
    print("  Troubleshooting:")
    print("    1. Check ECS tasks are running in the console")
    print("    2. Verify tasks are registered with the target group")
    print("    3. Check health check path matches container endpoint (/health)")
    print("    4. Verify security groups allow traffic from ALB to tasks")
    print("    5. Check CloudWatch logs for container errors")
    return False


def create_listener(elbv2_client, alb_arn, target_group_arn, allow_create=False):
    """
    Create HTTP and HTTPS listeners for the ALB.
    For now, we'll create HTTP listener. HTTPS requires ACM certificate.
    """
    # Check if listener already exists
    try:
        response = elbv2_client.describe_listeners(LoadBalancerArn=alb_arn)
        for listener in response.get('Listeners', []):
            if listener['Port'] == 80:
                # If listener already exists but points to a different target group, update it
                listener_arn = listener['ListenerArn']
                current_actions = listener.get('DefaultActions', [])
                current_tg = None
                if current_actions:
                    action = current_actions[0]
                    if action.get('Type') == 'forward':
                        current_tg = action.get('TargetGroupArn')
                if current_tg and current_tg != target_group_arn:
                    print(f"HTTP listener exists on port 80 but points to a different target group.")
                    print(f"Updating listener to forward to {target_group_arn} instead of {current_tg}...")
                    elbv2_client.modify_listener(
                        ListenerArn=listener_arn,
                        DefaultActions=[
                            {
                                'Type': 'forward',
                                'TargetGroupArn': target_group_arn
                            }
                        ]
                    )
                    print(f"Listener updated to use target group: {target_group_arn}")
                else:
                    print(f"Using existing HTTP listener on port 80")
                return listener_arn
    except Exception as e:
        print(f"Note: Could not check for existing listeners: {e}")
    
    if not allow_create:
        print(f"ALB listener does not exist and resource creation is disabled.")
        sys.exit(1)
    
    print("Creating HTTP listener on port 80...")
    
    try:
        response = elbv2_client.create_listener(
            LoadBalancerArn=alb_arn,
            Protocol='HTTP',
            Port=80,
            DefaultActions=[
                {
                    'Type': 'forward',
                    'TargetGroupArn': target_group_arn
                }
            ]
        )
        
        listener_arn = response['Listeners'][0]['ListenerArn']
        print(f"Created HTTP listener: {listener_arn}")
        
        return listener_arn
    except Exception as e:
        print(f"Error creating listener: {e}")
        sys.exit(1)
