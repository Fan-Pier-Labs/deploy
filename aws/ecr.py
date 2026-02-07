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


def build_image_only(repository_name, dockerfile='Dockerfile', build_context=None):
    """
    Build Docker image locally only (no ECR push, no deploy).
    Uses the same Buildx setup and cache as full deploy.
    Returns the local image tag (e.g. repository_name:latest-xxxx).
    """
    import os
    import uuid
    deployment_id = str(uuid.uuid4())[:8]
    image_tag = f"latest-{deployment_id}"
    docker.ensure_docker_running()
    docker.ensure_buildx_builder()
    cache_dir = ".buildx-cache-amd64"
    orig_cwd = os.getcwd()
    if build_context:
        os.chdir(build_context)
        print(f"Building from context: {build_context}")
    try:
        print(f"Building Docker image for linux/amd64 using Buildx and {dockerfile}...")
        utils.run_command(
            f"docker buildx build --platform=linux/amd64 --load "
            f"--cache-from type=local,src={cache_dir} "
            f"--cache-to type=local,dest={cache_dir},mode=max "
            f"-f {dockerfile} -t {repository_name}:{image_tag} .",
            "Failed to build Docker image",
            stream_output=True
        )
    finally:
        if build_context:
            os.chdir(orig_cwd)
    print(f"Built image: {repository_name}:{image_tag}")
    return f"{repository_name}:{image_tag}"


def build_and_push_image(ecr_client, repository_name, region, profile, dockerfile='Dockerfile', build_context=None):
    """
    Build Docker image and push to ECR.
    Returns the image URI.
    If build_context is set, the Docker build runs from that directory (e.g. config file dir).
    """
    import os
    # Get account ID
    session = boto3.Session(profile_name=profile, region_name=region)
    account_id = session.client('sts').get_caller_identity().get('Account')
    
    # Generate a unique identifier for this deployment
    deployment_id = str(uuid.uuid4())[:8]
    image_tag = f"latest-{deployment_id}"
    image_name = f"{account_id}.dkr.ecr.{region}.amazonaws.com/{repository_name}:{image_tag}"
    
    # Ensure Docker is running and a Buildx builder is selected
    docker.ensure_docker_running()
    docker.ensure_buildx_builder()

    # Build with Buildx so cache is architecture-specific (avoids ARM64/AMD64 cache
    # mixing when running on host vs in a dev container)
    cache_dir = ".buildx-cache-amd64"
    orig_cwd = os.getcwd()
    if build_context:
        os.chdir(build_context)
        print(f"Building from context: {build_context}")
    try:
        print(f"Building Docker image for linux/amd64 using Buildx and {dockerfile}...")
        utils.run_command(
            f"docker buildx build --platform=linux/amd64 --load "
            f"--cache-from type=local,src={cache_dir} "
            f"--cache-to type=local,dest={cache_dir},mode=max "
            f"-f {dockerfile} -t {repository_name}:{image_tag} .",
            "Failed to build Docker image",
            stream_output=True
        )
    finally:
        if build_context:
            os.chdir(orig_cwd)
    
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
