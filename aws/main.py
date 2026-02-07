#!/usr/bin/env python3
"""
CLI entry point for AWS Fargate deployment.
"""
import sys
from . import deploy, config, destroy


def main(config_file=None, destroy_infra=False, build_only=False):
    """
    Deploy to AWS Fargate using configuration from file.
    
    Args:
        config_file: Path to YAML configuration file. If None, will try to get from sys.argv.
        destroy_infra: If True, run teardown (--destroy) instead of deploy.
        build_only: If True, only build the Docker image; do not push or deploy.
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
    config_dict["_config_file"] = config_file  # so deploy can use config dir as Docker build context

    if destroy_infra:
        destroy.destroy_fargate_infra(config_dict)
        return

    if build_only:
        from . import ecr
        build_context = None
        if config_dict.get("_config_file"):
            import os
            build_context = os.path.dirname(os.path.abspath(config_dict["_config_file"]))
            if not os.path.isdir(build_context):
                build_context = None
        ecr.build_image_only(
            config_dict["app_name"].lower(),
            dockerfile=config_dict.get("dockerfile", "Dockerfile"),
            build_context=build_context,
        )
        return
    
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
