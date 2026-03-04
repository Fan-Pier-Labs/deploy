#!/usr/bin/env python3
"""
Generate CloudFormation template for ECS Fargate with optional ALB + CloudFront + Route53.
"""
import json


def _ref(logical_id):
    return {"Ref": logical_id}


def _get_att(logical_id, attr):
    return {"Fn::GetAtt": [logical_id, attr]}


def _sub(template, **kwargs):
    return {"Fn::Sub": [template, kwargs] if kwargs else template}


def _join(delimiter, *parts):
    return {"Fn::Join": [delimiter, list(parts)]}


def build_fargate_template(config):
    """
    Build CloudFormation template dict for Fargate deployment.
    config: parsed user YAML (platform, app_name, aws, task, public, allow_create, environment, etc).
    """
    app_name = config["app_name"]
    aws_cfg = config.get("aws", {})
    task_cfg = config.get("task", {})
    public = config.get("public") or {}
    region = aws_cfg.get("region", "us-east-2")

    cpu = str(task_cfg.get("cpu", 1024))
    memory = str(task_cfg.get("memory", 2048))
    port = int(task_cfg.get("port", 8080))
    replicas = int(task_cfg.get("replicas", 1))
    use_spot = task_cfg.get("spot", True)
    raw_ephemeral = task_cfg.get("ephemeral_storage", 21)
    if isinstance(raw_ephemeral, str):
        raw_ephemeral = raw_ephemeral.lower().replace("gb", "").strip()
    ephemeral = max(20, min(int(raw_ephemeral), 200))

    cluster_name = f"{app_name}-cluster"
    service_name = f"{app_name}-service"
    task_family = f"{app_name}-task"
    log_group = f"/ecs/{app_name}"
    domain = public.get("domain") if public else None
    is_production = bool(domain)  # Public domain always uses CloudFront + ALB (no lightweight mode)

    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": f"ECS Fargate service for {app_name}",
        "Parameters": {
            "ImageUri": {
                "Type": "String",
                "Description": "ECR image URI (e.g. 123456789.dkr.ecr.us-east-2.amazonaws.com/myapp:latest)",
            },
            "VpcId": {
                "Type": "AWS::EC2::VPC::Id",
                "Description": "VPC ID (e.g. default VPC)",
            },
            "SubnetIds": {
                "Type": "CommaDelimitedList",
                "Description": "Comma-separated subnet IDs (e.g. subnet-a,subnet-b)",
            },
        },
        "Resources": {},
        "Outputs": {
            "ClusterName": {"Value": cluster_name, "Description": "ECS cluster name"},
            "ServiceName": {"Value": service_name, "Description": "ECS service name"},
        },
    }

    # IAM execution role for ECS (pull image, logs)
    template["Resources"]["TaskExecutionRole"] = {
        "Type": "AWS::IAM::Role",
        "Properties": {
            "RoleName": _sub(f"{app_name}-ecs-execution"),
            "AssumeRolePolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            },
        },
    }
    template["Resources"]["TaskExecutionRolePolicy"] = {
        "Type": "AWS::IAM::ManagedPolicy",
        "Properties": {
            "Roles": [_ref("TaskExecutionRole")],
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {"Effect": "Allow", "Action": ["ecr:GetAuthorizationToken"], "Resource": "*"},
                    {"Effect": "Allow", "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], "Resource": _sub("arn:aws:ecr:${AWS::Region}:${AWS::AccountId}:repository/*")},
                    {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": _sub("arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/ecs/*")},
                ],
            },
        },
    }

    # Task role (for app permissions, e.g. S3, SQS)
    template["Resources"]["TaskRole"] = {
        "Type": "AWS::IAM::Role",
        "Properties": {
            "RoleName": _sub(f"{app_name}-ecs-task"),
            "AssumeRolePolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}],
            },
        },
    }
    template["Resources"]["TaskRolePolicy"] = {
        "Type": "AWS::IAM::ManagedPolicy",
        "Properties": {
            "Roles": [_ref("TaskRole")],
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {"Effect": "Allow", "Action": ["s3:*", "sqs:*"], "Resource": "*"},
                ],
            },
        },
    }

    # CloudWatch log group
    template["Resources"]["LogGroup"] = {
        "Type": "AWS::Logs::LogGroup",
        "Properties": {"LogGroupName": log_group, "RetentionInDays": 7},
    }

    # Security group for Fargate tasks
    template["Resources"]["FargateSecurityGroup"] = {
        "Type": "AWS::EC2::SecurityGroup",
        "Properties": {
            "GroupName": _sub(f"{app_name}-sg"),
            "GroupDescription": f"Fargate tasks for {app_name}",
            "VpcId": _ref("VpcId"),
            "SecurityGroupIngress": [] if is_production else [
                {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "CidrIp": "0.0.0.0/0"},
            ],
        },
    }

    # ECS cluster
    template["Resources"]["Cluster"] = {
        "Type": "AWS::ECS::Cluster",
        "Properties": {
            "ClusterName": cluster_name,
            "ClusterSettings": [{"Name": "containerInsights", "Value": "enabled"}],
        },
    }

    # Task definition
    container_def = {
        "Name": app_name,
        "Image": _ref("ImageUri"),
        "Essential": True,
        "LogConfiguration": {
            "LogDriver": "awslogs",
            "Options": {
                "awslogs-group": log_group,
                "awslogs-region": region,
                "awslogs-stream-prefix": "ecs",
            },
        },
        "PortMappings": [{"ContainerPort": port, "Protocol": "tcp"}],
    }
    env = config.get("environment") or {}
    if env:
        container_def["Environment"] = [{"Name": k, "Value": str(v)} for k, v in env.items()]

    task_def = {
        "Type": "AWS::ECS::TaskDefinition",
        "Properties": {
            "Family": task_family,
            "NetworkMode": "awsvpc",
            "RequiresCompatibilities": ["FARGATE"],
            "Cpu": cpu,
            "Memory": memory,
            "ExecutionRoleArn": _get_att("TaskExecutionRole", "Arn"),
            "TaskRoleArn": _get_att("TaskRole", "Arn"),
            "ContainerDefinitions": [container_def],
        },
    }
    if ephemeral >= 20:
        task_def["Properties"]["EphemeralStorage"] = {"SizeInGiB": ephemeral}
    template["Resources"]["TaskDefinition"] = task_def

    # ECS service - network config
    subnets_ref = {"Fn::Ref": "SubnetIds"}  # CommaDelimitedList is a string; we need list
    # For CommaDelimitedList, Ref returns a string; use Fn::Split to get list
    subnet_list = {"Fn::Split": [",", _ref("SubnetIds")]}
    network_config = {
        "AwsvpcConfiguration": {
            "Subnets": subnet_list,
            "SecurityGroups": [_ref("FargateSecurityGroup")],
            "AssignPublicIp": "ENABLED",
        },
    }

    capacity_provider = "FARGATE_SPOT" if use_spot else "FARGATE"
    service_props = {
        "Cluster": _ref("Cluster"),
        "ServiceName": service_name,
        "TaskDefinition": _ref("TaskDefinition"),
        "DesiredCount": replicas,
        "CapacityProviderStrategy": [{"CapacityProvider": capacity_provider, "Weight": 1}],
        "NetworkConfiguration": network_config,
    }

    if is_production:
        # ALB security group
        template["Resources"]["ALBSecurityGroup"] = {
            "Type": "AWS::EC2::SecurityGroup",
            "Properties": {
                "GroupName": _sub(f"{app_name}-alb-sg"),
                "GroupDescription": f"ALB for {app_name}",
                "VpcId": _ref("VpcId"),
                "SecurityGroupIngress": [{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "CidrIp": "0.0.0.0/0"}],
            },
        }
        # Allow Fargate SG from ALB
        template["Resources"]["FargateSecurityGroup"]["Properties"]["SecurityGroupIngress"] = [
            {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "SourceSecurityGroupId": _ref("ALBSecurityGroup")},
        ]

        # ALB
        template["Resources"]["ALB"] = {
            "Type": "AWS::ElasticLoadBalancingV2::LoadBalancer",
            "Properties": {
                "Name": _sub(f"{app_name}-alb"),
                "Scheme": "internet-facing",
                "Type": "application",
                "Subnets": subnet_list,
                "SecurityGroups": [_ref("ALBSecurityGroup")],
            },
        }
        template["Resources"]["TargetGroup"] = {
            "Type": "AWS::ElasticLoadBalancingV2::TargetGroup",
            "Properties": {
                "Name": _sub(f"{app_name}-tg"),
                "Port": port,
                "Protocol": "HTTP",
                "VpcId": _ref("VpcId"),
                "TargetType": "ip",
                "HealthCheckPath": "/api/health",
                "HealthCheckProtocol": "HTTP",
            },
        }
        template["Resources"]["Listener"] = {
            "Type": "AWS::ElasticLoadBalancingV2::Listener",
            "Properties": {
                "LoadBalancerArn": _ref("ALB"),
                "Port": 80,
                "Protocol": "HTTP",
                "DefaultActions": [{"Type": "forward", "TargetGroupArn": _ref("TargetGroup")}],
            },
        }

        service_props["LoadBalancers"] = [
            {"TargetGroupArn": _ref("TargetGroup"), "ContainerName": app_name, "ContainerPort": port},
        ]

        # CloudFront + ACM + Route53
        template["Parameters"]["CertificateArn"] = {
            "Type": "String",
            "Description": "ACM certificate ARN (must be in us-east-1) for CloudFront",
        }
        cert_id = public.get("certificate_id")
        if cert_id and isinstance(cert_id, str) and not cert_id.isdigit():
            template["Parameters"]["CertificateArn"]["Default"] = cert_id
        template["Parameters"]["HostedZoneId"] = {
            "Type": "String",
            "Description": "Route53 hosted zone ID for the domain",
        }
        if public.get("hosted_zone_id"):
            template["Parameters"]["HostedZoneId"]["Default"] = public["hosted_zone_id"]

        # CloudFront origin = ALB (use ALB DNS name)
        template["Resources"]["CloudFrontDistribution"] = {
            "Type": "AWS::CloudFront::Distribution",
            "Properties": {
                "DistributionConfig": {
                    "Aliases": [domain],
                    "Origins": [
                        {
                            "Id": "ALBOrigin",
                            "DomainName": _get_att("ALB", "DNSName"),
                            "CustomOriginConfig": {
                                "HTTPPort": 80,
                                "HTTPSPort": 443,
                                "OriginProtocolPolicy": "http-only",
                            },
                        }
                    ],
                    "DefaultCacheBehavior": {
                        "TargetOriginId": "ALBOrigin",
                        "ViewerProtocolPolicy": "redirect-to-https",
                        "AllowedMethods": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                        "CachedMethods": ["GET", "HEAD"],
                        "Compress": True,
                        "DefaultTTL": 0,
                        "MinTTL": 0,
                        "MaxTTL": 0,
                    },
                    "Enabled": True,
                    "PriceClass": "PriceClass_All",
                    "ViewerCertificate": {
                        "AcmCertificateArn": _ref("CertificateArn"),
                        "SslSupportMethod": "sni-only",
                        "MinimumProtocolVersion": "TLSv1.2_2021",
                    },
                },
            },
        }
        template["Resources"]["DNSRecord"] = {
            "Type": "AWS::Route53::RecordSet",
            "Properties": {
                "HostedZoneId": _ref("HostedZoneId"),
                "Name": domain if domain.endswith(".") else f"{domain}.",
                "Type": "A",
                "AliasTarget": {
                    "DNSName": _get_att("CloudFrontDistribution", "DomainName"),
                    "HostedZoneId": "Z2FDTNDATAQYW2",
                    "EvaluateTargetHealth": False,
                },
            },
        }
        template["Outputs"]["CloudFrontId"] = {"Value": _ref("CloudFrontDistribution"), "Description": "CloudFront distribution ID"}
        template["Outputs"]["Domain"] = {"Value": domain, "Description": "Public domain"}

    template["Resources"]["Service"] = {"Type": "AWS::ECS::Service", "Properties": service_props}

    return template
