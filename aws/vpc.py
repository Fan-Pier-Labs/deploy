#!/usr/bin/env python3
"""
VPC, subnet, and security group management.
"""
import sys


def get_default_vpc_resources(ec2_client, app_name, allow_create=False):
    """
    Get default VPC, subnets, and create a security group if needed.
    """
    # Get default VPC
    vpcs = ec2_client.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
    if not vpcs['Vpcs']:
        print("No default VPC found. Please create a VPC manually or modify this script.")
        sys.exit(1)
        
    default_vpc_id = vpcs['Vpcs'][0]['VpcId']
    print(f"Using default VPC: {default_vpc_id}")
    
    # Get subnets in the default VPC
    subnets = ec2_client.describe_subnets(
        Filters=[{'Name': 'vpc-id', 'Values': [default_vpc_id]}]
    )
    
    if not subnets['Subnets']:
        print("No subnets found in the default VPC. Please create subnets manually.")
        sys.exit(1)
        
    # Get at least two subnets (for high availability)
    subnet_ids = [subnet['SubnetId'] for subnet in subnets['Subnets'][:2]]
    if len(subnet_ids) < 2:
        print(f"Warning: Only found {len(subnet_ids)} subnets. For production, consider using at least 2 subnets.")
    
    print(f"Using subnets: {', '.join(subnet_ids)}")
    
    # Check if security group for our app exists, create if allowed
    app_sg_name = f'{app_name}-sg'
    security_groups = ec2_client.describe_security_groups(
        Filters=[
            {'Name': 'vpc-id', 'Values': [default_vpc_id]},
            {'Name': 'group-name', 'Values': [app_sg_name]}
        ]
    )
    
    if security_groups['SecurityGroups']:
        sg_id = security_groups['SecurityGroups'][0]['GroupId']
        print(f"Using existing security group: {sg_id}")
    else:
        if not allow_create:
            print(f"Security group '{app_sg_name}' does not exist and resource creation is disabled.")
            sys.exit(1)
            
        print(f"Creating security group: {app_sg_name}")
        sg_response = ec2_client.create_security_group(
            GroupName=app_sg_name,
            Description=f'Security group for {app_name} on Fargate',
            VpcId=default_vpc_id
        )
        sg_id = sg_response['GroupId']
        
        # Add inbound rules - allow HTTP and HTTPS
        ec2_client.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 80,
                    'ToPort': 80,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                },
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 443,
                    'ToPort': 443,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                }
            ]
        )
        print(f"Created security group: {sg_id} with HTTP and HTTPS access")
    
    return subnet_ids, sg_id, default_vpc_id


def create_alb_security_group(ec2_client, vpc_id, app_name, allow_create=False):
    """
    Create a security group for ALB that allows HTTP and HTTPS from anywhere.
    """
    sg_name = f'{app_name}-alb-sg'
    
    # Check if security group exists
    security_groups = ec2_client.describe_security_groups(
        Filters=[
            {'Name': 'vpc-id', 'Values': [vpc_id]},
            {'Name': 'group-name', 'Values': [sg_name]}
        ]
    )
    
    if security_groups['SecurityGroups']:
        sg_id = security_groups['SecurityGroups'][0]['GroupId']
        print(f"Using existing ALB security group: {sg_id}")
        return sg_id
    
    if not allow_create:
        print(f"ALB security group '{sg_name}' does not exist and resource creation is disabled.")
        sys.exit(1)
    
    print(f"Creating ALB security group: {sg_name}")
    sg_response = ec2_client.create_security_group(
        GroupName=sg_name,
        Description=f'Security group for {app_name} ALB',
        VpcId=vpc_id
    )
    sg_id = sg_response['GroupId']
    
    # Allow HTTP and HTTPS from anywhere
    ec2_client.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                'IpProtocol': 'tcp',
                'FromPort': 80,
                'ToPort': 80,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            },
            {
                'IpProtocol': 'tcp',
                'FromPort': 443,
                'ToPort': 443,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            }
        ]
    )
    print(f"Created ALB security group: {sg_id}")
    return sg_id


def update_fargate_security_group_for_alb(ec2_client, fargate_sg_id, alb_sg_id, port=80):
    """
    Update Fargate security group to allow traffic from ALB security group on the container port.
    """
    try:
        # Allow traffic from ALB on the specified application port
        ec2_client.authorize_security_group_ingress(
            GroupId=fargate_sg_id,
            IpPermissions=[
                {
                    'IpProtocol': 'tcp',
                    'FromPort': port,
                    'ToPort': port,
                    'UserIdGroupPairs': [{'GroupId': alb_sg_id}]
                }
            ]
        )
        print(f"Updated Fargate security group to allow traffic from ALB on port {port}")
    except ec2_client.exceptions.ClientError as e:
        if 'InvalidPermission.Duplicate' in str(e):
            print(f"Fargate security group already allows traffic from ALB on port {port}")
        else:
            raise
