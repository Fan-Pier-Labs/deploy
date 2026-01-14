#!/usr/bin/env python3
"""
ECR repository management.
"""
import sys
import uuid
import boto3
from . import utils
from . import docker


def setup_ecr_repository(ecr_client, repository_name, allow_create=False):
    """
    Check if ECR repository exists, create if needed.
    """
    try:
        ecr_client.describe_repositories(repositoryNames=[repository_name])
        print(f"ECR repository {repository_name} already exists")
    except ecr_client.exceptions.RepositoryNotFoundException:
        if not allow_create:
            print(f"ECR repository '{repository_name}' does not exist and resource creation is disabled.")
            sys.exit(1)
            
        ecr_client.create_repository(repositoryName=repository_name)
        print(f"Created ECR repository: {repository_name}")


def build_and_push_image(ecr_client, repository_name, region, profile, dockerfile='Dockerfile'):
    """
    Build Docker image and push to ECR.
    Returns the image URI.
    """
    # Get account ID
    session = boto3.Session(profile_name=profile, region_name=region)
    account_id = session.client('sts').get_caller_identity().get('Account')
    
    # Generate a unique identifier for this deployment
    deployment_id = str(uuid.uuid4())[:8]
    image_tag = f"latest-{deployment_id}"
    image_name = f"{account_id}.dkr.ecr.{region}.amazonaws.com/{repository_name}:{image_tag}"
    
    # Ensure Docker is running
    docker.ensure_docker_running()
    
    # Build Docker image
    print(f"Building Docker image for linux/amd64 platform using {dockerfile}...")
    utils.run_command(
        f"docker build --platform=linux/amd64 -f {dockerfile} -t {repository_name}:{image_tag} .",
        "Failed to build Docker image",
        stream_output=True
    )
    
    # Tag Docker image for ECR
    print("Tagging Docker image for ECR...")
    utils.run_command(
        f"docker tag {repository_name}:{image_tag} {image_name}",
        "Failed to tag Docker image"
    )
    
    # Login to ECR
    print("Logging in to ECR...")
    utils.run_command(
        f"aws ecr get-login-password --region {region} --profile {profile} | docker login --username AWS --password-stdin {account_id}.dkr.ecr.{region}.amazonaws.com",
        "Failed to login to ECR"
    )
    
    # Push Docker image
    print("Pushing Docker image to ECR...")
    utils.run_command(
        f"docker push {image_name}",
        "Failed to push Docker image to ECR",
        stream_output=True
    )
    
    return image_name
