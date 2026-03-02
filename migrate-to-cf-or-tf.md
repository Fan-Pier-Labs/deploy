# Migrate Infrastructure from boto3 to CloudFormation/Terraform

## Overview

Replace imperative boto3 resource management with declarative CloudFormation (or Terraform) templates, while keeping boto3 for operational tasks that CF/TF can't handle (build, push, invalidate, verify).

## The Standard Pattern

The industry-standard workflow for deploying containers with CF/TF:

1. **CF/TF defines the infrastructure shell** — all resources, wired together with references
2. **A script handles deploy-time actions** — build, push, force-redeploy, invalidate, verify

You never re-run CF/TF on every deploy. You run it once (or when infra changes), then your deploy script just pushes a new image and triggers a rollout.

---

## What CF/TF Replaces (Infrastructure)

These files/features are fully replaced by a CF stack or TF config:

| File | Lines | What CF/TF Handles |
|---|---|---|
| `aws/vpc.py` | 160 | SG creation + rules (VPC/subnet discovery becomes a parameter or data source) |
| `aws/iam.py` | 123 | Execution role, policy attachments, trust relationships |
| `aws/events.py` | 152 | EventBridge rules + CloudWatch log targets |
| `aws/ecs.py` | 239 | Cluster, task definition, service, capacity providers |
| `aws/alb.py` | 311 | ALB, target group, listener, health check config |
| `aws/cloudfront.py` | 291 | Distribution with all origin/behavior/SSL config |
| `aws/route53.py` | 484 | A/ALIAS records (record creation, not dig verification) |
| `aws/acm.py` | 212 | Certificate + DNS validation records |
| `aws/logs.py` (partial) | ~30 | Log group creation |
| `aws/destroy.py` | 342 | Replaced by `aws cloudformation delete-stack` or `terraform destroy` |
| `s3/s3_bucket.py` (partial) | ~150 | Bucket, website config, block public access, bucket policy |
| `s3/cloudfront_s3.py` | 184 | S3-origin CloudFront distribution |
| `s3/destroy.py` | 207 | Replaced by stack delete |
| **Total** | **~2,885** | |

This becomes a single CloudFormation template per deployment type — one for Fargate, one for S3.

---

## What Stays as boto3/Scripts (Operational)

These features cannot be done with CF/TF and remain as Python code:

| Feature | Current File(s) | Lines | Why CF/TF Can't Do It |
|---|---|---|---|
| Docker build (Buildx + cache) | `aws/docker.py` | 106 | Build step, not infrastructure |
| ECR auth + Docker push | `aws/ecr.py` | ~95 | Build step, not infrastructure |
| S3 file upload (dir traversal + MD5) | `s3/s3_bucket.py` | ~150 | CF/TF don't upload file contents |
| CloudFront invalidation | `aws/cloudfront.py` | ~30 | Post-deploy action, not a resource |
| ECS force new deployment | `aws/ecs.py` | ~10 | Imperative trigger after image push |
| DNS delegation verification (dig) | `aws/route53.py` | ~100 | Pre-flight check against public DNS |
| ALB target health polling | `aws/alb.py` | ~40 | Runtime verification |
| HTTP endpoint testing | `aws/utils.py` | 100 | Runtime verification |
| CloudWatch log tailing | `aws/logs.py` | ~60 | Runtime operations |
| **Total** | **~690** | |

---

## New Deploy Flows

### Fargate

```
1. Load YAML config                          # config.py (kept)
2. Ensure CF stack exists                    # boto3: cloudformation.create/update_stack()
   - ECR, ECS cluster, task def, service,
     ALB, CloudFront, Route53, ACM, IAM,
     SGs, log group, EventBridge
3. Verify DNS delegation                     # boto3/subprocess: dig (kept)
4. Docker build with Buildx                  # subprocess (kept)
5. ECR auth + push                           # boto3 ecr.get_authorization_token (kept)
6. Force new ECS deployment                  # boto3 ecs.update_service (kept)
7. Wait for ALB targets healthy              # boto3 elbv2.describe_target_health (kept)
8. Invalidate CloudFront                     # boto3 cloudfront.create_invalidation (kept)
9. HTTP verification                         # requests library (kept)
10. Tail logs                                # boto3 logs.get_log_events (kept)
```

### S3

```
1. Load YAML config                          # config.py (kept)
2. Ensure CF stack exists                    # boto3: cloudformation.create/update_stack()
   - S3 bucket, CloudFront, Route53, ACM,
     bucket policy
3. Upload files to S3                        # boto3 s3.put_object (kept)
4. Invalidate CloudFront                     # boto3 cloudfront.create_invalidation (kept)
5. HTTP verification                         # requests library (kept)
```

### Destroy

```
1. aws cloudformation delete-stack           # one command, replaces 549 lines
```

---

## Expected Impact

| | Before (boto3 only) | After (CF + boto3 hybrid) |
|---|---|---|
| Infrastructure code | ~2,885 lines of boto3 | ~200-300 lines of CF template per stack |
| Operational code | ~690 lines | ~690 lines (unchanged) |
| Orchestration code | ~1,241 lines | ~300-400 lines (much simpler) |
| Destroy code | 549 lines | 1 API call |
| **Total AWS code** | ~5,365 lines | ~1,900-2,000 lines |

**~65% reduction in code.**

### Key Wins

- **Destroy becomes trivial** — stack deletion handles ordering automatically
- **Idempotency is free** — CF handles create-or-update natively
- **Dependency wiring is declarative** — no more manual "create ALB, then get ARN, then pass to ECS service"
- **Drift detection** — CF tells you if someone changed infra manually
- **Orchestration simplifies** — deploy scripts shrink from "create everything" to "ensure stack exists, then build+push+trigger"

### What Stays Valuable

The boto3 that remains is genuinely operational — build, push, invalidate, verify, tail — stuff that runs every deploy and isn't about what resources exist.
