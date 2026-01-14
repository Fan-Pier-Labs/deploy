#!/usr/bin/env python3
"""
Unified deployment entry point.
Routes to AWS Fargate, Fly.io, or Vercel based on configuration.
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
            print("Please specify 'platform: \"fargate\"', 'platform: \"fly\"', or 'platform: \"vercel\"'")
            sys.exit(1)
        
        platform = config.get('platform', '').lower()
        
        if platform not in ['fargate', 'fly', 'vercel']:
            print(f"Error: Invalid platform '{platform}'. Must be 'fargate', 'fly', or 'vercel'")
            sys.exit(1)
        
        return config, platform
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Deploy app to Fargate, Fly.io, or Vercel')
    parser.add_argument('--config', type=str, default='deploy.yaml', 
                       help='Path to YAML configuration file (default: deploy.yaml)')
    
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
    
    # Validate fly platform doesn't support public domains
    if platform == 'fly':
        public_config = config.get('public')
        if public_config and public_config.get('domain'):
            print("Error: Fly.io deployment does not support public domains at this time")
            print("Please remove the 'public' section from your config or use platform: 'fargate' or 'vercel'")
            sys.exit(1)
    
    # Route to appropriate deployment module
    if platform == 'fargate':
        from aws.main import main as aws_main
        # Temporarily modify sys.argv to pass config to aws.main
        original_argv = sys.argv[:]
        sys.argv = [sys.argv[0], '--config', config_path]
        try:
            aws_main()
        finally:
            sys.argv = original_argv
    elif platform == 'fly':
        from fly.main import main as fly_main
        # Temporarily modify sys.argv to pass config to fly.main
        original_argv = sys.argv[:]
        sys.argv = [sys.argv[0], '--config', config_path]
        try:
            fly_main()
        finally:
            sys.argv = original_argv
    elif platform == 'vercel':
        from vercel.main import main as vercel_main
        # Temporarily modify sys.argv to pass config to vercel.main
        original_argv = sys.argv[:]
        sys.argv = [sys.argv[0], '--config', config_path]
        try:
            vercel_main()
        finally:
            sys.argv = original_argv


if __name__ == "__main__":
    main()
