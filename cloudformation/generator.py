#!/usr/bin/env python3
"""
Generate CloudFormation template from user YAML config.
"""
import sys
import yaml


def load_config(config_path):
    """Load and validate user YAML. Returns (config_dict, platform)."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    if not config:
        raise SystemExit("Config file is empty")
    platform = (config.get("platform") or "").lower()
    if platform not in ("s3", "fargate"):
        print("Error: 'platform' must be 's3' or 'fargate'", file=sys.stderr)
        sys.exit(1)
    if not config.get("app_name"):
        print("Error: 'app_name' is required", file=sys.stderr)
        sys.exit(1)
    return config, platform


def generate(config_path, out_path=None):
    """
    Load user YAML from config_path, generate CloudFormation YAML, optionally write to out_path.
    Returns the template dict and platform.
    """
    config, platform = load_config(config_path)
    if platform == "s3":
        from .s3_template import build_s3_template
        template = build_s3_template(config)
    else:
        from .fargate_template import build_fargate_template
        template = build_fargate_template(config)

    output = yaml.dump(template, default_flow_style=False, sort_keys=False, allow_unicode=True)
    if out_path:
        with open(out_path, "w") as f:
            f.write(output)
    return template, platform, output


def main():
    import argparse
    p = argparse.ArgumentParser(description="Generate CloudFormation from deploy YAML")
    p.add_argument("--config", "-c", default="deploy.yaml", help="User YAML config")
    p.add_argument("--output", "-o", help="Output CloudFormation file (default: stdout)")
    args = p.parse_args()
    _, _, output = generate(args.config, args.output)
    if not args.output:
        print(output)


if __name__ == "__main__":
    main()
