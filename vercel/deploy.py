#!/usr/bin/env python3
"""
Vercel deployment orchestrator.
"""
import subprocess
import sys
import os


def deploy_to_vercel(config_dict=None, **kwargs):
    """
    Deploy the application to Vercel.
    
    If config_dict is provided, it will be used. Otherwise, kwargs will be used.
    """
    # Merge config_dict and kwargs
    if config_dict:
        params = {**config_dict, **kwargs}
    else:
        params = kwargs
    
    # Extract parameters
    app_name = params.get('app_name')
    environment = params.get('environment', {})
    public_config = params.get('public', {})
    vercel_config = params.get('vercel', {})
    
    print("Starting deployment to Vercel...")
    
    # Validate required parameters
    if app_name is None:
        print("Error: 'app_name' parameter is required")
        sys.exit(1)
    
    # Get the directory where the app is located
    # The deploy script is typically run from the app directory (e.g., frontend/)
    current_dir = os.getcwd()
    
    # Check if we're in a Next.js/React app directory
    # Look for package.json with Next.js or React
    package_json_path = os.path.join(current_dir, 'package.json')
    if not os.path.exists(package_json_path):
        print(f"Error: package.json not found in {current_dir}")
        print("Please run the deployment from your frontend/app directory")
        sys.exit(1)
    
    try:
        # Step 1: Set environment variables
        if environment:
            print(f"\nSetting environment variables...")
            env_vars = []
            for key, value in environment.items():
                env_var_cmd = ['vercel', 'env', 'add', key, 'production']
                env_vars.append((key, value, env_var_cmd))
            
            # Note: Vercel env add is interactive, so we'll use --yes flag if available
            # For now, we'll just deploy and let Vercel use .env files or existing env vars
            print("Note: Environment variables should be set via Vercel dashboard or .env files")
            print("      You can also use 'vercel env add' command manually")
        
        # Step 2: Link project (if not already linked)
        project_name = vercel_config.get('project_name', app_name)
        team = vercel_config.get('team')
        scope = vercel_config.get('scope')
        
        print(f"\nLinking to Vercel project: {project_name}")
        link_cmd = ['vercel', 'link', '--yes']
        if project_name:
            link_cmd.extend(['--project', project_name])
        if team:
            link_cmd.extend(['--scope', team])
        elif scope:
            link_cmd.extend(['--scope', scope])
        
        print(f"Running: {' '.join(link_cmd)}")
        try:
            result = subprocess.run(link_cmd, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                # If link fails, it might already be linked, which is fine
                if 'already linked' in result.stderr.lower() or 'already linked' in result.stdout.lower():
                    print("Project is already linked to Vercel")
                else:
                    print(f"Warning: Project linking had issues: {result.stderr}")
        except FileNotFoundError:
            print("\nError: vercel command not found")
            print("Please install Vercel CLI: npm i -g vercel")
            sys.exit(1)
        
        # Step 3: Deploy to Vercel
        print(f"\nDeploying to Vercel...")
        deploy_cmd = ['vercel', '--prod'] if vercel_config.get('prod', True) else ['vercel']
        
        if vercel_config.get('yes', False):
            deploy_cmd.append('--yes')
        
        # Add domain if specified in public config
        if public_config.get('domain'):
            deploy_cmd.extend(['--domain', public_config['domain']])
        
        print(f"Running: {' '.join(deploy_cmd)}")
        result = subprocess.run(deploy_cmd, check=True, capture_output=False)
        
        print("\nDeployment to Vercel completed successfully!")
        print(f"App: {app_name}")
        if public_config.get('domain'):
            print(f"Domain: {public_config['domain']}")
        
        # Step 4: Display deployment URL
        print("\nFetching deployment URL...")
        inspect_cmd = ['vercel', 'inspect', '--wait']
        try:
            result = subprocess.run(inspect_cmd, check=False, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print("Deployment details:")
                print(result.stdout)
        except (subprocess.TimeoutExpired, Exception) as e:
            print("Note: Run 'vercel inspect' to see deployment details")
        
    except subprocess.CalledProcessError as e:
        print(f"\nError during Vercel deployment: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("\nError: vercel command not found")
        print("Please install Vercel CLI: npm i -g vercel")
        print("Or use: npm install -g vercel")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error during deployment: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
