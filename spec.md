# Deploy tool – specification

## Overview

Single-command deploy to AWS: read a user YAML config, generate a CloudFormation template, deploy the stack via the AWS CLI. Supports **S3** (static site + optional CloudFront + Route53) and **Fargate** (ECS + ALB + CloudFront + Route53). No local stack file is written unless the user passes `--debug-save-stack-locally`.

## Platforms

- **s3** – Static website in S3. Optional public domain: CloudFront + Route53. Requires `s3.folder`; if `public.domain` is set, certificate and hosted zone are resolved (see below).
- **fargate** – ECS Fargate service. Optional public domain: ALB + CloudFront + Route53. No lightweight mode (no direct-to-task IP + Route53).

Lightweight mode (domain → Fargate task IP) is **not** supported; public domain always uses CloudFront (+ ALB for Fargate).

## Default deploy flow (one command)

1. **Load config** – Read user YAML (`deploy.yaml` or `--config FILE`). Validate `platform` (s3 | fargate) and required fields.
2. **Resolve certificate (if public domain)** – deploy.yaml only has `public.domain`; we do **not** put cert id in config. **Python (boto3), outside CloudFormation:** In ACM **us-east-1** (CloudFront requirement), **find** an existing certificate: exact match for the domain, or wildcard match (e.g. `*.example.com` covers `app.example.com`). If none found and `allow_create: true`: **request** a new ACM certificate (for subdomains, request wildcard `*.parent`), **create** Route53 validation records (CNAME) in the domain’s hosted zone, **wait** for validation (up to ~30 minutes). Return the certificate ARN to use in the stack. (Optional override: if user sets `public.certificate_id` or `public.certificate_arn`, use that instead.)
3. **Resolve hosted zone (if public domain)** – deploy.yaml does not include hosted zone. Resolve Route53 hosted zone ID from the domain (e.g. `app.example.com` → zone for `example.com`) via AWS CLI (or boto3). (Optional override: if user sets `public.hosted_zone_id`, use that.)
4. **Generate CloudFormation** – From config, build the template (S3 or Fargate). Template is kept in memory (and optionally written to a temp file for `aws cloudformation deploy`). **Do not** write the stack to the current directory unless `--debug-save-stack-locally` is set.
5. **Deploy stack** – Run `aws cloudformation deploy` with the generated template and parameters (cert ARN, hosted zone ID, and for Fargate: ImageUri, VpcId, SubnetIds). Use a temp file for the template; delete it after deploy.
6. **Post-deploy**  
   - **S3:** `aws s3 sync` from `s3.folder` to the stack’s bucket; if the template has a CloudFront distribution, create a cache invalidation `/*`.  
   - **Fargate:** Before step 5, ensure ECR repo exists, build and push Docker image, pass `ImageUri` into the stack. After step 5, if the template has CloudFront, create a cache invalidation `/*`.

**Debug:** If the user passes `--debug-save-stack-locally` [FILE], save the generated CloudFormation to FILE (default `stack-debug.yaml`) in the current directory **and** still run the deploy. This is the only way the stack YAML is written to disk during a normal deploy.

## Certificate resolution (Python, outside CloudFormation)

- **Scope:** When `public.domain` is set. deploy.yaml does not contain cert id; we resolve it automatically.
- **Region:** ACM is used in **us-east-1** (required for CloudFront).
- **Find existing cert:**  
  - List ACM certificates in us-east-1.  
  - For each cert (status ISSUED or PENDING_VALIDATION):  
    - **Exact match:** `public.domain` equals the cert’s `DomainName` or is in `SubjectAlternativeNames`.  
    - **Wildcard match:** Any of the cert’s names is `*.suffix` and `public.domain` is equal to `suffix` or ends with `.{suffix}` (e.g. `*.example.com` covers `app.example.com`).  
  - Return the first matching cert ARN.
