#!/usr/bin/env python3
"""
Deploy via CloudFormation: read user YAML, generate CloudFormation template, deploy to AWS.
Supports platform: s3 (static site) and fargate (ECS).
"""
import os
import sys
import subprocess
import tempfile
import argparse


def run(cmd, check=True, capture=False, env=None):
    """Run command; return (ok, output)."""
    e = env or os.environ.copy()
    try:
        out = subprocess.run(
            cmd,
            shell=False,
            check=check,
            capture_output=capture,
            text=True,
            env=e,
        )
        return (True, out.stdout.strip() if capture else None)
    except subprocess.CalledProcessError as err:
        if capture:
            sys.stderr.write((err.stderr or "") + "\n")
        return (False, err.stderr if capture else None)


def get_default_vpc_and_subnets(profile, region):
    """Return (vpc_id, [subnet_id, ...]) using AWS CLI."""
    env = os.environ.copy()
    if profile:
        env["AWS_PROFILE"] = profile
    env["AWS_DEFAULT_REGION"] = region
    ok, vpc = run(
        ["aws", "ec2", "describe-vpcs", "--filters", "Name=isDefault,Values=true", "--query", "Vpcs[0].VpcId", "--output", "text"],
        env=env,
        capture=True,
    )
    if not ok or not vpc or vpc == "None":
        print("Error: No default VPC found. Create a VPC or pass VpcId/SubnetIds.", file=sys.stderr)
        sys.exit(1)
    ok, subnets = run(
        ["aws", "ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={vpc}", "--query", "Subnets[*].SubnetId", "--output", "text"],
        env=env,
        capture=True,
    )
    if not ok or not subnets:
        print("Error: No subnets found in default VPC.", file=sys.stderr)
        sys.exit(1)
    subnet_list = subnets.split()
    return (vpc, subnet_list[:2])  # at most 2


def get_hosted_zone_id(domain, profile, region):
    """Resolve Route53 hosted zone ID for domain (e.g. example.com -> zone for example.com)."""
    env = os.environ.copy()
    if profile:
        env["AWS_PROFILE"] = profile
    env["AWS_DEFAULT_REGION"] = region
    parts = domain.split(".")
    for i in range(len(parts)):
        zone_name = ".".join(parts[i:])
        if not zone_name.endswith("."):
            zone_name += "."
        ok, zid = run(
            ["aws", "route53", "list-hosted-zones", "--query", f"HostedZones[?Name=='{zone_name}'].Id", "--output", "text"],
            env=env,
            capture=True,
        )
        if ok and zid and zid != "None":
            return zid.strip().replace("/hostedzone/", "")
    return None


def resolve_cert_arn_for_domain(profile, region, domain, public_config, allow_create=True):
    """
    Resolve ACM certificate ARN for CloudFront (us-east-1).
    If public has certificate_arn or certificate_id, use that.
    Otherwise use Python (boto3) to find existing cert (exact/wildcard) or request + validate via Route53.
    """
    cert_arn = public_config.get("certificate_arn") or public_config.get("certificate_id")
    if cert_arn:
        if isinstance(cert_arn, str) and cert_arn.isdigit():
            acc = get_account_id(profile, region)
            return f"arn:aws:acm:us-east-1:{acc}:certificate/{cert_arn}"
        return cert_arn
    # Automatic: find or request + validate (Python outside CloudFormation)
    from cert_resolve import resolve_cert_arn
    return resolve_cert_arn(profile, domain, allow_create=allow_create, region_hint=region)


def remove_cloudfront_distribution_with_alias(profile, domain):
    """
    If a CloudFront distribution already has this domain as an alias, disable and delete it
    so the new stack can create one with the same alias. CloudFront is global (no region).
    """
    try:
        import boto3
    except ImportError:
        return
    session = boto3.Session(profile_name=profile) if profile and profile != "default" else boto3.Session()
    cf = session.client("cloudfront")
    paginator = cf.get_paginator("list_distributions")
    dist_id = None
    for page in paginator.paginate():
        for item in page.get("DistributionList", {}).get("Items", []):
            aliases = item.get("Aliases", {}).get("Items", [])
            if domain in aliases:
                dist_id = item["Id"]
                break
        if dist_id:
            break
    if not dist_id:
        return
    print(f"Removing existing CloudFront distribution {dist_id} that uses alias {domain}...")
    config_resp = cf.get_distribution_config(Id=dist_id)
    etag = config_resp["ETag"]
    config = config_resp["DistributionConfig"]
    config["Enabled"] = False
    cf.update_distribution(Id=dist_id, DistributionConfig=config, IfMatch=etag)
    # Wait for deployment (can take several minutes)
    import time
    for _ in range(60):
        resp = cf.get_distribution(Id=dist_id)
        status = resp["Distribution"].get("Status", "")
        if status == "Deployed":
            break
        time.sleep(10)
    etag = cf.get_distribution_config(Id=dist_id)["ETag"]
    cf.delete_distribution(Id=dist_id, IfMatch=etag)
    print(f"Deleted distribution {dist_id}.")


