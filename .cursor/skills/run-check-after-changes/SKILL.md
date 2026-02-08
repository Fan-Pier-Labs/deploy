---
name: run-check-after-changes
description: Runs make check (unit tests and mock boto3 deploy) after completing code or config changes. Use when finishing edits to deploy code, s3/aws modules, deploy configs, or when the user asks to run checks so the agent validates before considering the task done.
---

# Run make check after changes

## When to apply

After you have finished making code or configuration changes in this repo (including `s3/`, `aws/`, `test_site/`, config files, or the Makefile), run the project check before considering the task complete.

## Instructions

1. From the **repo root**, run:
   ```bash
   make check
   ```
2. `make check` runs in order: **unit tests** (`pytest`) then **mock deploy** (`run_deploy_mock.py` with mock boto3).
3. If either step fails:
   - Fix the failing tests or deploy logic.
   - Run `make check` again until it passes.
4. Only treat the task as done when `make check` succeeds.

## Notes

- Do not skip this step when the user asked for changes that affect deploy logic, tests, or config.
- If the user explicitly says they do not want to run checks, skip it.