- **Request + validate (if not found and `allow_create: true`):**  
  - **Subdomain (e.g. `app.example.com`):** Request ACM cert for `*.example.com` (wildcard) in us-east-1 with DNS validation.  
  - **Apex (e.g. `example.com`):** Request ACM cert for `example.com` with DNS validation.  
  - Get validation CNAME name/value from ACM `DescribeCertificate`.  
  - Find the Route53 hosted zone for the cert domain (e.g. `example.com`). Create (or update) a CNAME record for the validation name with the validation value.  
  - Poll ACM until certificate status is ISSUED (or timeout ~30 minutes).  
  - Return the new cert ARN.
- **Wildcard preference:** When **finding**, wildcard certs are used when they cover the domain. When **requesting** for a subdomain, a wildcard is requested so one cert covers that subdomain and others.

## Config (YAML) – deploy.yaml

**deploy.yaml is unchanged by CloudFormation:** you only specify the domain you want to deploy to. No `hosted_zone_id`, `certificate_id`, or `mode` in the config.

- **Required:** `platform` (s3 | fargate), `app_name`, `aws.region`.  
- **S3:** `s3.folder` (path to static files; must contain `index.html`). Optional `s3.bucket_name`.  
- **Fargate:** `task` (cpu, memory, replicas, spot, port, ephemeral_storage, dockerfile). Optional `environment`.  
- **Public domain (optional):**  
  - `public.domain` – Domain name. That is all you set; hosted zone and certificate are resolved automatically (see Certificate resolution).  
- **Flags:** `allow_create` – If true, allows creating resources (e.g. new ACM cert, validation records). Default false; set true for automatic cert.

Optional overrides (not in deploy.yaml by default): `public.hosted_zone_id`, `public.certificate_arn` / `public.certificate_id` – only if you need to pin a specific zone or cert.

## CLI

- **Deploy (default):**  
  `python3 main.py [--config FILE]`  
  Generates stack, deploys, no local stack file (unless `--debug-save-stack-locally`).

- **Debug – save stack locally:**  
  `python3 main.py --debug-save-stack-locally [FILE]`  
  Saves generated template to FILE (default `stack-debug.yaml`) and still deploys.

- **Generate only (no deploy):**  
  `python3 main.py --no-deploy` → print template to stdout.  
  `python3 main.py -o stack.yaml` → write template to `stack.yaml` and exit (no deploy).

- **Stack name:** `--stack-name NAME` (default `{app_name}-stack`).

## What runs where

- **CloudFormation (AWS):** S3 bucket, bucket policy, CloudFront distribution, Route53 A (alias) record; or ECS cluster/service/task def, IAM roles, log group, security groups, ALB, target group, listener, CloudFront, Route53. All long-lived infra is in the stack.
- **Python (boto3):** Certificate resolution only: find existing ACM cert (exact/wildcard) in us-east-1, or request cert + create Route53 validation records + wait for validation. No other resource creation in Python.
- **AWS CLI:** CloudFormation deploy, S3 sync, CloudFront invalidation; Fargate also uses CLI (or subprocess) for ECR login, and Docker for build/push.
- **Docker:** Fargate image build and push to ECR before stack deploy.

## Teardown

Delete the CloudFormation stack (e.g. `aws cloudformation delete-stack --stack-name <name>`). All stack resources (S3, CloudFront, Route53, ECS, ALB, etc.) are removed. ACM certificates are not deleted by the stack; they remain unless deleted manually.

## Summary

| Item | Behavior |
|------|----------|
| Deploy command | One command: generate stack → deploy. No local stack file by default. |
| Local stack file | Only when `--debug-save-stack-locally` [FILE] is set. |
| Lightweight mode | Dropped. Public domain always uses CloudFront (+ ALB for Fargate). |
| deploy.yaml public | Only `public.domain`. No hosted_zone_id, certificate_id, or mode. |
| Certificate | Resolved automatically: Python finds existing (exact/wildcard) or requests + validates via Route53. |
| Wildcard certs | Used when they cover the domain; for new certs on subdomains, wildcard is requested. |
