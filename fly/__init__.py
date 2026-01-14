"""
Fly.io deployment package.
"""
from .main import main
from .deploy import deploy_to_fly

__all__ = ['main', 'deploy_to_fly']
