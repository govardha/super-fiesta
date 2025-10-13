# File: stacks/alma_asg/alma_asg_stack.py

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_autoscaling as autoscaling,
    aws_iam as iam,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subscriptions,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    CfnOutput,
    Duration,
    Tags,
)
from constructs import Construct
from configs.config import AppConfigs
from configs.models import InfrastructureSpec


class AlmaASGStack(Stack):
    """
    Auto Scaling Group for AlmaLinux with spot/on-demand failover.
    
    Features:
    - Prefers spot instances, falls back to on-demand if unavailable
    - Multiple instance type options for better spot availability
    - Automatic recovery when instances are terminated
    - SNS notifications for all scaling events
    - Uses existing SimpleNetwork VPC
    - Configuration from infrastructure.yaml
    """
    
    def __init__(
        self, 
        scope: Construct, 
        construct_id: str,
        vpc: ec2.IVpc,
        account_name: str = "sandbox",
        notification_email: str = None,  # Optional email for notifications
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Load configuration
        self.config_loader = AppConfigs()
        self.infra_config: InfrastructureSpec = self.config_loader.get_infrastructure_info(account_name)
        self.account_name = account_name
        self.vpc = vpc
        self.notification_email = notification_email
        
        # Create security group
        self.create_security_group()
        
        # Create IAM role
        self.create_iam_role()
        
        # Create SNS topic for notifications
        self.create_notification_topic()
        
        # Create Launch Template
        self.create_launch_template()
        
        # Create Auto Scaling Group with mixed instances (spot + on-demand)
        self.create_auto_scaling_group()
        
        # Create CloudWatch alarms
        self.create_cloudwatch_alarms()
        
        # Create scheduled refresh if enabled
        if (self.infra_config.compute and 
            self.infra_config.compute.asg and 
            self.infra_config.compute.asg.enable_daily_refresh):
            self.create_scheduled_refresh()
        
        # Create outputs
        self.create_outputs()
    
    def create_security_group(self):
        """Create security group following existing pattern"""
        self.security_group = ec2.SecurityGroup(
            self,
            "AlmaASGSecurityGroup",
            vpc=self.vpc,
            description=f"Security group for AlmaLinux ASG in {self.account_name}",
            allow_all_outbound=True,
        )
        
        # Allow traffic from within VPC
        self.security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.all_traffic(),
            description="Allow all traffic from VPC CIDR",
        )
        
        Tags.of(self.security_group).add("Name", f"AlmaASG-{self.account_name}-SG")
    
    def create_iam_role(self):
        """Create IAM role following existing pattern"""
        self.instance_role = iam.Role(
            self,
            "AlmaASGInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description=f"IAM role for AlmaLinux ASG instances in {self.account_name}",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
                iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"),
            ],
            inline_policies={
                "ASGInstancePolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "ec2:DescribeInstances",
                                "ec2:DescribeTags",
                                "autoscaling:DescribeAutoScalingGroups",
                                "autoscaling:DescribeAutoScalingInstances",
                                "autoscaling:CompleteLifecycleAction",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                            ],
                            resources=["*"],
                        )
                    ]
                )
            },
        )
    
    def create_notification_topic(self):
        """Create SNS topic with detailed notifications"""
        self.notification_topic = sns.Topic(
            self,
            "ASGNotificationTopic",
            display_name=f"AlmaLinux ASG Notifications - {self.account_name}",
            topic_name=f"AlmaASG-{self.account_name}-Notifications",
        )
        
        # Subscribe email if provided
        if self.notification_email:
            self.notification_topic.add_subscription(
                sns_subscriptions.EmailSubscription(self.notification_email)
            )
            
        # Grant publish permissions to AutoScaling service
        self.notification_topic.grant_publish(
            iam.ServicePrincipal("autoscaling.amazonaws.com")
        )
    
    def create_launch_template(self):
        """Create launch template using configuration from infrastructure.yaml"""
        
        # Get AMI from configuration
        if not self.infra_config.compute or not self.infra_config.compute.almalinux_amis:
            raise ValueError("AlmaLinux AMI configuration not found in infrastructure.yaml")
        
        region = self.infra_config.region
        # Default to AlmaLinux 9 if not specified
        os_version = "9"
        
        if region not in self.infra_config.compute.almalinux_amis:
            raise ValueError(f"AlmaLinux AMI not configured for region {region}")
        
        if os_version not in self.infra_config.compute.almalinux_amis[region]:
            raise ValueError(f"AlmaLinux {os_version} AMI not configured for region {region}")
        
        ami_id = self.infra_config.compute.almalinux_amis[region][os_version]
        machine_image = ec2.MachineImage.generic_linux({region: ami_id})
        
        # User data script with notification details
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "#!/bin/bash",
            "set -e",
            "",
            "# Log all output",
            "exec > >(tee /var/log/user-data.log)",
            "exec 2>&1",
            "",
            "echo '=== AlmaLinux ASG Instance Setup Started at $(date) ==='",
            "",
            "# Update system",
            "dnf update -y",
            "",
            "# Install essential packages",
            "dnf install -y wget curl git vim htop tmux jq",
            "",
            "# Get instance metadata",
            "INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)",
            "REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)",
            "AZ=$(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone)",
            "INSTANCE_TYPE=$(curl -s http://169.254.169.254/latest/meta-data/instance-type)",
            "LOCAL_IP=$(curl -s http://169.254.169.254/latest/meta-data/local-ipv4)",
            "",
            "# Determine if this is spot or on-demand",
            "INSTANCE_LIFECYCLE=$(curl -s http://169.254.169.254/latest/meta-data/instance-life-cycle || echo 'on-demand')",
            "",
            "# Send notification to SNS about instance launch",
            f"aws sns publish --region {region} \\",
            f"  --topic-arn {self.notification_topic.topic_arn} \\",
            "  --subject \"AlmaLinux ASG: New Instance Launched\" \\",
            "  --message \"Instance Details:",
            "- Instance ID: $INSTANCE_ID",
            "- Instance Type: $INSTANCE_TYPE",
            "- Lifecycle: $INSTANCE_LIFECYCLE",
            "- Availability Zone: $AZ",
            "- Private IP: $LOCAL_IP",
            "- Launch Time: $(date)\"",
            "",
            "# Create instance info file",
            "cat > /root/instance-info.txt << EOF",
            "=== AlmaLinux ASG Instance ===",
            "Instance ID: $INSTANCE_ID",
            "Instance Type: $INSTANCE_TYPE",
            "Lifecycle: $INSTANCE_LIFECYCLE",
            "Region: $REGION",
            "Availability Zone: $AZ",
            "Private IP: $LOCAL_IP",
            "Launched: $(date)",
            "",
            "=== Auto-Recovery ===",
            "This instance is managed by an Auto Scaling Group.",
            "If terminated, a replacement will launch automatically.",
            "Preference: Spot instances with on-demand fallback",
            "",
            "=== Access ===",
            "SSM: aws ssm start-session --target $INSTANCE_ID",
            "EOF",
            "",
            "# Create spot interruption monitoring script",
            "cat > /usr/local/bin/spot-monitor.sh << 'EOFSCRIPT'",
            "#!/bin/bash",
            "TOKEN=$(curl -s -X PUT 'http://169.254.169.254/latest/api/token' -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600')",
            "INTERRUPTION=$(curl -s -H \"X-aws-ec2-metadata-token: $TOKEN\" http://169.254.169.254/latest/meta-data/spot/instance-action 2>/dev/null)",
            "",
            "if [ -n \"$INTERRUPTION\" ] && [ \"$INTERRUPTION\" != \"\" ]; then",
            "    INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)",
            "    INSTANCE_TYPE=$(curl -s http://169.254.169.254/latest/meta-data/instance-type)",
            "    ",
            f"    aws sns publish --region {region} \\",
            f"        --topic-arn {self.notification_topic.topic_arn} \\",
            "        --subject \"⚠️ AlmaLinux ASG: Spot Interruption Warning\" \\",
            "        --message \"Spot instance interruption detected!",
            "",
            "Instance: $INSTANCE_ID",
            "Type: $INSTANCE_TYPE",
            "Action: $INTERRUPTION",
            "Time: $(date)",
            "",
            "ASG will automatically launch a replacement instance.\"",
            "    ",
            "    echo \"[$(date)] Spot interruption detected: $INTERRUPTION\" >> /var/log/spot-interruption.log",
            "fi",
            "EOFSCRIPT",
            "",
            "chmod +x /usr/local/bin/spot-monitor.sh",
            "",
            "# Run spot monitor every minute",
            "echo '* * * * * /usr/local/bin/spot-monitor.sh' | crontab -",
            "",
            "echo '=== Setup Complete at $(date) ==='",
        )
        
        # Get key name from configuration
        key_name = getattr(self.infra_config.ec2, 'key_name', None) if hasattr(self.infra_config, 'ec2') else None
        
        # Create launch template (base configuration, no spot settings here)
        self.launch_template = ec2.LaunchTemplate(
            self,
            "AlmaASGLaunchTemplate",
            launch_template_name=f"AlmaASG-{self.account_name}-Template",
            
            # Instance configuration - will be overridden by mixed instances policy
            instance_type=ec2.InstanceType("m5.large"),  # Default, overridden below
            machine_image=machine_image,
            
            # Networking
            security_group=self.security_group,
            
            # IAM
            role=self.instance_role,
            
            # Storage - from configuration
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=20,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        iops=3000,
                        throughput=125,
                        delete_on_termination=True,
                        encrypted=True,
                    )
                )
            ],
            
            # User data
            user_data=user_data,
            
            # SSH key if configured
            key_pair=ec2.KeyPair.from_key_pair_name(
                self, 
                "AlmaASGKeyPair", 
                key_name
            ) if key_name else None,
            
            # Enable detailed monitoring
            detailed_monitoring=True,
            
            # Require IMDSv2
            require_imdsv2=True,
        )
    
    def create_auto_scaling_group(self):
        """Create ASG with mixed instances (spot preferred, on-demand fallback)"""
        
        # Get ASG configuration
        if not self.infra_config.compute or not self.infra_config.compute.asg:
            raise ValueError("ASG configuration not found in infrastructure.yaml")
        
        asg_config = self.infra_config.compute.asg
        
        # Build instance type overrides from configuration
        instance_overrides = [
            # Primary instance type
            autoscaling.LaunchTemplateOverrides(
                instance_type=ec2.InstanceType(asg_config.primary_instance_type)
            ),
        ]
        
        # Add alternative instance types from configuration
        for alt_type in asg_config.alternative_instance_types:
            instance_overrides.append(
                autoscaling.LaunchTemplateOverrides(
                    instance_type=ec2.InstanceType(alt_type)
                )
            )
        
        # Create ASG with mixed instances policy
        self.asg = autoscaling.AutoScalingGroup(
            self,
            "AlmaAutoScalingGroup",
            auto_scaling_group_name=f"AlmaASG-{self.account_name}",
            
            # Mixed instances policy - spot preferred, on-demand fallback
            mixed_instances_policy=autoscaling.MixedInstancesPolicy(
                launch_template=self.launch_template,
                launch_template_overrides=instance_overrides,
                instances_distribution=autoscaling.InstancesDistribution(
                    on_demand_base_capacity=0,
                    on_demand_percentage_above_base_capacity=asg_config.on_demand_percentage,
                    spot_allocation_strategy=autoscaling.SpotAllocationStrategy.PRICE_CAPACITY_OPTIMIZED,
                    spot_instance_pools=len(instance_overrides),
                ),
            ),
            
            # Network configuration
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            
            # Capacity configuration from infrastructure.yaml
            min_capacity=asg_config.min_capacity,
            max_capacity=asg_config.max_capacity,
            desired_capacity=asg_config.desired_capacity,
            
            # Health check with configured grace period
            health_check=autoscaling.HealthCheck.ec2(
                grace=Duration.seconds(asg_config.health_check_grace_period)
            ),
            
            # Update policy
            update_policy=autoscaling.UpdatePolicy.rolling_update(
                max_batch_size=1,
                min_instances_in_service=0,
                pause_time=Duration.seconds(300),
            ),
            
            # Termination policies
            termination_policies=[
                autoscaling.TerminationPolicy.OLDEST_INSTANCE,
            ],
            
            # Enable metrics
            group_metrics=[autoscaling.GroupMetrics.all()],
            
            # Notifications for ALL events
            notifications=[
                autoscaling.NotificationConfiguration(
                    topic=self.notification_topic,
                    scaling_events=autoscaling.ScalingEvents.ALL,
                )
            ],
        )
        
        # Add tags
        Tags.of(self.asg).add("Name", f"AlmaASG-{self.account_name}")
        Tags.of(self.asg).add("ManagedBy", "AutoScalingGroup")
        Tags.of(self.asg).add("Environment", self.account_name)
    
    def create_cloudwatch_alarms(self):
        """Create CloudWatch alarms for monitoring"""
        
        # Alarm when no healthy instances
        no_instances_alarm = cloudwatch.Alarm(
            self,
            "NoHealthyInstancesAlarm",
            metric=self.asg.metric_group_in_service_instances(
                statistic=cloudwatch.Stats.AVERAGE,
                period=Duration.minutes(1),
            ),
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
            alarm_description="Alert when ASG has no healthy instances",
            alarm_name=f"AlmaASG-{self.account_name}-NoHealthyInstances",
        )
        
        no_instances_alarm.add_alarm_action(
            cw_actions.SnsAction(self.notification_topic)
        )
    
   def create_scheduled_refresh(self):
        """Create Lambda function to automatically refresh instances on schedule"""
        from aws_cdk import (
            aws_lambda as lambda_,
            aws_events as events,
            aws_events_targets as targets,
        )
        import os
        
        asg_config = self.infra_config.compute.asg
        
        # Get path to lambda directory
        lambda_dir = os.path.join(
            os.path.dirname(__file__),
            'lambda'
        )
        
        # Lambda function for instance refresh
        refresh_lambda = lambda_.Function(
            self,
            "ASGRefreshLambda",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="refresh_handler.handler",
            code=lambda_.Code.from_asset(lambda_dir),
            environment={
                'ASG_NAME': self.asg.auto_scaling_group_name,
                'TOPIC_ARN': self.notification_topic.topic_arn,
                'REFRESH_ONLY_ON_DEMAND': 'true' if asg_config.refresh_only_on_demand else 'false',
            },
            timeout=Duration.seconds(60),
            description=f"Scheduled refresh for {self.asg.auto_scaling_group_name}",
        )
        
        # Grant permissions
        refresh_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'autoscaling:DescribeAutoScalingGroups',
                    'autoscaling:StartInstanceRefresh',
                    'ec2:DescribeInstances',
                    'sns:Publish',
                ],
                resources=['*']
            )
        )
        
        # Schedule: Run daily at configured hour
        events.Rule(
            self,
            "DailyRefreshRule",
            rule_name=f"AlmaASG-{self.account_name}-DailyRefresh",
            description=f"Daily instance refresh check for {self.asg.auto_scaling_group_name}",
            schedule=events.Schedule.cron(
                minute='0',
                hour=str(asg_config.refresh_hour),
                month='*',
                week_day='*',
                year='*'
            ),
            targets=[targets.LambdaFunction(refresh_lambda)],
        )
        
        # Output
        CfnOutput(
            self,
            "RefreshSchedule",
            value=f"Daily at {asg_config.refresh_hour}:00 UTC (refresh_only_on_demand: {asg_config.refresh_only_on_demand})",
            description="Automated refresh schedule",
        ) 
    
    def create_outputs(self):
        """Create CloudFormation outputs"""
        
        CfnOutput(
            self,
            "AutoScalingGroupName",
            value=self.asg.auto_scaling_group_name,
            description="Auto Scaling Group name",
            export_name=f"AlmaASG-{self.account_name}-Name",
        )
        
        CfnOutput(
            self,
            "LaunchTemplateName",
            value=self.launch_template.launch_template_name,
            description="Launch Template name",
        )
        
        CfnOutput(
            self,
            "NotificationTopicArn",
            value=self.notification_topic.topic_arn,
            description="SNS Topic ARN for notifications",
            export_name=f"AlmaASG-{self.account_name}-TopicArn",
        )
        
        CfnOutput(
            self,
            "GetInstanceCommand",
            value=f"aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names {self.asg.auto_scaling_group_name} --query 'AutoScalingGroups[0].Instances[0].[InstanceId,InstanceType,LifecycleState]' --output text",
            description="Command to get current instance details",
        )
        
        CfnOutput(
            self,
            "ConnectCommand",
            value=f"INSTANCE_ID=$(aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names {self.asg.auto_scaling_group_name} --query 'AutoScalingGroups[0].Instances[0].InstanceId' --output text) && aws ssm start-session --target $INSTANCE_ID",
            description="One-liner to connect via SSM",
        )
        
        CfnOutput(
            self,
            "InstanceStrategy",
            value=f"{100 - asg_config.on_demand_percentage}% spot (preferred) / {asg_config.on_demand_percentage}% on-demand (fallback)",
            description="Instance allocation strategy",
        )
        
        CfnOutput(
            self,
            "InstanceTypes",
            value=f"Primary: {asg_config.primary_instance_type}, Alternatives: {', '.join(asg_config.alternative_instance_types)}",
            description="Configured instance types",
        )
        
        CfnOutput(
            self,
            "NotificationInfo",
            value="SNS notifications sent for: launches, terminations, spot interruptions, and failures",
            description="Notification configuration",
        )
