---
name: Patch aws package level
overview: The current code patches at the consumer level (aws.deploy.vpc, aws.deploy.ecs, ...) because deploy and destroy are imported before the patch block, so their view of vpc/ecs is already fixed. You can do a single "patch aws" by patching package-level attributes (aws.vpc, aws.iam, ...) and importing deploy/destroy inside the with block so they resolve to the mocks. Only the submodules used by deploy/destroy need to be implemented as mocks.
todos: []
isProject: false
---

# Patch at `aws` package level and implement only needed submodules

## Why the current code doesn’t do `patch("aws", ...)`

**Import order.** In [run_deploy_mock.py](run_deploy_mock.py), `run_fargate_mock` does:

```python
def run_fargate_mock(config_path):
    from aws.deploy import deploy_to_fargate   # aws.deploy loads here
    from aws.destroy import destroy_fargate_infra
    ...
    with fargate_aws_mock(...):
        deploy_to_fargate(...)
```

When `aws.deploy` is loaded, it runs `from . import vpc, iam, logs, ...` and binds those names in `aws.deploy`’s namespace (e.g. `aws.deploy.vpc = aws.vpc` at that moment). That happens **before** the `with` block. So when we later patch `aws.deploy.vpc`, we’re patching the **consumer** (the module that already captured a reference). If we instead only patched `aws.vpc` after deploy was loaded, `aws.deploy.vpc` would still point at the original module, so the current design deliberately patches where the names are used: `aws.deploy.vpc`, `aws.deploy.ecs`, etc.

Replacing the whole `aws` package with one object (e.g. `patch("aws", mock_aws)`) doesn’t work because:

- The code under test lives **inside** `aws` (`aws.deploy`, `aws.destroy`).
- Those modules have already imported `vpc`, `ecs`, etc. into their own namespaces; changing `aws` doesn’t change those bindings if the import already happened.

So the “hesitation” is: you can’t usefully replace `aws` in one shot after deploy/destroy are loaded; you have to either patch consumers (current approach) or patch the package **before** those consumers load.

## What we can do instead: patch `aws` and import inside the block

We **can** do a single logical “patch aws” by:

1. **Patching package-level attributes**
  Patch `aws.vpc`, `aws.iam`, `aws.logs`, `aws.events`, `aws.ecr`, `aws.ecs`, `aws.route53`, `aws.cloudfront`, `aws.alb`, `aws.acm` to mock objects (same mocks as today).
2. **Importing deploy/destroy inside the `with` block**
  So that when `aws.deploy` runs `from . import vpc, iam, ...`, it looks up `aws.vpc`, `aws.iam`, etc. **after** the patches are applied and gets the mocks. Same idea for `aws.destroy` and its `from . import route53, cloudfront`.
3. **Implementing only the submodules we need**
  Only those 10 submodules (vpc, iam, logs, events, ecr, ecs, route53, cloudfront, alb, acm) are replaced with mocks. The rest of the package stays real: `aws.config`, `aws.deploy`, `aws.destroy`, `aws.utils`, `aws.docker`, etc. If any code path used an aws submodule we didn’t mock, it would get the real module (or we could use a strict object that raises if an unexpected attribute is accessed).

So we’re not doing a single `patch("aws", one_big_object)`; we’re doing one **conceptual** “patch aws” by patching the package’s **attributes** (`aws.vpc`, …) and only implementing those. No need to mock `aws.config`, `aws.docker`, or the deploy/destroy modules themselves.

## Implementation sketch

**1. Keep `_make_mock_aws_modules**`  
Still build the same mock objects for vpc, iam, logs, events, ecr, ecs, route53, cloudfront, alb, acm (and the minimal boto3 session).

**2. Change `fargate_aws_mock` to patch package-level `aws.***`

- Patch `aws.vpc`, `aws.iam`, `aws.logs`, `aws.events`, `aws.ecr`, `aws.ecs`, `aws.route53`, `aws.cloudfront`, `aws.alb`, `aws.acm` (and keep `boto3.Session`, `time.sleep`, and `aws.deploy.test_deployment_http_requests` as today).
- **Remove** patches on `aws.deploy.vpc`, `aws.deploy.iam`, … and `aws.destroy.route53`, `aws.destroy.cloudfront`, because they won’t be needed once deploy/destroy are loaded under the patched `aws`.

**3. Import deploy/destroy inside the `with` block**

- In `run_fargate_mock`, **do not** import `deploy_to_fargate` or `destroy_fargate_infra` at the top of the function.
- Enter `with fargate_aws_mock(...):`, then inside the block run something like:
  - `from aws.config import load_config` (can stay outside if config doesn’t use the mocked submodules),
  - `from aws.deploy import deploy_to_fargate`
  - `from aws.destroy import destroy_fargate_infra`
  then run the three phases as now.

So the only behavioral change is: apply patches to `aws.<submodule>`, then import the code that uses those submodules so it sees the mocks. We still only implement the 10 submodules we need; nothing else in `aws` is mocked.

## Optional: strict “only these submodules” behavior

If you want “if something isn’t mocked, error”, we could replace the real `aws` package with a thin wrapper that:

- Exposes the 10 mocked submodules and leaves `config`, `deploy`, `destroy`, etc. as the real modules (so we’d copy or proxy the real `aws.__dict__` and override only vpc, iam, …).
- Or we keep the current “patch individual attributes” approach and don’t replace `aws` itself; then any use of an aws submodule we didn’t patch (e.g. `aws.docker`) would still be the real module. To get “error if unmocked” we’d need a custom object for `aws` that raises on attribute access for anything we didn’t allow, which is more invasive.

Recommendation: do the minimal change (patch `aws.vpc`, … and import inside the block); that gives you “patch aws” and “implement just some of the aws classes” without extra complexity.