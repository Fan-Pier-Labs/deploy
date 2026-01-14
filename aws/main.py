#!/usr/bin/env python3
"""
CLI entry point for AWS Fargate deployment.
"""
import argparse
import sys
from . import deploy, config


def main():
    parser = argparse.ArgumentParser(description='Deploy app to AWS Fargate')
    parser.add_argument('--config', type=str, help='Path to YAML configuration file')
    parser.add_argument('--replicas', type=int, help='Number of task replicas to run')
    parser.add_argument('--no-spot', action='store_true', help='Use regular Fargate instead of Fargate Spot')
    parser.add_argument('--region', type=str, help='AWS region to deploy to')
    parser.add_argument('--allow-create', action='store_true', help='Allow creation of resources if they don\'t exist')
    parser.add_argument('--env', action='append', help='Environment variables in KEY=VALUE format (can be used multiple times)')
    parser.add_argument('--cpu', type=str, help='CPU units for the task (e.g., 256 for 0.25 vCPU)')
    parser.add_argument('--memory', type=str, help='Memory in MB for the task (e.g., 512 for 0.5 GB)')
    parser.add_argument('--ephemeral-storage', type=int, help='Ephemeral storage in GB (min: 20, max: 200)')
    parser.add_argument('--profile', type=str, help='AWS profile to use')
    parser.add_argument('--dockerfile', type=str, help='Name of the Dockerfile to use')
    
    args = parser.parse_args()
    
    # Load configuration from file if provided
    config_dict = {}
    if args.config:
        config_dict = config.load_config(args.config)
    
    # Command-line arguments override configuration file
    if args.replicas is not None:
        config_dict['replicas'] = args.replicas
    if args.no_spot:
        config_dict['spot'] = False
    elif 'spot' not in config_dict:
        config_dict['spot'] = True
    if args.region:
        config_dict['region'] = args.region
    if args.allow_create:
        config_dict['allow_create'] = True
    if args.cpu:
        config_dict['cpu'] = args.cpu
    if args.memory:
        config_dict['memory'] = args.memory
    if args.ephemeral_storage is not None:
        config_dict['ephemeral_storage'] = args.ephemeral_storage
    if args.profile:
        config_dict['profile'] = args.profile
    if args.dockerfile:
        config_dict['dockerfile'] = args.dockerfile
    
    # Parse environment variables
    if 'environment' not in config_dict:
        config_dict['environment'] = {}
    if args.env:
        for env_var in args.env:
            if '=' in env_var:
                key, value = env_var.split('=', 1)
                config_dict['environment'][key] = value
            else:
                print(f"Warning: Ignoring malformed environment variable: {env_var}")
    
    # Ensure app_name is set
    if 'app_name' not in config_dict:
        print("Error: 'app_name' must be specified in configuration file or as a parameter")
        sys.exit(1)
    
    # Validate lightweight mode requires exactly 1 replica
    public_config = config_dict.get('public') or {}
    if public_config.get('mode') == 'lightweight':
        replicas = config_dict.get('replicas', 1)
        if replicas != 1:
            print("Error: invalid config - 'lightweight' mode requires replicas to be 1")
            sys.exit(1)
    
    # Deploy with specified options
    deploy.deploy_to_fargate(config_dict=config_dict)


if __name__ == "__main__":
    main()
