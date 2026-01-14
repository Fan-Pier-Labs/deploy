#!/usr/bin/env python3
"""
Configuration loading and validation for Vercel deployment.
"""
import yaml
import sys
import os


def load_config(config_file):
    """
    Load configuration from YAML file for Vercel deployment.
    """
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        # Validate required fields
        if 'platform' not in config:
            print("Error: 'platform' is required in the configuration file")
            print("Please specify 'platform: \"fargate\"', 'platform: \"fly\"', or 'platform: \"vercel\"'")
            sys.exit(1)
        
        platform = config.get('platform', '').lower()
        if platform != 'vercel':
            print(f"Error: This deployment script is for Vercel, but platform is set to '{platform}'")
            print("Please set 'platform: \"vercel\"' in your configuration file")
            sys.exit(1)
        
        if 'app_name' not in config:
            print("Error: 'app_name' must be specified in the configuration")
            sys.exit(1)
        
        # Vercel configuration
        vercel_config = config.get('vercel', {})
        
        return {
            'app_name': config['app_name'],
            'environment': config.get('environment', {}),
            'public': config.get('public', {}),
            'vercel': {
                'project_name': vercel_config.get('project_name', config['app_name']),
                'team': vercel_config.get('team'),
                'scope': vercel_config.get('scope'),
                'prod': vercel_config.get('prod', True),
                'yes': vercel_config.get('yes', False),  # Skip confirmation prompts
            }
        }
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        sys.exit(1)
