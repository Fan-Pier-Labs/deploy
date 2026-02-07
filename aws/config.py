#!/usr/bin/env python3
"""
Configuration loading and validation.
"""
import yaml
import sys
from .utils import parse_ephemeral_storage


def load_config(config_file):
    """
    Load configuration from YAML file.
    """
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        # Extract configuration values with defaults
        aws_config = config.get('aws', {})
        task_config = config.get('task', {})
        public_config = config.get('public', {})
        
        # Validate platform is set and is fargate
        if 'platform' not in config:
            print("Error: 'platform' is required in the configuration file")
            print("Please specify 'platform: \"fargate\"' or 'platform: \"fly\"'")
            sys.exit(1)
        
        platform = config.get('platform', '').lower()
        if platform != 'fargate':
            print(f"Error: This deployment script is for AWS Fargate, but platform is set to '{platform}'")
            print("Please set 'platform: \"fargate\"' in your configuration file")
            sys.exit(1)
        
        # Default IAM permissions if not specified
        default_iam_permissions = [
            'arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy',
            'arn:aws:iam::aws:policy/AmazonSQSFullAccess',
            'arn:aws:iam::aws:policy/AmazonS3FullAccess'
        ]
        
        # Validate required fields
        if 'app_name' not in config:
            print("Error: 'app_name' must be specified in the configuration")
            sys.exit(1)
        if 'cpu' not in task_config:
            print("Error: 'cpu' must be specified in the task configuration")
            sys.exit(1)
        if 'memory' not in task_config:
            print("Error: 'memory' must be specified in the task configuration")
            sys.exit(1)
        if 'ephemeral_storage' not in task_config:
            print("Error: 'ephemeral_storage' must be specified in the task configuration")
            sys.exit(1)
        
        # Validate AWS configuration
        if 'region' not in aws_config:
            print("Error: 'region' must be specified in the AWS configuration")
            sys.exit(1)
        
        # Validate public configuration if provided
        if public_config:
            if 'domain' not in public_config:
                print("Error: 'domain' must be specified in the public configuration")
                sys.exit(1)
            if 'mode' in public_config:
                mode = public_config['mode']
                if mode not in ['lightweight', 'production']:
                    print("Error: 'mode' must be either 'lightweight' or 'production'")
                    sys.exit(1)
                # Validate that lightweight mode requires exactly 1 replica
                if mode == 'lightweight':
                    replicas = task_config.get('replicas', 1)
                    if replicas != 1:
                        print("Error: invalid config - 'lightweight' mode requires replicas to be 1")
                        sys.exit(1)
        
        # Parse ephemeral_storage (supports both integer and string formats like "21gb")
        try:
            ephemeral_storage = parse_ephemeral_storage(task_config['ephemeral_storage'])
        except ValueError as e:
            print(f"Error: {str(e)}")
            sys.exit(1)
        
        result = {
            'app_name': config['app_name'],
            'service_name': config.get('service_name', f"{config['app_name']}-service"),
            'profile': aws_config.get('profile', 'personal'),
            'region': aws_config['region'],
            'cpu': str(task_config['cpu']),
            'memory': str(task_config['memory']),
            'spot': task_config.get('spot', True),
            'replicas': task_config.get('replicas', 1),
            'ephemeral_storage': ephemeral_storage,
            'allow_create': config.get('allow_create', False),
            'environment': config.get('environment', {}),
            'iam_permissions': config.get('iam_permissions', default_iam_permissions),
            'custom_iam_policy': config.get('custom_iam_policy', None),
            'dockerfile': config.get('dockerfile', 'Dockerfile'),
            'public': public_config if public_config else None,
            'port': task_config.get('port', 8080),  # Default port for container
            'health_check_path': config.get('health_check_path', '/api/health')
        }
        
        # Extract certificate_id from public config if provided
        if public_config and 'certificate_id' in public_config:
            result['certificate_id'] = public_config['certificate_id']
        
        return result
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        sys.exit(1)