def get_account_id(profile, region):
    """Return AWS account ID."""
    env = os.environ.copy()
    if profile:
        env["AWS_PROFILE"] = profile
    env["AWS_DEFAULT_REGION"] = region
    ok, aid = run(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"], env=env, capture=True)
    if not ok or not aid:
        return None
    return aid.strip()


def ecr_ensure_repo(profile, region, repo_name):
    """Create ECR repository if it doesn't exist. Return repo URI (without tag)."""
    env = os.environ.copy()
    if profile:
        env["AWS_PROFILE"] = profile
    env["AWS_DEFAULT_REGION"] = region
    run(
        ["aws", "ecr", "describe-repositories", "--repository-names", repo_name],
        check=False,
        env=env,
    )
    # If describe fails, create
    run(
        ["aws", "ecr", "create-repository", "--repository-name", repo_name],
        check=False,
        env=env,
    )
    account = get_account_id(profile, region)
    return f"{account}.dkr.ecr.{region}.amazonaws.com/{repo_name}"


def docker_build_push(profile, region, app_name, dockerfile="Dockerfile", tag="latest"):
    """Build image and push to ECR. Return full image URI."""
    repo_name = app_name.lower()
    repo_uri = ecr_ensure_repo(profile, region, repo_name)
    image_uri = f"{repo_uri}:{tag}"
    env = os.environ.copy()
    if profile:
        env["AWS_PROFILE"] = profile
    # Login to ECR
    ok, passwd = run(
        ["aws", "ecr", "get-login-password", "--region", region],
        env=env,
        capture=True,
    )
    if not ok:
        print("Error: Failed to get ECR login password.", file=sys.stderr)
        sys.exit(1)
    import base64
    # Docker login via stdin
    proc = subprocess.Popen(
        ["docker", "login", "--username", "AWS", "--password-stdin", repo_uri.split("/")[0]],
        stdin=subprocess.PIPE,
        env=env,
    )
    proc.communicate(input=passwd.encode())
    if proc.returncode != 0:
        print("Error: Docker login to ECR failed.", file=sys.stderr)
        sys.exit(1)
    # Build and push
    if run(["docker", "build", "-t", image_uri, "-f", dockerfile, "."], env=env)[0]:
        if run(["docker", "push", image_uri], env=env)[0]:
            return image_uri
    print("Error: Docker build or push failed.", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Deploy app to AWS via CloudFormation (s3 or fargate)")
    parser.add_argument("--config", "-c", default="deploy.yaml", help="Path to YAML config")
    parser.add_argument("--output", "-o", help="Write generated CloudFormation to this file only (no deploy)")
    parser.add_argument("--debug-save-stack-locally", metavar="FILE", nargs="?", const="stack-debug.yaml", help="When deploying, save the generated template to FILE (default: stack-debug.yaml) in current directory")
    parser.add_argument("--no-deploy", action="store_true", help="Only generate template; do not deploy")
    parser.add_argument("--stack-name", help="CloudFormation stack name (default: from app_name)")
    args = parser.parse_args()

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.getcwd(), config_path)
    if not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from cloudformation.generator import load_config, generate

    config, platform = load_config(config_path)
    app_name = config["app_name"]
    aws_cfg = config.get("aws", {})
    profile = aws_cfg.get("profile", "default")
    region = aws_cfg.get("region", "us-east-2")
    stack_name = args.stack_name or f"{app_name}-stack"

    template, _, output_yaml = generate(config_path, out_path=None)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_yaml)
        print(f"Wrote CloudFormation to {args.output}")
        return
    if args.no_deploy:
        print(output_yaml)
        return

    # Debug: save generated template locally when flag is set
    if args.debug_save_stack_locally:
        save_path = args.debug_save_stack_locally
        if not os.path.isabs(save_path):
            save_path = os.path.join(os.getcwd(), save_path)
        with open(save_path, "w") as f:
            f.write(output_yaml)
        print(f"Saved template to {save_path}")

    # Write template to temp file for deploy
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(output_yaml)
        template_file = f.name
    try:
        env = os.environ.copy()
        if profile:
            env["AWS_PROFILE"] = profile
        env["AWS_DEFAULT_REGION"] = region

        if platform == "s3":
            params = []
            s3_cfg = config.get("s3", {})
            folder = s3_cfg.get("folder", ".")
            if not os.path.isabs(folder):
                folder = os.path.join(os.path.dirname(config_path), folder)
            public = config.get("public") or {}
            if public.get("domain"):
                domain = public["domain"]
                remove_cloudfront_distribution_with_alias(profile, domain)
                allow_create = config.get("allow_create", True)
                cert_arn = resolve_cert_arn_for_domain(profile, region, domain, public, allow_create=allow_create)
                params.append(f"CertificateArn={cert_arn}")
                zone_id = public.get("hosted_zone_id") or get_hosted_zone_id(domain, profile, region)
                if not zone_id:
                    print("Error: Could not resolve Route53 hosted zone for domain. Set public.hosted_zone_id in config.", file=sys.stderr)
                    sys.exit(1)
                params.append(f"HostedZoneId={zone_id}")

            cmd = ["aws", "cloudformation", "deploy", "--template-file", template_file, "--stack-name", stack_name, "--capabilities", "CAPABILITY_IAM", "--no-fail-on-empty-changeset"]
            if params:
                cmd.extend(["--parameter-overrides"] + params)
            ok, _ = run(cmd, env=env)
            if not ok:
                sys.exit(1)
            # Upload files to bucket (get name from stack output)
            ok, out = run(["aws", "cloudformation", "describe-stacks", "--stack-name", stack_name, "--query", "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue", "--output", "text"], env=env, capture=True)
            bucket_name = out.strip() if ok and out else None
            if bucket_name and os.path.isdir(folder):
                print("Uploading files to S3...")
                run(["aws", "s3", "sync", folder, f"s3://{bucket_name}/", "--delete"], env=env)
                # Invalidate CloudFront if present
                if "CloudFrontId" in template.get("Outputs", {}):
                    ok, cf_id = run(["aws", "cloudformation", "describe-stacks", "--stack-name", stack_name, "--query", "Stacks[0].Outputs[?OutputKey=='CloudFrontId'].OutputValue", "--output", "text"], env=env, capture=True)
                    if ok and cf_id and cf_id.strip():
                        run(["aws", "cloudfront", "create-invalidation", "--distribution-id", cf_id.strip(), "--paths", "/*"], env=env, check=False)
            print("Deploy complete.")

        else:
            # Fargate: need ImageUri, VpcId, SubnetIds
            public = config.get("public") or {}
            if public.get("domain"):
                remove_cloudfront_distribution_with_alias(profile, public["domain"])
            vpc_id, subnet_ids = get_default_vpc_and_subnets(profile, region)
            subnet_str = ",".join(subnet_ids)
            dockerfile = config.get("dockerfile", "Dockerfile")
            image_uri = docker_build_push(profile, region, app_name, dockerfile=dockerfile)
            params = [
                f"ImageUri={image_uri}",
                f"VpcId={vpc_id}",
                f"SubnetIds={subnet_str}",
            ]
            if public.get("domain"):
                domain = public["domain"]
                allow_create = config.get("allow_create", True)
                cert_arn = resolve_cert_arn_for_domain(profile, region, domain, public, allow_create=allow_create)
                params.append(f"CertificateArn={cert_arn}")
                zone_id = public.get("hosted_zone_id") or get_hosted_zone_id(domain, profile, region)
                if zone_id:
                    params.append(f"HostedZoneId={zone_id}")

            cmd = ["aws", "cloudformation", "deploy", "--template-file", template_file, "--stack-name", stack_name, "--capabilities", "CAPABILITY_NAMED_IAM", "--no-fail-on-empty-changeset", "--parameter-overrides"] + params
            ok, _ = run(cmd, env=env)
            if not ok:
                sys.exit(1)
            # Invalidate CloudFront if production
            if "CloudFrontId" in template.get("Outputs", {}):
                ok, cf_id = run(["aws", "cloudformation", "describe-stacks", "--stack-name", stack_name, "--query", "Stacks[0].Outputs[?OutputKey=='CloudFrontId'].OutputValue", "--output", "text"], env=env, capture=True)
                if ok and cf_id and cf_id.strip():
                    run(["aws", "cloudfront", "create-invalidation", "--distribution-id", cf_id.strip(), "--paths", "/*"], env=env, check=False)
            print("Deploy complete.")
    finally:
        os.unlink(template_file)


if __name__ == "__main__":
    main()
