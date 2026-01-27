#!/usr/bin/env python3
"""
Utility functions for deployment scripts.
"""
import subprocess
import sys
import re


def run_command(command, error_message, stream_output=False):
    """
    Run a shell command and exit if it fails.
    
    Args:
        command: The shell command to run
        error_message: Error message to display if command fails
        stream_output: If True, stream output in real-time instead of capturing it
    """
    if stream_output:
        # Stream output in real-time
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Print output line by line as it comes in
        for line in process.stdout:
            print(line, end='', flush=True)
        
        process.wait()
        
        if process.returncode != 0:
            print(f"\nError: {error_message}")
            sys.exit(1)
        
        return subprocess.CompletedProcess(
            args=command,
            returncode=process.returncode,
            stdout="",
            stderr=""
        )
    else:
        # Capture output (original behavior)
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"Error: {error_message}")
            if result.stderr:
                print(f"Details: {result.stderr}")
            sys.exit(1)
        
        return result


def parse_ephemeral_storage(value):
    """
    Parse ephemeral_storage value from either integer or string format.
    
    Args:
        value: Either an integer (e.g., 21) or a string (e.g., "21gb", "21GB", "21 gb")
    
    Returns:
        Integer value in GB
    
    Examples:
        parse_ephemeral_storage(21) -> 21
        parse_ephemeral_storage("21gb") -> 21
        parse_ephemeral_storage("21GB") -> 21
        parse_ephemeral_storage("21 gb") -> 21
    """
    if isinstance(value, int):
        return value
    
    if isinstance(value, str):
        # Remove whitespace and convert to lowercase
        value = value.strip().lower()
        
        # Try to extract number and unit
        match = re.match(r'^(\d+)\s*(gb|gib)?$', value)
        if match:
            number = int(match.group(1))
            return number
        
        # If no match, try to parse as integer string
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"Invalid ephemeral_storage format: {value}. Expected integer or string like '21gb'")
    
    raise ValueError(f"Invalid ephemeral_storage type: {type(value)}. Expected int or str")
