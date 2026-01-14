#!/usr/bin/env python3
"""
EventBridge event capture for ECS clusters.
"""
import json
import sys


def enable_event_capture(events_client, logs_client, cluster_name, region, account_id, allow_create=False):
    """
    Enable event capture for an ECS cluster using EventBridge and CloudWatch Logs.
    EventBridge can write directly to CloudWatch Logs without needing a Lambda function.
    
    Note: The native ECS event capture feature (the one-click "Turn on event capture" button
    in the AWS Console) can only be enabled via the console and is not available via API.
    This function implements equivalent functionality programmatically by setting up the same
    underlying resources (EventBridge rule, CloudWatch Logs log group, and resource policy).
    """
    # CloudWatch Logs log group for ECS events
    events_log_group_name = f"/aws/ecs/events/{cluster_name}"
    # EventBridge rule name for capturing ECS events
    rule_name = f"ecs-event-capture-{cluster_name}"
    log_group_arn = f"arn:aws:logs:{region}:{account_id}:log-group:{events_log_group_name}"
    rule_arn = f"arn:aws:events:{region}:{account_id}:rule/{rule_name}"
    
    # Step 1: Create or ensure CloudWatch Logs log group exists
    try:
        existing = logs_client.describe_log_groups(logGroupNamePrefix=events_log_group_name)
        existing = [lg for lg in existing['logGroups'] 
                   if lg['logGroupName'] == events_log_group_name]
        
        if existing:
            print(f"Using existing event capture log group: {events_log_group_name}")
        else:
            if not allow_create:
                print(f"Event capture log group '{events_log_group_name}' does not exist and resource creation is disabled.")
                sys.exit(1)
            
            print(f"Creating event capture log group: {events_log_group_name}")
            logs_client.create_log_group(logGroupName=events_log_group_name)
            
            # Set retention policy to 7 days (default for event capture)
            logs_client.put_retention_policy(
                logGroupName=events_log_group_name,
                retentionInDays=7
            )
            print(f"Created event capture log group with 7-day retention: {events_log_group_name}")
    except logs_client.exceptions.ResourceAlreadyExistsException:
        print(f"Event capture log group already exists: {events_log_group_name}")
    except Exception as e:
        print(f"Error creating event capture log group: {e}")
        sys.exit(1)
    
    # Step 2: Set up CloudWatch Logs resource policy to allow EventBridge to write
    resource_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowEventBridgeToWriteLogs",
                "Effect": "Allow",
                "Principal": {
                    "Service": "events.amazonaws.com"
                },
                "Action": "logs:PutLogEvents",
                "Resource": log_group_arn,
                "Condition": {
                    "ArnEquals": {
                        "aws:SourceArn": rule_arn
                    }
                }
            }
        ]
    }
    
    try:
        logs_client.put_resource_policy(
            policyName=f"EventBridge-{cluster_name}",
            policyDocument=json.dumps(resource_policy)
        )
        print(f"Set CloudWatch Logs resource policy for EventBridge")
    except Exception as e:
        print(f"Note: Could not set resource policy (may already exist): {e}")
    
    # Step 3: Create EventBridge rule to capture ECS events
    event_pattern = {
        "source": ["aws.ecs"],
        "detail-type": [
            "ECS Task State Change",
            "ECS Service Action",
            "ECS Deployment State Change",
            "ECS Container Instance State Change"
        ],
        "detail": {
            "clusterArn": [f"arn:aws:ecs:{region}:{account_id}:cluster/{cluster_name}"]
        }
    }
    
    try:
        # Check if rule already exists
        try:
            events_client.describe_rule(Name=rule_name)
            print(f"EventBridge rule {rule_name} already exists, updating...")
            
            # Update the rule
            events_client.put_rule(
                Name=rule_name,
                EventPattern=json.dumps(event_pattern),
                State='ENABLED',
                Description=f'Captures ECS events for cluster {cluster_name}'
            )
        except events_client.exceptions.ResourceNotFoundException:
            if not allow_create:
                print(f"EventBridge rule '{rule_name}' does not exist and resource creation is disabled.")
                sys.exit(1)
            
            print(f"Creating EventBridge rule: {rule_name}")
            events_client.put_rule(
                Name=rule_name,
                EventPattern=json.dumps(event_pattern),
                State='ENABLED',
                Description=f'Captures ECS events for cluster {cluster_name}'
            )
        
        # Step 4: Set up EventBridge target (CloudWatch Logs directly)
        # Remove any existing targets first
        try:
            existing_targets = events_client.list_targets_by_rule(Rule=rule_name)
            if existing_targets['Targets']:
                target_ids = [target['Id'] for target in existing_targets['Targets']]
                events_client.remove_targets(Rule=rule_name, Ids=target_ids)
        except Exception:
            pass  # No existing targets, that's fine
        
        # Add CloudWatch Logs as target - EventBridge can write directly
        target_id = f"ecs-events-{cluster_name}"
        events_client.put_targets(
            Rule=rule_name,
            Targets=[
                {
                    'Id': target_id,
                    'Arn': log_group_arn
                }
            ]
        )
        
        print(f"Enabled event capture for cluster: {cluster_name}")
        print(f"  EventBridge rule: {rule_name}")
        print(f"  CloudWatch Logs group: {events_log_group_name}")
        
    except Exception as e:
        print(f"Error setting up event capture: {e}")
        sys.exit(1)
