#!/usr/bin/env python3
"""
Configuration loading and validation for S3 deployments.
"""
import yaml
import sys
import os


def load_config(config_file):
    """
    Load configuration from YAML file for S3 deployment.
    """
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        # Extract configuration values with defaults
        aws_config = config.get('aws', {})
        s3_config = config.get('s3', {})
        public_config = config.get('public', {})
        
        # Validate platform is set and is s3
        if 'platform' not in config:
            print("Error: 'platform' is required in the configuration file")
            print("Please specify 'platform: \"s3\"'")
            sys.exit(1)
        
        platform = config.get('platform', '').lower()
        if platform != 's3':
            print(f"Error: This deployment script is for AWS S3, but platform is set to '{platform}'")
            print("Please set 'platform: \"s3\"' in your configuration file")
            sys.exit(1)
        
        # Validate required fields
        if 'app_name' not in config:
            print("Error: 'app_name' must be specified in the configuration")
            sys.exit(1)
        
        # Validate AWS configuration
        if 'region' not in aws_config:
            print("Error: 'region' must be specified in the AWS configuration")
            sys.exit(1)
        
        # Validate S3 configuration
        if 'folder' not in s3_config:
            print("Error: 'folder' must be specified in the S3 configuration")
            sys.exit(1)
        
        folder_path = s3_config['folder']
        
        # Resolve folder path (can be relative or absolute)
        if not os.path.isabs(folder_path):
            # Relative to config file directory
            config_dir = os.path.dirname(os.path.abspath(config_file))
            folder_path = os.path.join(config_dir, folder_path)
        
        # Validate folder exists
        if not os.path.exists(folder_path):
            print(f"Error: Folder '{folder_path}' does not exist")
            sys.exit(1)
        
        if not os.path.isdir(folder_path):
            print(f"Error: '{folder_path}' is not a directory")
            sys.exit(1)
        
        # Validate index.html exists
        index_path = os.path.join(folder_path, 'index.html')
        if not os.path.exists(index_path):
            print(f"Error: index.html not found in folder '{folder_path}'")
            sys.exit(1)
        
        # Validate public configuration if provided
        if public_config:
            if 'domain' not in public_config:
                print("Error: 'domain' must be specified in the public configuration")
                sys.exit(1)
        
        result = {
            'app_name': config['app_name'],
            'profile': aws_config.get('profile', 'personal'),
            'region': aws_config['region'],
            'allow_create': config.get('allow_create', False),
            'folder': folder_path,
            'bucket_name': s3_config.get('bucket_name'),  # Optional: user-specified bucket name
            'public': public_config if public_config else None
        }
        
        # Extract certificate_id from public config if provided
        if public_config and 'certificate_id' in public_config:
            result['certificate_id'] = public_config['certificate_id']
        
        return result
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        sys.exit(1)
