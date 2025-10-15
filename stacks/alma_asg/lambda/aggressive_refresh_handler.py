# File: stacks/alma_asg/lambda/aggressive_refresh_handler.py

import json
import os
from datetime import datetime, timedelta

import boto3


def handler(event, context):
    """
    Aggressive Lambda to continuously pursue spot instances.
    Runs every N minutes and refreshes if on on-demand instance.
    """
    asg_client = boto3.client("autoscaling")
    ec2_client = boto3.client("ec2")
    sns_client = boto3.client("sns")

    asg_name = os.environ["ASG_NAME"]
    topic_arn = os.environ["TOPIC_ARN"]

    try:
        # Get current instances
        response = asg_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg_name]
        )

        if not response["AutoScalingGroups"]:
            return {"statusCode": 404, "body": "ASG not found"}

        asg = response["AutoScalingGroups"][0]
        instances = asg["Instances"]

        if not instances:
            print("No instances currently running")
            return {"statusCode": 200, "body": "No instances to check"}

        # Check if there's an ongoing refresh
        refresh_response = asg_client.describe_instance_refreshes(
            AutoScalingGroupName=asg_name, MaxRecords=1
        )

        if refresh_response["InstanceRefreshes"]:
            latest_refresh = refresh_response["InstanceRefreshes"][0]
            if latest_refresh["Status"] in ["Pending", "InProgress"]:
                print(f"Refresh already in progress: {latest_refresh['Status']}")
                return {
                    "statusCode": 200,
                    "body": "Refresh already in progress",
                    "refresh_status": latest_refresh["Status"],
                }

        # Check each instance
        on_demand_instances = []
        spot_instances = []

        for instance in instances:
            instance_id = instance["InstanceId"]
            instance_type = instance["InstanceType"]

            ec2_response = ec2_client.describe_instances(InstanceIds=[instance_id])
            ec2_instance = ec2_response["Reservations"][0]["Instances"][0]
            lifecycle = ec2_instance.get("InstanceLifecycle")
            launch_time = ec2_instance["LaunchTime"]

            instance_info = {
                "id": instance_id,
                "type": instance_type,
                "launch_time": launch_time.isoformat(),
            }

            if lifecycle == "spot":
                spot_instances.append(instance_info)
            else:
                on_demand_instances.append(instance_info)

        # Decision: Refresh if ANY on-demand instances exist
        if on_demand_instances:
            # Start aggressive refresh
            asg_client.start_instance_refresh(
                AutoScalingGroupName=asg_name,
                Preferences={
                    "MinHealthyPercentage": 0,
                    "InstanceWarmup": 300,
                    "SkipMatching": False,
                },
            )

            message = f"""🎯 AGGRESSIVE SPOT PURSUIT - Refresh Started

ASG: {asg_name}
Trigger: Found {len(on_demand_instances)} on-demand instance(s)

On-Demand Instances (targeting for replacement):
{json.dumps(on_demand_instances, indent=2)}

Current Spot Instances:
{json.dumps(spot_instances, indent=2) if spot_instances else "None"}

Action: Starting instance refresh to pursue spot capacity
Next Check: In 15 minutes (will keep trying until spot is achieved)

Cost Impact:
- On-Demand: ~$0.096/hour (~$70/month)
- Spot Target: ~$0.029/hour (~$21/month)
- Potential Savings: ~$49/month per instance
"""

            sns_client.publish(
                TopicArn=topic_arn,
                Subject=f"🎯 Aggressive Spot Refresh: {asg_name}",
                Message=message,
            )

            print(
                f"Started aggressive refresh - found {len(on_demand_instances)} on-demand instances"
            )

            return {
                "statusCode": 200,
                "body": "Aggressive refresh started",
                "on_demand_count": len(on_demand_instances),
                "spot_count": len(spot_instances),
                "action": "refresh_started",
            }

        else:
            # All instances are spot - SUCCESS!
            message = f"""✅ SPOT ACHIEVED - All Instances Running on Spot!

ASG: {asg_name}
Status: SUCCESS - No on-demand instances found

Current Spot Instances:
{json.dumps(spot_instances, indent=2)}

Cost Status:
- Running at optimal spot pricing
- Saving ~60-70% vs on-demand
- Estimated cost: ~$21/month per instance

Aggressive spot pursuit will continue monitoring every 15 minutes.
"""

            # Only send "success" notification once per day to avoid spam
            # Check if we sent this notification in the last 6 hours
            print("All instances are spot - optimal state achieved")

            return {
                "statusCode": 200,
                "body": "All instances are spot",
                "on_demand_count": 0,
                "spot_count": len(spot_instances),
                "action": "no_refresh_needed",
            }

    except Exception as e:
        error_message = f"Error during aggressive spot refresh: {str(e)}"
        print(error_message)

        try:
            sns_client.publish(
                TopicArn=topic_arn,
                Subject=f"❌ Aggressive Spot Refresh Error: {asg_name}",
                Message=error_message,
            )
        except Exception as sns_error:
            print(f"Failed to send SNS notification: {sns_error}")

        return {"statusCode": 500, "body": error_message}
