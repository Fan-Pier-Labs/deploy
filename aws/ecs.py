#!/usr/bin/env python3
"""
ECS cluster, service, and task definition management.
"""
import sys


def ensure_cluster(ecs_client, cluster_name, allow_create=False):
    """
    Ensure ECS cluster exists.
    """
    clusters = ecs_client.describe_clusters(clusters=[cluster_name])
    cluster_exists = bool(clusters['clusters'])
    
    if cluster_exists:
        print(f"ECS cluster {cluster_name} already exists")
    else:
        if not allow_create:
            print(f"ECS cluster '{cluster_name}' does not exist and resource creation is disabled.")
            sys.exit(1)
            
        ecs_client.create_cluster(clusterName=cluster_name)
        print(f"Created ECS cluster: {cluster_name}")
    
    # Enable Container Insights with enhanced observability
    ecs_client.put_cluster_capacity_providers(
        cluster=cluster_name,
        capacityProviders=['FARGATE', 'FARGATE_SPOT'],
        defaultCapacityProviderStrategy=[],
    )
    
    cluster_settings = [
        {
            'name': 'containerInsights',
            'value': 'enhanced'
        },
    ]
    
    ecs_client.update_cluster_settings(
        cluster=cluster_name,
        settings=cluster_settings
    )
    print(f"Enabled Container Insights with enhanced observability on cluster: {cluster_name}")


def register_task_definition(ecs_client, task_family, image_name, app_name, region, 
                            cpu, memory, ephemeral_storage, execution_role_arn, 
                            environment_variables=None, port=8080):
    """
    Register ECS task definition.
    Returns the task definition ARN.
    """
    print("Registering task definition...")
    
    # Prepare container definition
    container_def = {
        'name': app_name,
        'image': image_name,
        'essential': True,
        'logConfiguration': {
            'logDriver': 'awslogs',
            'options': {
                'awslogs-group': f"/ecs/{app_name}",
                'awslogs-region': region,
                'awslogs-stream-prefix': 'ecs'
            }
        },
        'portMappings': [
            {
                'containerPort': port,
                'protocol': 'tcp'
            }
        ]
    }
    
    # Add environment variables if provided
    if environment_variables:
        container_def['environment'] = [
            {'name': key, 'value': value} for key, value in environment_variables.items()
        ]
        print(f"Adding environment variables: {', '.join(environment_variables.keys())}")
    
    # Prepare task definition parameters
    task_def_params = {
        'family': task_family,
        'requiresCompatibilities': ['FARGATE'],
        'networkMode': 'awsvpc',
        'cpu': cpu,
        'memory': memory,
        'executionRoleArn': execution_role_arn,
        'taskRoleArn': execution_role_arn,
        'containerDefinitions': [container_def]
    }
    
    # Add ephemeral storage configuration if specified
    if ephemeral_storage and ephemeral_storage >= 20:
        storage_size = min(max(ephemeral_storage, 20), 200)
        task_def_params['ephemeralStorage'] = {
            'sizeInGiB': storage_size
        }
        print(f"Setting ephemeral storage to {storage_size} GB")
    
    # Register the task definition
    response = ecs_client.register_task_definition(**task_def_params)
    
    task_definition_arn = response['taskDefinition']['taskDefinitionArn']
    print(f"Task definition registered: {task_definition_arn}")
    
    return task_definition_arn


def create_or_update_service(ecs_client, cluster_name, service_name, task_definition_arn,
                            desired_count, use_spot, subnet_ids, security_group_id,
                            allow_create=False, load_balancer_config=None):
    """
    Create or update ECS service.
    load_balancer_config should be a dict with 'targetGroupArn' and 'containerName' keys.
    """
    print("Creating/updating ECS service...")
    
    # Check if service exists
    services = ecs_client.describe_services(cluster=cluster_name, services=[service_name])
    service_exists = services['services'] and services['services'][0]['status'] != 'INACTIVE'
    
    capacity_provider = 'FARGATE_SPOT' if use_spot else 'FARGATE'
    
    network_config = {
        'awsvpcConfiguration': {
            'subnets': subnet_ids,
            'securityGroups': [security_group_id],
            'assignPublicIp': 'ENABLED'  # Always enable public IP for ECR access, even with ALB
        }
    }
    
    if service_exists:
        # Check current service configuration
        current_service = services['services'][0]
        current_load_balancers = current_service.get('loadBalancers', [])
        
        # Update existing service
        update_params = {
            'cluster': cluster_name,
            'service': service_name,
            'taskDefinition': task_definition_arn,
            'desiredCount': desired_count,
            'forceNewDeployment': True,
            'capacityProviderStrategy': [
                {
                    'capacityProvider': capacity_provider,
                    'weight': 1
                }
            ],
            'networkConfiguration': network_config
        }
        
        if load_balancer_config:
            update_params['loadBalancers'] = [load_balancer_config]
            print(f"  Configuring load balancer:")
            print(f"    Target Group: {load_balancer_config['targetGroupArn']}")
            print(f"    Container: {load_balancer_config['containerName']}")
            print(f"    Port: {load_balancer_config['containerPort']}")
            
            # Check if load balancer config changed
            if current_load_balancers:
                current_tg = current_load_balancers[0].get('targetGroupArn', '')
                new_tg = load_balancer_config['targetGroupArn']
                if current_tg != new_tg:
                    print(f"  Note: Load balancer target group changed - new tasks will be deployed")
            else:
                print(f"  Note: Adding load balancer to existing service - new tasks will be deployed")
        
        response = ecs_client.update_service(**update_params)
        print(f"Updated service: {service_name} with {desired_count} {'Spot ' if use_spot else ''}instances")
    else:
        if not allow_create:
            print(f"ECS service '{service_name}' does not exist and resource creation is disabled.")
            sys.exit(1)
        
        # Create new service
        create_params = {
            'cluster': cluster_name,
            'serviceName': service_name,
            'taskDefinition': task_definition_arn,
            'capacityProviderStrategy': [
                {
                    'capacityProvider': capacity_provider,
                    'weight': 1
                }
            ],
            'desiredCount': desired_count,
            'networkConfiguration': network_config
        }
        
        if load_balancer_config:
            create_params['loadBalancers'] = [load_balancer_config]
        
        response = ecs_client.create_service(**create_params)
        print(f"Created service: {service_name}")
    
    return response
