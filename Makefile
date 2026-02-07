# Deploy project Makefile
# Run from repo root.

PYTHON ?= python3
PIP ?= pip
CONFIG_S3 ?= test_site_s3/deploy.yaml
CONFIG_FARGATE ?= test_site_fargate/deploy.yaml

.PHONY: install test test-mock test-mock-fargate check build-fargate deploy deploy-fargate

# Install all dependencies with pip
install:
	$(PIP) install -r requirements-test.txt

# Run unit tests (pytest)
test: install
	$(PYTHON) -m pytest

# Run S3 deploy + destroy against mock boto3 (validates deploy/destroy flow)
test-mock: install
	$(PYTHON) run_deploy_mock.py $(CONFIG_S3)

# Run Fargate deploy + destroy against mock boto3 (no Docker build; validates flow)
test-mock-fargate: install
	$(PYTHON) run_deploy_mock.py $(CONFIG_FARGATE)

# Run both: unit tests, S3 mock deploy, and Fargate mock deploy
check: test test-mock test-mock-fargate

# Build Fargate test site Docker image locally, then mock deploy (full build, no push to AWS)
build-fargate: install
	docker build -t deploytest-fargate-site:local -f test_site_fargate/Dockerfile test_site_fargate/
	$(PYTHON) run_deploy_mock.py $(CONFIG_FARGATE)

# Deploy the S3 test site to AWS (real deployment)
deploy-s3: install
	$(PYTHON) main.py --config $(CONFIG_S3)

# Deploy the Fargate test site to AWS (real deployment; requires Docker)
deploy-fargate: install
	$(PYTHON) main.py --config $(CONFIG_FARGATE)
