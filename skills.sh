#!/bin/bash
# skills.sh - Guide for LLMs on writing deploy.yaml files
# This script documents all available options and configurations for deploy.yaml files

cat << 'EOF'
# Guide: How to Write deploy.yaml Files

This guide helps LLMs understand how to write deploy.yaml configuration files for the unified deployment tool.

## Overview

The deploy.yaml file is a YAML configuration file that defines how an application should be deployed. The `platform` field determines which deployment platform is used: "fargate", "fly", "vercel", or "s3".

## Common Fields (All Platforms)

### Required Fields
- `platform`: One of "fargate", "fly", "vercel", or "s3" (case-insensitive)
- `app_name`: A unique name for your application (string)

### Optional Fields
- `environment`: Dictionary of environment variables (key-value pairs)
- `allow_create`: Boolean (default: false) - Whether to allow creation of new cloud resources
- `dockerfile`: Path to Dockerfile (default: "Dockerfile") - Only for containerized platforms

## Platform: "fargate" (AWS Fargate)

Deploy containerized applications to AWS Fargate. Supports both internal services and public-facing web applications.

### Required Configuration

```yaml
platform: "fargate"
app_name: "my-app"
aws:
  region: "us-east-2"  # Required: AWS region
task:
  cpu: 1024            # Required: CPU units (256, 512, 1024, 2048, 4096, etc.)
  memory: 2048         # Required: Memory in MB
  ephemeral_storage: 50  # Required: Storage in GB (integer) or string like "21gb"
```

### Optional AWS Configuration

```yaml
aws:
  profile: "personal"  # Optional: AWS profile name (default: "personal")
  region: "us-east-2"  # Required: AWS region
```

### Optional Task Configuration

```yaml
task:
  cpu: 1024            # Required
  memory: 2048         # Required
  ephemeral_storage: 50  # Required: Can be integer (GB) or string like "21gb"
  replicas: 1          # Optional: Number of task replicas (default: 1)
  spot: true           # Optional: Use Fargate Spot for cost savings (default: true)
  port: 8080           # Optional: Container port (default: 8080)
```

### Optional Service Configuration

```yaml
service_name: "my-app-service"  # Optional: Custom service name (default: "{app_name}-service")
```

### Public Web Application Configuration

For public-facing applications, add a `public` section:

```yaml
public:
  domain: "app.example.com"  # Required: Domain name
  mode: "production"         # Optional: "production" or "lightweight" (default: "production")
  certificate_id: "arn:..."  # Optional: Pre-existing ACM certificate ARN
```

**Public Mode Options:**
- `production`: Full infrastructure with CloudFront + ALB + Route53 (stable, production-ready)
  - Supports multiple replicas
  - Provides stable IP addresses
  - Includes CDN caching
- `lightweight`: Direct to Fargate with ephemeral IPs (simpler, cheaper)
  - **Requires replicas: 1** (enforced validation)
  - IP addresses change on each deployment
  - No load balancer or CDN

### IAM Permissions

```yaml
iam_permissions:  # Optional: List of IAM policy ARNs
  - "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
  - "arn:aws:iam::aws:policy/AmazonSQSFullAccess"
  - "arn:aws:iam::aws:policy/AmazonS3FullAccess"

custom_iam_policy: |  # Optional: Custom IAM policy JSON
  {
    "Version": "2012-10-17",
    "Statement": [...]
  }
```

**Default IAM Permissions** (if not specified):
- AmazonECSTaskExecutionRolePolicy
- AmazonSQSFullAccess
- AmazonS3FullAccess

### Complete Fargate Examples

**Basic Internal Service:**
```yaml
platform: "fargate"
app_name: "my-api"
aws:
  profile: "personal"
  region: "us-east-2"
task:
  cpu: 1024
  memory: 2048
  ephemeral_storage: 50
  replicas: 1
  spot: true
environment:
  NODE_ENV: "production"
allow_create: true
```

**Production Public Web App:**
```yaml
platform: "fargate"
app_name: "my-webapp"
aws:
  profile: "personal"
  region: "us-east-2"
task:
  cpu: 1024
  memory: 2048
  ephemeral_storage: 50
  replicas: 2
  port: 8080
public:
  domain: "app.example.com"
  mode: "production"
environment:
  NODE_ENV: "production"
allow_create: true
```

**Lightweight Public Web App:**
```yaml
platform: "fargate"
app_name: "my-test-app"
aws:
  profile: "personal"
  region: "us-east-2"
task:
  cpu: 512
  memory: 1024
  ephemeral_storage: 21
  replicas: 1  # Must be 1 for lightweight mode
public:
  domain: "test.example.com"
  mode: "lightweight"
allow_create: true
```

## Platform: "fly" (Fly.io)

Deploy containerized applications to Fly.io.

### Required Configuration

```yaml
platform: "fly"
app_name: "my-app"
```

### Optional Configuration

```yaml
platform: "fly"
app_name: "my-app"
dockerfile: "Dockerfile"  # Optional: Path to Dockerfile (default: "Dockerfile")
task:
  replicas: 1  # Optional: Number of replicas (default: 1)
environment:
  NODE_ENV: "production"
```

### Important Notes

- **Fly.io does NOT support public domain configuration**
- If `public.domain` is specified, deployment will fail with an error
- Use "fargate" or "s3" platforms for public-facing applications

### Complete Fly.io Example

```yaml
platform: "fly"
app_name: "my-api"
dockerfile: "Dockerfile"
task:
  replicas: 2
environment:
  NODE_ENV: "production"
  API_KEY: "secret-key"
```

## Platform: "vercel" (Vercel)

Deploy serverless applications and edge functions to Vercel.

### Required Configuration

