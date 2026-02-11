# Bug report: `custom_iam_policy` not applied to ECS task execution role

**Repo:** https://github.com/fan-Pier-Labs/deploy  
**Config:** `deploy.yaml` with `platform: "fargate"`, `secrets`, and `custom_iam_policy`

---

## Summary

When deploying an ECS Fargate service that uses `secrets` and `custom_iam_policy`, the policy is not applied to the IAM role that the running task uses to call AWS APIs. The task fails at runtime with `AccessDeniedException` when the container calls Secrets Manager (e.g. `GetSecretValue`).

---

## Environment

- **Deploy tool:** `python3 ./node_modules/deploy/main.py --config deploy.yaml`
- **Platform:** Fargate (`platform: "fargate"`)
- **Region:** us-east-2
- **App:** ECS service that at runtime calls AWS Secrets Manager from application code (not only via ECS secret injection).

---

## Steps to reproduce

1. Create a `deploy.yaml` with:
   - `platform: "fargate"`
   - `secrets:` listing one or more Secrets Manager ARNs
   - `custom_iam_policy:` with a Statement allowing `secretsmanager:GetSecretValue` on those ARNs

2. Deploy: `python3 ./node_modules/deploy/main.py --config deploy.yaml`

3. Ensure the ECS task definition uses the account’s **ecsTaskExecutionRole** (or a shared execution role) as the execution role — i.e. the deploy tool does not create/use a dedicated execution role for this app.

4. Run the service so a task starts. Application code at startup calls `SecretsManagerClient.get_secret_value()` (or equivalent) for the same secrets.

5. Check the task’s CloudWatch log stream.

---

## Expected behavior

- The `custom_iam_policy` from `deploy.yaml` is attached to the **same IAM role that the ECS task uses** when making AWS API calls (e.g. Secrets Manager) at runtime.
- The task can successfully call `GetSecretValue` on the secrets listed in `secrets` and referenced in `custom_iam_policy`.

---

## Actual behavior

- The task fails on startup with an error like:

  ```
  User: arn:aws:sts::ACCOUNT:assumed-role/ecsTaskExecutionRole/TASK_ID is not authorized to perform: secretsmanager:GetSecretValue on resource: arn:aws:secretsmanager:us-east-2:ACCOUNT:secret:SECRET_NAME because no identity-based policy allows the secretsmanager:GetSecretValue action
  ```

- The role named in the error (`ecsTaskExecutionRole`) has **no** inline or attached policy granting `secretsmanager:GetSecretValue` on the configured secrets.
- The `custom_iam_policy` defined in `deploy.yaml` is either:
  - Applied to a different role (e.g. one the deploy tool creates) that is not used by the task definition, or
  - Not applied to any role at all.

---

## Root cause (hypothesis)

- The deploy tool may create a new execution role and attach `custom_iam_policy` to it, but the registered ECS task definition still references an existing role (e.g. `ecsTaskExecutionRole`).
- Or the tool only uses `custom_iam_policy` when it creates the execution role; when the task definition is configured to use a pre-existing execution role (by name or ARN), the tool does not attach the custom policy to that existing role.

In both cases, the role that actually runs the task (and is used for SDK calls from the container) never receives the custom policy.

---

## Impact

- Services that need runtime access to Secrets Manager (or other resources covered by `custom_iam_policy`) fail immediately after start.
- Workaround: manually attach an equivalent policy to the execution role the task uses (e.g. `ecsTaskExecutionRole`), which is error-prone and not reflected in `deploy.yaml`.

---

## Suggested fix

1. **If the task definition uses a role created by the deploy tool:**  
   Ensure the task definition’s `executionRoleArn` is set to that role’s ARN and that `custom_iam_policy` is attached to that role.

2. **If the task definition uses a pre-existing execution role (e.g. by name):**  
   When `custom_iam_policy` is present, attach it (or merge it) to that existing role (e.g. by putting an inline policy on the role or attaching a generated policy), so the role used at runtime has the required permissions.

3. **Documentation:**  
   Clarify in the deploy tool’s docs whether `custom_iam_policy` is applied only to a deployer-created role or also to an existing execution role, and how to ensure the running task’s role has the needed permissions.

---

## Example `deploy.yaml` (minimal)

```yaml
platform: "fargate"
app_name: "my-app"
aws:
  profile: "my-profile"
  region: "us-east-2"

task:
  cpu: 1024
  memory: 2048
  port: 8080

secrets:
  - arn:aws:secretsmanager:us-east-2:ACCOUNT:secret:MY_SECRET-xxxxx

custom_iam_policy:
  Version: "2012-10-17"
  Statement:
    - Effect: Allow
      Action: secretsmanager:GetSecretValue
      Resource: arn:aws:secretsmanager:us-east-2:ACCOUNT:secret:MY_SECRET-xxxxx
```

When the app calls Secrets Manager at runtime using the task’s execution role, the above results in `AccessDeniedException` until the same policy is manually added to that execution role.

