#!/usr/bin/env python3
"""
Unified deployment entry point.
Routes to AWS Fargate, Fly.io, or S3 based on configuration.
Note: Vercel deployment is currently disabled and needs to be tested.
"""
import sys
import os
import yaml
import argparse

# Add the current directory to the path so we can import aws and fly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_config(config_file):
    """
    Load configuration from YAML file and determine platform.
    """
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        # Platform is required
        if 'platform' not in config:
            print("Error: 'platform' is required in the configuration file")
            print("Please specify 'platform: \"fargate\"', 'platform: \"fly\"', or 'platform: \"s3\"'")
            print("Note: 'platform: \"vercel\"' is currently disabled and needs to be tested before use.")
            sys.exit(1)
        
        platform = config.get('platform', '').lower()
        
        if platform not in ['fargate', 'fly', 'vercel', 's3']:
            print(f"Error: Invalid platform '{platform}'. Must be 'fargate', 'fly', or 's3'")
            print("Note: 'vercel' is currently disabled and needs to be tested before use.")
            sys.exit(1)
        
        return config, platform
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Deploy app to Fargate, Fly.io, or S3 (Vercel is currently disabled)')
    parser.add_argument('--config', type=str, default='deploy.yaml', 
                       help='Path to YAML configuration file (default: deploy.yaml)')
    parser.add_argument('--destroy', action='store_true',
                       help='Teardown all deployment infrastructure (S3 and Fargate). Prompts for confirmation.')
    parser.add_argument('--build-only', action='store_true',
                       help='Only build the Docker image; do not push to ECR or deploy.')
    
    args = parser.parse_args()
    
    # Resolve config file path - only check current directory
    config_path = args.config
    if not os.path.isabs(config_path):
        # Check current directory (where the command is run from)
        current_dir_config = os.path.join(os.getcwd(), config_path)
        if os.path.exists(current_dir_config):
            config_path = current_dir_config
        else:
            print(f"Error: Configuration file not found: {args.config}")
            print(f"Looked in: {current_dir_config}")
            sys.exit(1)
    
    # Load configuration and determine platform
    config, platform = load_config(config_path)
    
    # Disable Vercel option - needs to be tested before it can be used
    if platform == 'vercel':
        print("Error: Vercel deployment is currently disabled")
        print("The Vercel deployment option needs to be tested before it can be used.")
        print("Please use 'platform: \"fargate\"', 'platform: \"fly\"', or 'platform: \"s3\"' instead.")
        sys.exit(1)
    
    # Validate fly platform doesn't support public domains
    if platform == 'fly':
        public_config = config.get('public')
        if public_config and public_config.get('domain'):
            print("Error: Fly.io deployment does not support public domains at this time")
            print("Please remove the 'public' section from your config or use platform: 'fargate' or 's3'")
            sys.exit(1)
    
    if args.destroy and platform not in ('s3', 'fargate'):
        print("Error: --destroy is only supported for platform: s3 or fargate")
        sys.exit(1)
    
    if args.build_only and platform != 'fargate':
        print("Error: --build-only is only supported for platform: fargate")
        sys.exit(1)
    
    # Route to appropriate deployment module
    if platform == 'fargate':
        from aws.main import main as aws_main
        aws_main(config_file=config_path, destroy_infra=args.destroy, build_only=args.build_only)
    elif platform == 'fly':
        from fly.main import main as fly_main
        fly_main(config_file=config_path)
    elif platform == 'vercel':
        from vercel.main import main as vercel_main
        vercel_main(config_file=config_path)
    elif platform == 's3':
        from s3.main import main as s3_main
        s3_main(config_file=config_path, destroy_infra=args.destroy)


if __name__ == "__main__":
    main()
