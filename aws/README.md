# AWS Fargate Deployment Package

This package provides modular deployment tools for AWS Fargate, supporting both internal deployments and public-facing web applications.

## Structure

- `vpc.py` - VPC, subnet, and security group management
- `iam.py` - IAM role management for ECS tasks
- `logs.py` - CloudWatch Logs setup
- `events.py` - EventBridge event capture for ECS
- `docker.py` - Docker utilities
- `utils.py` - General utility functions
- `config.py` - Configuration loading and validation
- `ecr.py` - ECR repository management
- `ecs.py` - ECS cluster, service, and task definition management
- `route53.py` - Route53 domain and DNS record management
- `cloudfront.py` - CloudFront distribution management
- `alb.py` - Application Load Balancer management
- `deploy.py` - Main deployment orchestrator
- `main.py` - CLI entry point

## Usage

### Basic Deployment (Internal)

```yaml
# fargate.config.yaml
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

```bash
python deploy_to_fargate.py --config fargate.config.yaml
```

### Lightweight Public App

For testing/internal sites where domain points directly to Fargate:

```yaml
# fargate.config.yaml
app_name: "my-app"
public:
  domain: "test.example.com"
  mode: "lightweight"
# ... rest of config
```

**Note:** Lightweight mode points directly to Fargate task IPs, which are ephemeral. DNS records may need updating on each deployment. For production, use `production` mode.

### Production Public App

For production sites with CloudFront and ALB:

```yaml
# fargate.config.yaml
app_name: "my-app"
public:
  domain: "app.example.com"
  mode: "production"
task:
  port: 8080  # Port your container listens on
# ... rest of config
```

**Architecture:**
- Route53 → CloudFront (no caching, forwards all headers) → ALB → Fargate

## Configuration Options

### Public App Configuration

- `domain`: The domain or subdomain to host the app on (e.g., `app.example.com` or `example.com`)
- `mode`: Either `lightweight` or `production`

### Task Configuration

- `cpu`: CPU units (256 = 0.25 vCPU, 1024 = 1 vCPU, etc.)
- `memory`: Memory in MB
- `spot`: Use Fargate Spot (true) or On-Demand (false)
- `replicas`: Number of task replicas
- `ephemeral_storage`: Storage in GB (20-200)
- `port`: Container port (default: 80)

## Route53 Requirements

- The domain must be managed by Route53 in the same AWS account
- The script will only modify CNAME, A, or AAAA records for the specified domain/subdomain
- It will find the appropriate hosted zone automatically

## CloudFront Configuration

Production mode creates a CloudFront distribution with:
- No caching (TTL = 0)
- All headers forwarded
- HTTPS redirect
- All HTTP methods allowed
