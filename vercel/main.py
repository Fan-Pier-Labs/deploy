#!/usr/bin/env python3
"""
CLI entry point for Vercel deployment.
"""
import argparse
import sys
from . import deploy, config


def main():
    parser = argparse.ArgumentParser(description='Deploy app to Vercel')
    parser.add_argument('--config', type=str, help='Path to YAML configuration file')
    parser.add_argument('--env', action='append', help='Environment variables in KEY=VALUE format (can be used multiple times)')
    parser.add_argument('--prod', action='store_true', help='Deploy to production (default: True)')
    parser.add_argument('--no-prod', action='store_true', help='Deploy to preview environment')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation prompts')
    
    args = parser.parse_args()
    
    # Load configuration from file if provided
    config_dict = {}
    if args.config:
        config_dict = config.load_config(args.config)
    
    # Command-line arguments override configuration file
    if args.prod:
        if 'vercel' not in config_dict:
            config_dict['vercel'] = {}
        config_dict['vercel']['prod'] = True
    if args.no_prod:
        if 'vercel' not in config_dict:
            config_dict['vercel'] = {}
        config_dict['vercel']['prod'] = False
    if args.yes:
        if 'vercel' not in config_dict:
            config_dict['vercel'] = {}
        config_dict['vercel']['yes'] = True
    
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
    
    # Deploy with specified options
    deploy.deploy_to_vercel(config_dict=config_dict)


if __name__ == "__main__":
    main()
