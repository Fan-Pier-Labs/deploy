#!/usr/bin/env python3
"""
CLI entry point for AWS S3 static website deployment.
"""
import sys
from . import deploy, config, destroy


def main(config_file=None, destroy_infra=False):
    """
    Deploy to AWS S3 using configuration from file.
    
    Args:
        config_file: Path to YAML configuration file. If None, will try to get from sys.argv.
        destroy_infra: If True, run teardown (--destroy) instead of deploy.
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
    
    if destroy_infra:
        destroy.destroy_s3_infra(config_dict)
    else:
        deploy.deploy_to_s3(config_dict=config_dict)


if __name__ == "__main__":
    main()
