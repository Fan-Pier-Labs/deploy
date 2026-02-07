#!/usr/bin/env python3
"""
Teardown Fargate deployment infrastructure: CloudFront, ALB, ECS service, Route53,
ECS cluster, task definitions, security groups, ECR repo. CloudWatch log groups are left.
"""
import sys
import time
import boto3
from botocore.exceptions import ClientError

from . import route53, cloudfront


def _find_cloudfront_by_domain(cloudfront_client, domain):
    """Return (distribution_id, etag) for the distribution with this domain alias, or (None, None)."""
    try:
        paginator = cloudfront_client.get_paginator('list_distributions')
        for page in paginator.paginate():
            for dist in page.get('DistributionList', {}).get('Items', []):
                if domain in dist.get('Aliases', {}).get('Items', []):
                    dist_id = dist['Id']
                    config = cloudfront_client.get_distribution_config(Id=dist_id)
                    return dist_id, config['ETag']
    except Exception as e:
        print(f"Warning: Could not list CloudFront distributions: {e}")
    return None, None


def _delete_route53_record_for_domain(route53_client, domain, record_type='A'):
    """Delete the A record for this domain if it exists. Returns True if deleted."""
    hosted_zone_id, record_name, zone_name = route53.find_hosted_zone(route53_client, domain)
    if not hosted_zone_id:
        return False
    if record_name == domain:
        full_record_name = zone_name
    else:
        full_record_name = f"{record_name}.{zone_name}"
    if not full_record_name.endswith('.'):
        full_record_name += '.'
    existing = route53.get_existing_record(route53_client, hosted_zone_id, full_record_name, record_type)
    if not existing:
        return False
    route53_client.change_resource_record_sets(
        HostedZoneId=hosted_zone_id,
        ChangeBatch={'Changes': [{'Action': 'DELETE', 'ResourceRecordSet': existing}]}
    )
    return True


def _delete_ecs_service(ecs_client, cluster_name, service_name):
    """Delete ECS service (force=True stops tasks and deletes)."""
    try:
        ecs_client.delete_service(cluster=cluster_name, service=service_name, force=True)
        return True
    except ecs_client.exceptions.ClusterNotFoundException:
        return False
    except ecs_client.exceptions.ServiceNotFoundException:
        return False
    except Exception as e:
        print(f"  Error deleting ECS service: {e}")
        return False


def _delete_alb_and_target_group(elbv2_client, app_name):
    """Delete ALB (after deleting listeners) and target group. Returns True if something was deleted."""
    alb_name = f"{app_name}-alb"
    tg_name = f"{app_name}-tg"
    deleted = False
    try:
        response = elbv2_client.describe_load_balancers(Names=[alb_name])
        if not response.get('LoadBalancers'):
            return False
        alb_arn = response['LoadBalancers'][0]['LoadBalancerArn']
        # Delete listeners first
        listeners = elbv2_client.describe_listeners(LoadBalancerArn=alb_arn)
        for listener in listeners.get('Listeners', []):
            elbv2_client.delete_listener(ListenerArn=listener['ListenerArn'])
            print(f"  Deleted listener {listener['ListenerArn'].split('/')[-1]}")
            deleted = True
        elbv2_client.delete_load_balancer(LoadBalancerArn=alb_arn)
        print(f"  Deleted ALB {alb_name}")
        deleted = True
    except elbv2_client.exceptions.LoadBalancerNotFoundException:
        pass
    except Exception as e:
        print(f"  Warning: Could not delete ALB: {e}")
    try:
        tg_response = elbv2_client.describe_target_groups(Names=[tg_name])
        if tg_response.get('TargetGroups'):
            tg_arn = tg_response['TargetGroups'][0]['TargetGroupArn']
            elbv2_client.delete_target_group(TargetGroupArn=tg_arn)
            print(f"  Deleted target group {tg_name}")
            deleted = True
    except elbv2_client.exceptions.TargetGroupNotFoundException:
        pass
    except Exception as e:
        print(f"  Warning: Could not delete target group: {e}")
    return deleted


def _delete_ecs_cluster(ecs_client, cluster_name):
    """Delete ECS cluster (must have no services)."""
    try:
        ecs_client.delete_cluster(cluster=cluster_name)
        return True
    except ecs_client.exceptions.ClusterNotFoundException:
        return False
    except Exception as e:
        print(f"  Error deleting ECS cluster: {e}")
        return False


