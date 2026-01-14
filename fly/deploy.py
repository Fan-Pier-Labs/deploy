#!/usr/bin/env python3
"""
Fly.io deployment orchestrator.
"""
import subprocess
import sys
import os


def deploy_to_fly(config_dict=None, **kwargs):
    """
    Deploy the application to Fly.io.
    
    If config_dict is provided, it will be used. Otherwise, kwargs will be used.
    """
    # Merge config_dict and kwargs
    if config_dict:
        params = {**config_dict, **kwargs}
    else:
        params = kwargs
    
    # Extract parameters
    app_name = params.get('app_name')
    dockerfile = params.get('dockerfile', 'Dockerfile')
    replicas = params.get('replicas', 1)
    environment = params.get('environment', {})
    
    print("Starting deployment to Fly.io...")
    
    # Validate required parameters
    if app_name is None:
        print("Error: 'app_name' parameter is required")
        sys.exit(1)
    
    # Get the backend directory (where fly.toml should be)
    # The deploy script is typically run from the backend directory
    current_dir = os.getcwd()
    
    # Try current directory first (most common case)
    if os.path.exists(os.path.join(current_dir, 'fly.toml')):
        backend_dir = current_dir
    else:
        # Try backend directory relative to deploy script
        deploy_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        backend_dir = os.path.join(os.path.dirname(deploy_dir), 'backend')
        
        if not os.path.exists(os.path.join(backend_dir, 'fly.toml')):
            print(f"Error: fly.toml not found")
            print(f"Tried: {os.path.join(current_dir, 'fly.toml')}")
            print(f"Tried: {os.path.join(backend_dir, 'fly.toml')}")
            print("Please ensure fly.toml exists in the backend directory")
            sys.exit(1)
    
    fly_toml_path = os.path.join(backend_dir, 'fly.toml')
    
    try:
        # Step 1: Deploy to Fly.io
        print(f"Deploying to Fly.io app: {app_name}")
        print(f"Using Dockerfile: {dockerfile}")
        
        # Change to backend directory for fly deploy
        original_dir = os.getcwd()
        os.chdir(backend_dir)
        
        try:
            # Run fly deploy
            deploy_cmd = ['fly', 'deploy', '--remote-only']
            print(f"Running: {' '.join(deploy_cmd)}")
            result = subprocess.run(deploy_cmd, check=True, capture_output=False)
            
            # Step 2: Set the machine count (required because fly.toml min_machines_running doesn't work correctly)
            print(f"\nSetting machine count to {replicas}...")
            count_cmd = ['fly', 'scale', 'count', str(replicas)]
            print(f"Running: {' '.join(count_cmd)}")
            result = subprocess.run(count_cmd, check=True, capture_output=False)
            
            print("\nDeployment to Fly.io completed successfully!")
            print(f"App: {app_name}")
            print(f"Replicas: {replicas}")
            
        finally:
            os.chdir(original_dir)
            
    except subprocess.CalledProcessError as e:
        print(f"\nError during Fly.io deployment: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("\nError: fly command not found")
        print("Please install Fly.io CLI: https://fly.io/docs/hands-on/install-flyctl/")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error during deployment: {str(e)}")
        sys.exit(1)
