# File: stacks/alma_asg/lambda/refresh_handler.py

import boto3
import os
import json


def handler(event, context):
    """
    Lambda function to check ASG instances and refresh if needed.
    
    Environment Variables:
        ASG_NAME: Auto Scaling Group name
        TOPIC_ARN: SNS topic for notifications
        REFRESH_ONLY_ON_DEMAND: 'true' or 'false'
    """
    asg_client = boto3.client('autoscaling')
    ec2_client = boto3.client('ec2')
    sns_client = boto3.client('sns')
    
    asg_name = os.environ['ASG_NAME']
    topic_arn = os.environ['TOPIC_ARN']
    refresh_only_on_demand = os.environ['REFRESH_ONLY_ON_DEMAND'] == 'true'
    
    try:
        # Get current instances
        response = asg_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg_name]
        )
        
        if not response['AutoScalingGroups']:
            return {'statusCode': 404, 'body': 'ASG not found'}
        
        instances = response['AutoScalingGroups'][0]['Instances']
        
        if not instances:
            return {'statusCode': 200, 'body': 'No instances to check'}
        
        # Check each instance
        on_demand_instances = []
        spot_instances = []
        
        for instance in instances:
            instance_id = instance['InstanceId']
            instance_type = instance['InstanceType']
            
            ec2_response = ec2_client.describe_instances(InstanceIds=[instance_id])
            lifecycle = ec2_response['Reservations'][0]['Instances'][0].get('InstanceLifecycle')
            
            if lifecycle == 'spot':
                spot_instances.append({'id': instance_id, 'type': instance_type})
            else:
                on_demand_instances.append({'id': instance_id, 'type': instance_type})
        
        # Decide whether to refresh
        should_refresh = False
        reason = ""
        
        if on_demand_instances:
            should_refresh = True
            reason = f"Found {len(on_demand_instances)} on-demand instance(s)"
        elif not refresh_only_on_demand:
            should_refresh = True
            reason = "Scheduled refresh to optimize spot pricing"
        else:
            reason = "All instances are spot, no refresh needed"
        
        # Build notification message
        message = f"""ASG Scheduled Refresh Check - {asg_name}

Current State:
- Spot Instances: {len(spot_instances)}
- On-Demand Instances: {len(on_demand_instances)}

On-Demand Details: {json.dumps(on_demand_instances, indent=2) if on_demand_instances else 'None'}
Spot Details: {json.dumps(spot_instances, indent=2)}

Decision: {'REFRESHING' if should_refresh else 'NO REFRESH'}
Reason: {reason}
"""
        
        if should_refresh:
            # Start instance refresh
            asg_client.start_instance_refresh(
                AutoScalingGroupName=asg_name,
                Preferences={
                    'MinHealthyPercentage': 0,
                    'InstanceWarmup': 300
                }
            )
            
            message += "\n✅ Instance refresh started"
            
            # Send SNS notification
            sns_client.publish(
                TopicArn=topic_arn,
                Subject=f"ASG Refresh Started: {asg_name}",
                Message=message
            )
            
            return {
                'statusCode': 200,
                'body': 'Instance refresh started',
                'details': {
                    'on_demand_count': len(on_demand_instances),
                    'spot_count': len(spot_instances),
                    'action': 'refreshed'
                }
            }
        else:
            # Send notification that no refresh is needed
            sns_client.publish(
                TopicArn=topic_arn,
                Subject=f"ASG Refresh Check: {asg_name} (No Action)",
                Message=message
            )
            
            return {
                'statusCode': 200,
                'body': 'No refresh needed',
                'details': {
                    'on_demand_count': len(on_demand_instances),
                    'spot_count': len(spot_instances),
                    'action': 'skipped'
                }
            }
            
    except Exception as e:
        error_message = f"Error during ASG refresh check: {str(e)}"
        print(error_message)
        
        # Send error notification
        try:
            sns_client.publish(
                TopicArn=topic_arn,
                Subject=f"❌ ASG Refresh Error: {asg_name}",
                Message=error_message
            )
        except Exception as sns_error:
            print(f"Failed to send SNS notification: {sns_error}")
        
        return {
            'statusCode': 500,
            'body': error_message
        }