def _deregister_task_definitions(ecs_client, task_family):
    """Deregister all task definition revisions for this family."""
    try:
        paginator = ecs_client.get_paginator('list_task_definitions')
        arns = []
        for page in paginator.paginate(familyPrefix=task_family, status='ACTIVE'):
            arns.extend(page.get('taskDefinitionArns', []))
        for arn in arns:
            try:
                ecs_client.deregister_task_definition(taskDefinition=arn)
                rev = arn.split(':')[-1]
                print(f"  Deregistered task definition {task_family}:{rev}")
            except Exception as e:
                print(f"  Warning: Could not deregister {arn}: {e}")
        return len(arns) > 0
    except Exception as e:
        print(f"  Warning: Could not list/deregister task definitions: {e}")
        return False


def _delete_security_groups(ec2_client, app_name, vpc_id):
    """Delete ALB security group then Fargate security group (order matters if Fargate SG references ALB SG)."""
    alb_sg_name = f"{app_name}-alb-sg"
    fargate_sg_name = f"{app_name}-sg"
    deleted = False
    for sg_name in (alb_sg_name, fargate_sg_name):
        try:
            resp = ec2_client.describe_security_groups(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'group-name', 'Values': [sg_name]}
                ]
            )
            if not resp.get('SecurityGroups'):
                continue
            sg_id = resp['SecurityGroups'][0]['GroupId']
            try:
                ec2_client.delete_security_group(GroupId=sg_id)
                print(f"  Deleted security group {sg_name} ({sg_id})")
                deleted = True
            except ClientError as e:
                if 'DependencyViolation' in str(e):
                    print(f"  Warning: Could not delete {sg_name} (in use); try again later")
                else:
                    print(f"  Warning: Could not delete {sg_name}: {e}")
        except Exception as e:
            print(f"  Warning: Could not find/delete {sg_name}: {e}")
    return deleted


def _get_default_vpc_id(ec2_client):
    """Return default VPC ID or None."""
    try:
        vpcs = ec2_client.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
        if vpcs.get('Vpcs'):
            return vpcs['Vpcs'][0]['VpcId']
    except Exception:
        pass
    return None


def _delete_ecr_repository(ecr_client, app_name):
    """Delete ECR repository and all images (force)."""
    repo_name = app_name.lower()
    try:
        ecr_client.delete_repository(repositoryName=repo_name, force=True)
        print(f"  Deleted ECR repository {repo_name}")
        return True
    except ecr_client.exceptions.RepositoryNotFoundException:
        return False
    except Exception as e:
        print(f"  Warning: Could not delete ECR repository: {e}")
        return False


