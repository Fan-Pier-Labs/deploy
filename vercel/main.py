#!/usr/bin/env python3
"""
CLI entry point for Vercel deployment.
"""
import sys
from . import deploy, config


def main(config_file=None):
    """
    Deploy to Vercel using configuration from file.
    
    Args:
        config_file: Path to YAML configuration file. If None, will try to get from sys.argv.
    """
    # Get config file from argument or sys.argv (for backward compatibility)
    if config_file is None:
        if len(sys.argv) > 2 and sys.argv[1] == '--config':
            config_file = sys.argv[2]
        else:
            print("Error: Configuration file must be specified")
            sys.exit(1)
    
    # Load configuration from file
    config_dict = config.load_config(config_file)
    
    # Deploy with specified options
    deploy.deploy_to_vercel(config_dict=config_dict)


if __name__ == "__main__":
    main()
