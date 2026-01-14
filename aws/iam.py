#!/usr/bin/env python3
"""
IAM role management for ECS tasks.
"""
import json
import sys


def ensure_ecs_execution_role(iam_client, account_id, required_policies, custom_policy=None, allow_create=False):
    """
    Ensure the ECS task execution role exists with the correct policies.
    Syncs policies: adds missing ones and removes ones not in the config.
    Also manages a custom inline policy for fine-grained permissions.
    """
    role_name = 'ecsTaskExecutionRole'
    inline_policy_name = 'CustomResourcePermissions'
    
    try:
        # Check if role exists
        iam_client.get_role(RoleName=role_name)
        print(f"Using existing IAM role: {role_name}")
        
        # Get currently attached policies
        response = iam_client.list_attached_role_policies(RoleName=role_name)
        current_policies = {policy['PolicyArn'] for policy in response['AttachedPolicies']}
        
        # Convert required_policies to a set for comparison
        required_policies_set = set(required_policies)
        
        # Determine which policies to add and remove
        policies_to_add = required_policies_set - current_policies
        policies_to_remove = current_policies - required_policies_set
        
        # Add missing policies
        for policy_arn in policies_to_add:
            print(f"Attaching policy: {policy_arn}")
            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn=policy_arn
            )
        
        # Remove policies not in config
        for policy_arn in policies_to_remove:
            print(f"Detaching policy: {policy_arn}")
            iam_client.detach_role_policy(
                RoleName=role_name,
                PolicyArn=policy_arn
            )
        
        if policies_to_add or policies_to_remove:
            print(f"IAM role policies synced. Added: {len(policies_to_add)}, Removed: {len(policies_to_remove)}")
        else:
            print("IAM role policies are already in sync")
        
        # Handle custom inline policy
        if custom_policy:
            # Add Version if not present
            if 'Version' not in custom_policy:
                custom_policy['Version'] = '2012-10-17'
            
            print(f"Updating custom inline policy: {inline_policy_name}")
            iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName=inline_policy_name,
                PolicyDocument=json.dumps(custom_policy)
            )
            print("Custom inline policy updated")
        else:
            # Remove inline policy if it exists but is not in config
            try:
                iam_client.get_role_policy(RoleName=role_name, PolicyName=inline_policy_name)
                print(f"Removing custom inline policy: {inline_policy_name}")
                iam_client.delete_role_policy(RoleName=role_name, PolicyName=inline_policy_name)
            except iam_client.exceptions.NoSuchEntityException:
                pass  # Policy doesn't exist, nothing to remove
            
    except iam_client.exceptions.NoSuchEntityException:
        if not allow_create:
            print(f"IAM role '{role_name}' does not exist and resource creation is disabled.")
            sys.exit(1)
            
        print(f"Creating IAM role: {role_name}")
        
        # Create the role with trust relationship for ECS
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy)
        )
        
        # Attach all required policies
        for policy_arn in required_policies:
            print(f"Attaching policy: {policy_arn}")
            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn=policy_arn
            )
        
        # Add custom inline policy if provided
        if custom_policy:
            if 'Version' not in custom_policy:
                custom_policy['Version'] = '2012-10-17'
            print(f"Adding custom inline policy: {inline_policy_name}")
            iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName=inline_policy_name,
                PolicyDocument=json.dumps(custom_policy)
            )
        
        print(f"Created role {role_name} with {len(required_policies)} managed policies" + 
              (" and custom inline policy" if custom_policy else ""))
    
    return f'arn:aws:iam::{account_id}:role/{role_name}'
