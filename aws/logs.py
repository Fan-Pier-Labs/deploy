#!/usr/bin/env python3
"""
CloudWatch Logs management.
"""
import sys


def ensure_cloudwatch_log_group(logs_client, log_group_name, allow_create=False):
    """
    Ensure CloudWatch log group exists for ECS task logs.
    Fargate should create this automatically, but often fails with permission errors if it doesn't exist.
    """
    try:
        logs_client.describe_log_groups(logGroupNamePrefix=log_group_name)
        existing = [lg for lg in logs_client.describe_log_groups(logGroupNamePrefix=log_group_name)['logGroups'] 
                   if lg['logGroupName'] == log_group_name]
        
        if existing:
            print(f"Using existing log group: {log_group_name}")
            return
        
        if not allow_create:
            print(f"Log group '{log_group_name}' does not exist and resource creation is disabled.")
            sys.exit(1)
        
        print(f"Creating CloudWatch log group: {log_group_name}")
        logs_client.create_log_group(logGroupName=log_group_name)
        
        # Set retention policy to 30 days to avoid unlimited log storage costs
        logs_client.put_retention_policy(
            logGroupName=log_group_name,
            retentionInDays=30
        )
        print(f"Created log group with 30-day retention: {log_group_name}")
        
    except logs_client.exceptions.ResourceAlreadyExistsException:
        print(f"Log group already exists: {log_group_name}")