def destroy_fargate_infra(config_dict, confirm_callback=None):
    """
    Teardown Fargate deployment: CloudFront (if production), Route53 A record,
    ECS service, ALB/target group (if production), ECS cluster, task definitions,
    security groups, ECR repo. CloudWatch log groups are left.

    confirm_callback: if provided, called with list of resource descriptions; return True to proceed.
    If not provided, prompts stdin: "Type 'yes' to confirm destruction:"
    """
    app_name = config_dict.get('app_name')
    service_name = config_dict.get('service_name') or f"{app_name}-service"
    region = config_dict.get('region')
    profile = config_dict.get('profile', 'personal')
    public_config = config_dict.get('public')
    cluster_name = f"{app_name}-cluster"
    task_family = f"{app_name}-task"

    session = boto3.Session(profile_name=profile, region_name=region)
    ecs_client = session.client('ecs')
    route53_client = session.client('route53')
    cloudfront_client = session.client('cloudfront')
    elbv2_client = session.client('elbv2')
    ec2_client = session.client('ec2')
    ecr_client = session.client('ecr')

    to_destroy = []
    cf_id = None
    mode = (public_config or {}).get('mode', 'production')
    domain = (public_config or {}).get('domain') if public_config else None

    to_destroy.append(f"  - ECS service: {cluster_name} / {service_name}")
    to_destroy.append(f"  - ECS cluster: {cluster_name}")
    to_destroy.append(f"  - Task definitions: family {task_family}")
    to_destroy.append(f"  - Security groups: {app_name}-sg, {app_name}-alb-sg")
    to_destroy.append(f"  - ECR repository: {app_name.lower()}")

    if public_config and domain:
        to_destroy.append(f"  - Route53 A record: {domain}")
        if mode == 'production':
            cf_id, _ = _find_cloudfront_by_domain(cloudfront_client, domain)
            if cf_id:
                to_destroy.append(f"  - CloudFront distribution: {cf_id} (alias: {domain})")
            to_destroy.append(f"  - ALB: {app_name}-alb")
            to_destroy.append(f"  - Target group: {app_name}-tg")

    print("\n" + "=" * 60)
    print("DESTROY (Fargate): The following will be permanently removed")
    print("=" * 60)
    for line in to_destroy:
        print(line)
    print("=" * 60)
    print("(CloudWatch log groups are NOT deleted)")
    print("=" * 60)

    if confirm_callback:
        if not confirm_callback(to_destroy):
            print("Aborted.")
            sys.exit(0)
    else:
        try:
            answer = input("Type 'yes' to confirm destruction: ").strip().lower()
        except EOFError:
            answer = ""
        if answer != 'yes':
            print("Aborted.")
            sys.exit(0)

    print("\n=== Tearing down ===\n")

    # 1. CloudFront (production only): disable, wait, delete
    if public_config and domain and mode == 'production' and cf_id:
        print("Disabling CloudFront distribution...")
        try:
            config_resp = cloudfront_client.get_distribution_config(Id=cf_id)
            etag = config_resp['ETag']
            config = config_resp['DistributionConfig']
            config['Enabled'] = False
            cloudfront_client.update_distribution(Id=cf_id, DistributionConfig=config, IfMatch=etag)
            print("  CloudFront disabled; waiting for deployment...")
            if cloudfront.wait_for_cloudfront_deployment(cloudfront_client, cf_id, timeout_minutes=25):
                etag = cloudfront_client.get_distribution_config(Id=cf_id)['ETag']
                cloudfront_client.delete_distribution(Id=cf_id, IfMatch=etag)
                print(f"  Deleted CloudFront distribution {cf_id}")
            else:
                print("  CloudFront did not reach Deployed state; run destroy again later to delete it.")
        except Exception as e:
            print(f"  Error: {e}")

    # 2. Route53 A record
    if public_config and domain:
        print(f"Deleting Route53 A record for {domain}...")
        if _delete_route53_record_for_domain(route53_client, domain, 'A'):
            print(f"  Deleted A record for {domain}")
        else:
            print(f"  No A record found for {domain}")

    # 3. ECS service (force delete; cluster delete requires service to be gone)
    print(f"Deleting ECS service {service_name}...")
    try:
        if _delete_ecs_service(ecs_client, cluster_name, service_name):
            print(f"  ECS service marked for deletion; waiting for it to drain...")
            for _ in range(30):  # wait up to 5 minutes
                time.sleep(10)
                try:
                    ecs_client.describe_services(cluster=cluster_name, services=[service_name])
                except ecs_client.exceptions.ClusterNotFoundException:
                    break
                except ecs_client.exceptions.ServiceNotFoundException:
                    break
                resp = ecs_client.describe_services(cluster=cluster_name, services=[service_name])
                if not resp.get("services"):
                    break
                status = resp["services"][0].get("status", "")
                if status == "INACTIVE":
                    break
        else:
            print(f"  Service not found or already deleted")
    except Exception as e:
        print(f"  Error: {e}")

    # 4. ALB and target group (production only)
    if public_config and domain and mode == 'production':
        print(f"Deleting ALB and target group...")
        _delete_alb_and_target_group(elbv2_client, app_name)

    # 5. ECS cluster (must have no services; retry a few times if still draining)
    print(f"Deleting ECS cluster {cluster_name}...")
    for attempt in range(6):
        if _delete_ecs_cluster(ecs_client, cluster_name):
            break
        try:
            ecs_client.describe_clusters(clusters=[cluster_name])
        except Exception:
            break
        if attempt < 5:
            print("  Cluster still has services/tasks; waiting 30s...")
            time.sleep(30)

    # 6. Task definitions (deregister all revisions)
    print(f"Deregistering task definitions for family {task_family}...")
    _deregister_task_definitions(ecs_client, task_family)

    # 7. Security groups (ALB SG first, then Fargate SG)
    vpc_id = _get_default_vpc_id(ec2_client)
    if vpc_id:
        print("Deleting security groups...")
        _delete_security_groups(ec2_client, app_name, vpc_id)
    else:
        print("  Skipping security groups (no default VPC found)")

    # 8. ECR repository
    print("Deleting ECR repository...")
    _delete_ecr_repository(ecr_client, app_name)

    print("\nTeardown complete. You can re-deploy with the same config to recreate infrastructure.")
