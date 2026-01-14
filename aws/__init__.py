#!/usr/bin/env python3
"""
AWS Fargate deployment package.
"""
from .deploy import deploy_to_fargate
from .config import load_config

__all__ = ['deploy_to_fargate', 'load_config']
