# File: lambdas/site_manager/index.py

import json
import boto3
import time
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    """
    Site Manager Lambda function
    Creates new DDEV sites dynamically including:
    - Site creation on EC2 via SSM
    - Target group creation
    - ALB listener rule creation
    - CloudFlare DNS record creation
    """
    logger.info(f"Event: {json.dumps(event)}")
    
    # Parse input
    site_name = event.get('site_name')
    port = event.get('port')
    
    # Auto-calculate port if not provided
    if not port and site_name.startswith('qa'):
        try:
            site_num = int(site_name[2:])  # Extract number from qa3, qa4, etc.
            port = 8000 + site_num
        except (ValueError, IndexError):
            port = 8010  # Default fallback
    elif not port:
        port = 8010  # Default fallback
    
    if not site_name:
        return {'error': 'site_name is required'}
    
    # AWS clients
    ssm = boto3.client('ssm')
    ec2 = boto3.client('ec2')
    elbv2 = boto3.client('elbv2')
    lambda_client = boto3.client('lambda')
    
    # Get environment variables set by CDK
    instance_id = os.environ['INSTANCE_ID']
    alb_arn = os.environ['ALB_ARN']
    vpc_id = os.environ['VPC_ID']
    alb_dns_name = os.environ['ALB_DNS_NAME']
    listener_arn = os.environ['HTTPS_LISTENER_ARN']
    dns_lambda_name = os.environ['DNS_LAMBDA_NAME']
    
    try:
        # 1. Create site on EC2 instance via SSM
        logger.info(f"Creating site {site_name} on port {port}")
        
        response = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={
                'commands': [f'/opt/ddev-scripts/create-site.sh {site_name} {port}']
            },
            TimeoutSeconds=300
        )
        
        command_id = response['Command']['CommandId']
        
        # Wait for command to complete
        for i in range(30):  # Wait up to 5 minutes
            result = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )
            if result['Status'] in ['Success', 'Failed']:
                break
            time.sleep(10)
        
        if result['Status'] != 'Success':
            error_msg = result.get('StandardErrorContent', 'Unknown error')
            logger.error(f"Failed to create site: {error_msg}")
            return {'error': f'Failed to create site: {error_msg}'}
        
        logger.info(f"Site {site_name} created successfully")
        
        # 2. Create target group
        logger.info(f"Creating target group for {site_name}")
        
        target_group_response = elbv2.create_target_group(
            Name=f'{site_name}-tg',
            Protocol='HTTP',
            Port=port,
            VpcId=vpc_id,
            HealthCheckPath='/health',
            HealthCheckProtocol='HTTP',
            HealthCheckPort=str(port),
            HealthCheckIntervalSeconds=30,
            HealthCheckTimeoutSeconds=5,
            HealthyThresholdCount=2,
            UnhealthyThresholdCount=5,
            Matcher={'HttpCode': '200,404'}
        )
        
        target_group_arn = target_group_response['TargetGroups'][0]['TargetGroupArn']
        logger.info(f"Target group created: {target_group_arn}")
        
        # 3. Register instance with target group
        elbv2.register_targets(
            TargetGroupArn=target_group_arn,
            Targets=[{'Id': instance_id, 'Port': port}]
        )
        logger.info(f"Instance registered with target group")
        
        # 4. Create listener rule
        # Get next available priority
        existing_rules = elbv2.describe_rules(ListenerArn=listener_arn)
        priorities = [int(rule['Priority']) for rule in existing_rules['Rules'] if rule['Priority'] != 'default']
        next_priority = max(priorities) + 10 if priorities else 100
        
        elbv2.create_rule(
            ListenerArn=listener_arn,
            Conditions=[
                {
                    'Field': 'host-header',
                    'Values': [f'{site_name}.vadai.org']
                }
            ],
            Priority=next_priority,
            Actions=[
                {
                    'Type': 'forward',
                    'TargetGroupArn': target_group_arn
                }
            ]
        )
        logger.info(f"Listener rule created with priority {next_priority}")
        
        # 5. Create CloudFlare DNS record
        logger.info(f"Creating DNS record for {site_name}.vadai.org")
        
        dns_payload = {
            'RequestType': 'Create',
            'ResourceProperties': {
                'DomainName': f'{site_name}.vadai.org',
                'TargetValue': alb_dns_name,
                'RecordType': 'CNAME'
            }
        }
        
        lambda_client.invoke(
            FunctionName=dns_lambda_name,
            InvocationType='Event',
            Payload=json.dumps(dns_payload)
        )
        logger.info(f"DNS creation request sent")
        
        return {
            'success': True,
            'site_name': site_name,
            'port': port,
            'url': f'https://{site_name}.vadai.org',
            'target_group_arn': target_group_arn,
            'priority': next_priority,
            'message': f'Site {site_name} created successfully. It may take a few minutes for DNS to propagate.'
        }
        
    except Exception as e:
        logger.error(f"Error creating site: {str(e)}")
        return {'error': str(e)}