# AWS Deployment Tool (CloudFormation)

Deploy to **AWS S3** (static sites) or **AWS Fargate** (ECS) from a single YAML config. One command: **generate CloudFormation** from your config, then **deploy** via the AWS CLI. No local stack file unless you pass `--debug-save-stack-locally`.

## Features

- **YAML config** → CloudFormation template generation → deploy in one command
- **S3**: Static website + optional CloudFront + Route53
- **Fargate**: ECS cluster, service, ALB, CloudFront, Route53 (no lightweight mode)
- **Automatic ACM**: Find existing cert (exact or wildcard) or request + DNS validate via Route53 (Python/boto3)
- **Post-deploy**: S3 sync; Docker build/push + ECR for Fargate

## Quick Start

1. Create `deploy.yaml`:

```yaml
platform: "s3"   # or "fargate"
app_name: "my-app"
aws:
  profile: "personal"
  region: "us-east-2"
s3:
  folder: "."
public:
  domain: "app.example.com"
allow_create: true
```

2. Deploy:

```bash
python3 main.py --config deploy.yaml
```

## Platform Options

- **s3**: Static website in S3, optional CloudFront + Route53. Requires `s3.folder`; if `public.domain` is set, hosted zone and certificate are resolved automatically.
- **fargate**: ECS Fargate service. Builds and pushes Docker image to ECR, then deploys stack. Public domain always uses CloudFront + ALB.

## Configuration

### Common

```yaml
platform: "s3" | "fargate"
app_name: "my-app"
aws:
  profile: "personal"
  region: "us-east-2"
allow_create: true
```

### S3

```yaml
platform: "s3"
app_name: "my-static-site"
s3:
  folder: "./dist"           # Path to static files (must have index.html)
  bucket_name: "my-bucket"   # Optional; default derived from app_name
public:
  domain: "app.example.com"
```

### Fargate

```yaml
platform: "fargate"
app_name: "my-app"
aws:
  profile: "personal"
  region: "us-east-2"
task:
  cpu: 1024
  memory: 2048
  replicas: 1
  spot: true
  port: 8080
  ephemeral_storage: 50
  dockerfile: "Dockerfile"
environment:
  NODE_ENV: "production"
public:
  domain: "app.example.com"
allow_create: true
```

## Public domain (S3 and Fargate)

You only specify **`public.domain`** in `deploy.yaml`. The tool resolves the Route53 hosted zone from the domain and finds or requests the ACM certificate (us-east-1) automatically—including wildcard certs when they cover the domain. No `hosted_zone_id`, `certificate_id`, or `mode` in config.

## How to deploy

**Default (one command):** Generate the CloudFormation template (in memory / temp file) and deploy. No stack file is written to disk unless you pass `--debug-save-stack-locally`.

```bash
python3 main.py --config deploy.yaml
```

**Debug: save the generated stack locally** while still deploying:

```bash
python3 main.py --config deploy.yaml --debug-save-stack-locally
# or to a specific file:
python3 main.py --config deploy.yaml --debug-save-stack-locally my-stack.yaml
```

**Two-step (generate, then deploy yourself):** Generate `stack.yaml` in the current directory, then deploy with the AWS CLI.

```bash
# 1. Generate stack.yaml (no deploy)
python3 main.py --config deploy.yaml -o stack.yaml

# 2. Deploy the stack (S3 example; pass parameters your config needs)
aws cloudformation deploy \
  --template-file stack.yaml \
  --stack-name my-app-stack \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides CertificateArn=arn:aws:acm:us-east-1:ACCOUNT:certificate/ID HostedZoneId=Z123...

# For S3, then upload files and invalidate CDN:
aws s3 sync ./dist s3://BUCKET_NAME/ --delete
aws cloudfront create-invalidation --distribution-id DIST_ID --paths "/*"
```

For **Fargate** you must build/push the image first, then pass `ImageUri`, `VpcId`, and `SubnetIds` to `--parameter-overrides`.

## CLI

```bash
# Deploy (generate template + deploy)
python3 main.py --config deploy.yaml

# Debug: save generated template to stack-debug.yaml (or named file) when deploying
python3 main.py --config deploy.yaml --debug-save-stack-locally
python3 main.py --config deploy.yaml --debug-save-stack-locally my-stack.yaml

# Only generate CloudFormation (no deploy); write to file
python3 main.py --config deploy.yaml -o stack.yaml
python3 main.py --config deploy.yaml --no-deploy   # print to stdout

# Custom stack name
python3 main.py --config deploy.yaml --stack-name my-stack
```

## Generate template only

```bash
python3 -m cloudformation.generator --config deploy.yaml -o template.yaml
```

## Project structure

```
deploy/
├── main.py                 # Entry: load YAML, generate CFN, deploy via AWS CLI
├── cloudformation/         # Generate CloudFormation from YAML
│   ├── generator.py
│   ├── s3_template.py
│   └── fargate_template.py
├── cert_resolve.py         # ACM find/request + Route53 validation (boto3)
├── aws/                    # Used by cert_resolve (acm, route53)
└── s3/                     # Legacy (not used by main deploy)
```

## Requirements

- Python 3.x (PyYAML; boto3 for automatic ACM/Route53 when cert not provided)
- AWS CLI installed and configured
- Docker (for Fargate builds)
- For public domains: only `public.domain` is required in config; hosted zone and certificate are resolved automatically.

## Notes

- **Fargate**: Uses default VPC and first two subnets unless you pass them. Image is built and pushed to ECR before stack deploy.
- **S3**: After stack deploy, files are synced with `aws s3 sync`. CloudFront cache is invalidated if a distribution exists.
- **Teardown**: Delete the CloudFormation stack (`aws cloudformation delete-stack --stack-name <name>`) to remove all resources.
