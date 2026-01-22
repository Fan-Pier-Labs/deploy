# Unified Deployment Tool

A unified deployment tool that supports deploying applications to **AWS Fargate**, **Fly.io**, **Vercel**, or **AWS S3** from a single configuration file. This tool simplifies multi-platform deployments by providing a consistent interface and configuration format across different cloud providers.

## Features

- **Multi-Platform Support**: Deploy to AWS Fargate, Fly.io, Vercel, or AWS S3 with a single tool
- **YAML Configuration**: Simple, declarative configuration files
- **Unified CLI**: Single entry point that routes to the appropriate platform
- **Flexible Deployment Options**: Support for internal services, public web apps, and serverless deployments
- **Environment Variables**: Easy configuration of environment variables via config file or CLI
- **Resource Management**: Automatic creation and management of cloud resources (AWS only)

## Installation

Add the deploy tool to your `package.json` as a dev dependency:

```json
{
  "devDependencies": {
    "deploy": "git@github.com:Fan-Pier-Labs/deploy.git"
  },
  "scripts": {
    "deploy": "python3 ./node_modules/deploy/main.py --config deploy.yaml"
  }
}
```

Then install dependencies:

```bash
bun install  # or npm install / yarn install
```

## Quick Start

1. Create a `deploy.yaml` configuration file in your project directory:

```yaml
platform: "fargate"  # or "fly", "vercel", or "s3"
app_name: "my-app"
aws:
  profile: "personal"
  region: "us-east-2"
task:
  cpu: 1024
  memory: 2048
  replicas: 1
environment:
  NODE_ENV: "production"
```

2. Run the deployment:

```bash
bun run deploy
```

## Configuration

The tool uses YAML configuration files to define deployment settings. The `platform` field determines which deployment module is used.

### Platform Options

- `fargate`: Deploy to AWS Fargate (containerized workloads)
- `fly`: Deploy to Fly.io (containerized workloads)
- `vercel`: Deploy to Vercel (serverless/edge functions)
- `s3`: Deploy static websites to AWS S3 with CloudFront

### Common Configuration Fields

```yaml
platform: "fargate"  # Required: "fargate", "fly", "vercel", or "s3"
app_name: "my-app"   # Required: Application name
environment:         # Optional: Environment variables
  KEY1: "value1"
  KEY2: "value2"
```

## Platform-Specific Configuration

### AWS Fargate

Deploy containerized applications to AWS Fargate with support for both internal services and public-facing web applications.

**Basic Configuration:**
```yaml
platform: "fargate"
app_name: "my-app"
aws:
  profile: "personal"
  region: "us-east-2"
task:
  cpu: 1024
  memory: 2048
  spot: true
  replicas: 1
  ephemeral_storage: 50
allow_create: true
```

**Public Web Application (Production):**
```yaml
platform: "fargate"
app_name: "my-app"
public:
  domain: "app.example.com"
  mode: "production"  # Uses CloudFront + ALB
task:
  port: 8080
  cpu: 1024
  memory: 2048
  replicas: 2
aws:
  region: "us-east-2"
```

**Public Web Application (Lightweight):**
```yaml
platform: "fargate"
app_name: "my-app"
public:
  domain: "test.example.com"
  mode: "lightweight"  # Direct to Fargate (ephemeral IPs)
task:
  replicas: 1  # Must be 1 for lightweight mode
```

**Features:**
- Automatic VPC, subnet, and security group management
- ECR repository creation and image pushing
- ECS cluster, service, and task definition management
- CloudWatch Logs integration
- Route53 DNS management
- CloudFront distribution (production mode)
- Application Load Balancer (production mode)
- Fargate Spot support for cost savings

**Command-Line Options:**
```bash
bun run deploy -- --replicas 2 --cpu 2048 --memory 4096 \
  --env NODE_ENV=production --env API_KEY=secret
```

### Fly.io

Deploy containerized applications to Fly.io.

**Configuration:**
```yaml
platform: "fly"
app_name: "my-app"
replicas: 2
environment:
  NODE_ENV: "production"
```

**Note:** Fly.io deployment does not currently support public domain configuration. Use `fargate` or `vercel` platforms for public domains.

**Command-Line Options:**
```bash
bun run deploy -- --replicas 2 --env NODE_ENV=production
```

### Vercel

Deploy serverless applications and edge functions to Vercel.

**Configuration:**
```yaml
platform: "vercel"
app_name: "my-app"
vercel:
  prod: true  # Deploy to production
environment:
  NODE_ENV: "production"
```

**Command-Line Options:**
```bash
bun run deploy -- --prod --yes --env NODE_ENV=production
```

### AWS S3

Deploy static websites to AWS S3 with CloudFront distribution and Route53 DNS.

**Configuration:**
```yaml
platform: "s3"
app_name: "my-static-site"
aws:
  profile: "personal"
  region: "us-east-2"
s3:
  folder: "./dist"  # Path to folder containing static files (must have index.html)
public:
  domain: "app.example.com"
allow_create: true
```

**Features:**
- Automatic S3 bucket creation and configuration
- Static website hosting setup
- CloudFront distribution with 10-minute cache
- Route53 DNS management
- SSL certificate management (ACM)
- Validates that `index.html` exists in the folder

**Requirements:**
- The specified folder must contain an `index.html` file
- Folder path can be relative (to config file) or absolute

**Command-Line Options:**
```bash
bun run deploy -- --allow-create --region us-east-2
```

**Architecture:**
- Route53 → CloudFront (10 min cache) → S3 Bucket

## Usage

### Basic Deployment

```bash
# Deploy using the npm/bun script (uses deploy.yaml by default)
bun run deploy

# Or run directly with a custom config file
python3 ./node_modules/deploy/main.py --config my-config.yaml
```

### Platform-Specific Deployment

You can also use the platform-specific modules directly:

```bash
# AWS Fargate
python3 ./node_modules/deploy/aws/main.py --config deploy.yaml

# Fly.io
python3 ./node_modules/deploy/fly/main.py --config deploy.yaml

# Vercel
python3 ./node_modules/deploy/vercel/main.py --config deploy.yaml
```

## Project Structure

```
deploy/
├── main.py              # Unified entry point
├── aws/                 # AWS Fargate deployment module
│   ├── main.py
│   ├── deploy.py
│   ├── config.py
│   ├── ecs.py
│   ├── ecr.py
│   ├── vpc.py
│   ├── alb.py
│   ├── cloudfront.py
│   ├── route53.py
│   └── ...
├── fly/                 # Fly.io deployment module
│   ├── main.py
│   ├── deploy.py
│   └── config.py
├── vercel/              # Vercel deployment module
│   ├── main.py
│   ├── deploy.py
│   └── config.py
└── s3/                  # AWS S3 static website deployment module
    ├── main.py
    ├── deploy.py
    ├── config.py
    ├── s3_bucket.py
    └── cloudfront_s3.py
```

## Requirements

- Python 3.x
- AWS CLI configured (for Fargate deployments)
- Fly.io CLI installed and authenticated (for Fly deployments)
- Vercel CLI installed and authenticated (for Vercel deployments)
- Docker (for containerized deployments)

## Notes

- **Fly.io**: Public domain support is not available. Use `fargate` or `vercel` for public-facing applications.
- **AWS Fargate Lightweight Mode**: Points directly to Fargate task IPs, which are ephemeral. DNS records may need updating on each deployment. For production, use `production` mode.
- **AWS Fargate Production Mode**: Creates a full infrastructure stack with CloudFront, ALB, and Route53 for stable, production-ready deployments.

## License

[Add your license information here]