```yaml
platform: "vercel"
app_name: "my-app"
```

### Optional Configuration

```yaml
platform: "vercel"
app_name: "my-app"
vercel:
  project_name: "my-app"  # Optional: Vercel project name (default: app_name)
  team: "my-team"         # Optional: Vercel team name
  scope: "my-scope"       # Optional: Vercel scope
  prod: true              # Optional: Deploy to production (default: true)
  yes: false              # Optional: Skip confirmation prompts (default: false)
environment:
  NODE_ENV: "production"
public:
  domain: "app.example.com"  # Optional: Custom domain
```

### Complete Vercel Example

```yaml
platform: "vercel"
app_name: "my-serverless-app"
vercel:
  project_name: "my-serverless-app"
  prod: true
  yes: false
environment:
  NODE_ENV: "production"
  API_KEY: "secret"
```

### Important Notes

- Vercel deployment is currently disabled in the main entry point (needs testing)
- Use platform-specific module directly if needed: `python3 ./node_modules/deploy/vercel/main.py`

## Platform: "s3" (AWS S3 Static Website)

Deploy static websites to AWS S3 with CloudFront distribution and Route53 DNS.

### Required Configuration

```yaml
platform: "s3"
app_name: "my-static-site"
aws:
  region: "us-east-2"  # Required: AWS region
s3:
  folder: "./dist"     # Required: Path to folder containing static files
```

### Optional AWS Configuration

```yaml
aws:
  profile: "personal"  # Optional: AWS profile name (default: "personal")
  region: "us-east-2"  # Required: AWS region
```

### Optional S3 Configuration

```yaml
s3:
  folder: "./dist"                    # Required: Path to folder (relative to config file or absolute)
  bucket_name: "my-custom-bucket"     # Optional: Custom bucket name (default: auto-generated)
```

### Optional Public Configuration

```yaml
public:
  domain: "app.example.com"           # Required if public: Domain name
  certificate_id: "arn:..."           # Optional: Pre-existing ACM certificate ARN
```

### Important Requirements

- The specified folder **must contain an `index.html` file**
- Folder path can be relative (to config file directory) or absolute
- If folder doesn't exist or is not a directory, deployment will fail

### Complete S3 Examples

**Basic Static Site:**
```yaml
platform: "s3"
app_name: "my-static-site"
aws:
  profile: "personal"
  region: "us-east-2"
s3:
  folder: "./dist"
allow_create: true
```

**Public Static Site with Custom Domain:**
```yaml
platform: "s3"
app_name: "my-static-site"
aws:
  profile: "personal"
  region: "us-east-2"
s3:
  folder: "./build"
  bucket_name: "my-custom-bucket-name"
public:
  domain: "app.example.com"
allow_create: true
```

**Public Static Site with Custom Certificate:**
```yaml
platform: "s3"
app_name: "my-static-site"
aws:
  profile: "personal"
  region: "us-east-2"
s3:
  folder: "./dist"
public:
  domain: "app.example.com"
  certificate_id: "arn:aws:acm:us-east-1:123456789012:certificate/12345678-1234-1234-1234-123456789012"
allow_create: true
```

## Validation Rules

### Fargate Validation
- `platform` must be "fargate"
- `app_name` is required
- `aws.region` is required
- `task.cpu` is required
- `task.memory` is required
- `task.ephemeral_storage` is required
- If `public.mode` is "lightweight", `task.replicas` must be 1
- If `public` section exists, `public.domain` is required
- `public.mode` must be "lightweight" or "production" if specified

### Fly.io Validation
- `platform` must be "fly"
- `app_name` is required
- `public.domain` is NOT allowed (will cause error)

### Vercel Validation
- `platform` must be "vercel"
- `app_name` is required

### S3 Validation
- `platform` must be "s3"
- `app_name` is required
- `aws.region` is required
- `s3.folder` is required
- Folder must exist and be a directory
- Folder must contain `index.html`
- If `public` section exists, `public.domain` is required

## Best Practices

1. **Always specify `allow_create: true`** when deploying for the first time or when you want to create new resources
2. **Use `environment` section** for environment variables instead of hardcoding them
3. **For production**, use `mode: "production"` for Fargate public apps (not "lightweight")
4. **For S3**, ensure your folder contains `index.html` before deployment
5. **For Fargate**, choose appropriate CPU/memory based on your workload:
   - Small: 256 CPU, 512 MB memory
   - Medium: 1024 CPU, 2048 MB memory
   - Large: 2048 CPU, 4096 MB memory
6. **Use Fargate Spot** (`spot: true`) for cost savings on non-critical workloads
7. **Specify `ephemeral_storage`** appropriately - default is 20GB, but you can specify up to 200GB

## Common Mistakes to Avoid

1. ❌ Setting `platform: "fly"` with `public.domain` (not supported)
2. ❌ Setting `public.mode: "lightweight"` with `replicas > 1` (must be 1)
3. ❌ Missing `index.html` in S3 folder
4. ❌ Using relative paths for S3 folder without understanding they're relative to config file
5. ❌ Forgetting `allow_create: true` when deploying new infrastructure
6. ❌ Not specifying required fields (cpu, memory, ephemeral_storage for Fargate)
7. ❌ Using invalid CPU/memory combinations (must be valid Fargate combinations)

## Architecture Notes

### Fargate Production Mode
- Route53 → CloudFront → ALB → ECS Fargate Tasks
- Stable IPs, CDN caching, load balancing

### Fargate Lightweight Mode
- Route53 → ECS Fargate Task (direct)
- Ephemeral IPs, no load balancer, no CDN

### S3 Static Site
- Route53 → CloudFront (10 min cache) → S3 Bucket
- Automatic SSL certificate management via ACM

EOF
