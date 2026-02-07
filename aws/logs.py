#!/usr/bin/env python3
"""
CloudWatch Logs management.
"""
import sys
import time


def tail_ecs_logs(logs_client, log_group_name, max_events=20, timeout_seconds=60):
    """
    Tail the ECS log group for new events after deploy.
    Stops when max_events are seen or timeout_seconds have elapsed.
    """
    start_time = time.time()
    start_time_ms = int(start_time * 1000)
    seen_event_ids = set()
    events_collected = 0
    printed_waiting = False

    while time.time() - start_time < timeout_seconds and events_collected < max_events:
        try:
            response = logs_client.filter_log_events(
                logGroupName=log_group_name,
                startTime=start_time_ms,
                limit=min(50, max_events - events_collected + 10),
            )
        except Exception as e:
            print(f"  [logs] {e}")
            break

        events = response.get("events", [])
        if not events and not printed_waiting:
            print("\nTailing CloudWatch Logs (up to {} events or {}s)...".format(max_events, timeout_seconds))
            printed_waiting = True

        for event in events:
            eid = (event.get("logStreamName") or "", event.get("eventId"))
            if eid in seen_event_ids:
                continue
            seen_event_ids.add(eid)
            ts = event.get("timestamp", 0)
            msg = (event.get("message") or "").rstrip()
            stream = event.get("logStreamName") or ""
            print("  [{}] {}".format(stream, msg))
            events_collected += 1
            start_time_ms = max(start_time_ms, ts + 1)
            if events_collected >= max_events:
                break

        if events_collected >= max_events:
            break
        if not response.get("nextToken"):
            time.sleep(2)

    if events_collected:
        print("  (stopped after {} log events)\n".format(events_collected))
    elif printed_waiting:
        print("  (no new log events in {}s)\n".format(timeout_seconds))


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
