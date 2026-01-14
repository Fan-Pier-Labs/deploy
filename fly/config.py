#!/usr/bin/env python3
"""
Configuration loading and validation for Fly.io deployment.
"""
import yaml
import sys
import os


def load_config(config_file):
    """
    Load configuration from YAML file for Fly.io deployment.
    """
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        # Extract configuration values
        task_config = config.get('task', {})
        
        # Validate required fields
        if 'platform' not in config:
            print("Error: 'platform' is required in the configuration file")
            print("Please specify 'platform: \"fargate\"' or 'platform: \"fly\"'")
            sys.exit(1)
        
        platform = config.get('platform', '').lower()
        if platform != 'fly':
            print(f"Error: This deployment script is for Fly.io, but platform is set to '{platform}'")
            print("Please set 'platform: \"fly\"' in your configuration file")
            sys.exit(1)
        
        if 'app_name' not in config:
            print("Error: 'app_name' must be specified in the configuration")
            sys.exit(1)
        
        # Validate that fly platform doesn't support public domains
        if platform == 'fly':
            public_config = config.get('public')
            if public_config and public_config.get('domain'):
                print("Error: Fly.io deployment does not support public domains at this time")
                print("Please remove the 'public' section from your config or use platform: 'fargate'")
                sys.exit(1)
        
        return {
            'app_name': config['app_name'],
            'dockerfile': config.get('dockerfile', 'Dockerfile'),
            'replicas': task_config.get('replicas', 1),
            'environment': config.get('environment', {})
        }
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        sys.exit(1)
