#!/usr/bin/env python3
"""
Docker utilities for building and pushing images.
"""
import subprocess
import sys
import time


def ensure_docker_running():
    """
    Check if Docker daemon is running, and start Docker Desktop if it's not.
    """
    try:
        # Check if Docker daemon is responding
        result = subprocess.run(
            ['docker', 'info'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            print("Docker daemon is running")
            return True
        else:
            print("Docker daemon is not responding, attempting to start Docker Desktop...")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("Docker is not available, attempting to start Docker Desktop...")
    
    # Try to start Docker Desktop (macOS)
    try:
        subprocess.run(
            ['open', '-a', 'Docker'],
            check=True,
            capture_output=True
        )
        print("Docker Desktop is starting, waiting for daemon to be ready... (if it hangs here, kill the script, open docker desktop, and try again)")
        
        # Wait for Docker daemon to be ready (up to 60 seconds)
        for i in range(60):
            time.sleep(2)
            try:
                result = subprocess.run(
                    ['docker', 'info'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    print("Docker daemon is now running")
                    return True
            except subprocess.TimeoutExpired:
                continue
        
        print("Error: Docker daemon did not start within 60 seconds")
        print("Please start Docker Desktop manually and try again.")
        sys.exit(1)
        
    except subprocess.CalledProcessError:
        print("Error: Could not start Docker Desktop")
        print("Please start Docker Desktop manually and try again.")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: Docker Desktop is not installed or 'open' command is not available")
        print("Please install Docker Desktop or start it manually.")
        sys.exit(1)
