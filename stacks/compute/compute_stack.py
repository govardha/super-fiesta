# File: stacks/compute/compute_stack.py

import os

from aws_cdk import (
    CfnOutput,
    Fn,
    Stack,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_iam as iam,
)
from cdk_ec2_spot_simple import SpotInstance

from configs.config import AppConfigs
from configs.models import ComputeInstanceConfig, InfrastructureSpec
from constructs import Construct


class ComputeStack(Stack):
    """
    Compute Stack for AlmaLinux instances
    - Uses existing SimpleNetwork VPC passed as parameter
    - Creates AlmaLinux instances with customizable specs
    - SSM-only access (no SSH)
    - Configurable EBS volumes
    - Persistent data volumes
    - Spot instance support
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,  # VPC passed from network stack
        account_name: str = "sandbox",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Load configuration
        self.config_loader = AppConfigs()
        self.infra_config: InfrastructureSpec = (
            self.config_loader.get_infrastructure_info(account_name)
        )
        self.account_name = account_name

        # Use the VPC passed from network stack
        self.vpc = vpc
        self.vpc_cidr = vpc.vpc_cidr_block

        # Create compute instances
        if self.infra_config.compute and self.infra_config.compute.instances:
            self.create_compute_instances()

        # Create outputs
        self.create_outputs()

    def create_compute_instances(self):
        """Create compute instances based on configuration"""

        self.instances = []

        for instance_config in self.infra_config.compute.instances:
            instance = self.create_single_instance(instance_config)
            self.instances.append(instance)

    def create_single_instance(self, config: ComputeInstanceConfig):
        """Create a single compute instance"""

        # Get AMI based on OS configuration
        ami_id = self.get_ami_id(config.os, config.os_version)

        machine_image = ec2.MachineImage.generic_linux(
            {self.infra_config.region: ami_id}
        )

        # Security Group
        sg = ec2.SecurityGroup(
            self,
            f"{config.name}SecurityGroup",
            vpc=self.vpc,
            description=f"Security group for {config.name}",
            allow_all_outbound=True,
        )

        # Allow traffic from within VPC (for SSM, etc.)
        sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc_cidr),
            connection=ec2.Port.all_traffic(),
            description="Allow all traffic from VPC CIDR",
        )

        # IAM Role for instance
        role = iam.Role(
            self,
            f"{config.name}Role",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                ),
            ],
            inline_policies={
                f"{config.name}Policy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "ec2:DescribeInstances",
                                "ec2:DescribeVpcs",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                            ],
                            resources=["*"],
                        )
                    ]
                )
            },
        )

        # User data script
        user_data_script = self.create_user_data_script(config)

        # Determine subnet type
        if config.subnet_type == "PUBLIC":
            subnet_selection = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
        else:
            subnet_selection = ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            )

        # Parse instance type directly (no abstraction)
        instance_type = ec2.InstanceType(config.instance_type)

        # Root EBS volume configuration (for OS)
        block_devices = [
            ec2.BlockDevice(
                device_name="/dev/sda1",  # Root device
                volume=ec2.BlockDeviceVolume.ebs(
                    volume_size=config.ebs_volume_size,
                    volume_type=self.get_ebs_volume_type(config.ebs_volume_type),
                    delete_on_termination=True,
                    encrypted=True,
                    iops=config.ebs_iops if config.ebs_iops else None,
                    throughput=config.ebs_throughput
                    if config.ebs_volume_type == "GP3" and config.ebs_throughput
                    else None,
                ),
            )
        ]

        # Add separate data volume if configured
        if config.data_volume_size:
            block_devices.append(
                ec2.BlockDevice(
                    device_name=config.data_volume_device_name,
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=config.data_volume_size,
                        volume_type=self.get_ebs_volume_type(config.data_volume_type),
                        delete_on_termination=False,  # Persist data volume
                        encrypted=True,
                    ),
                )
            )

        # Create instance based on spot or on-demand
        if config.use_spot:
            # Build spot options
            spot_options = {}
            if config.spot_max_price:
                spot_options["maxPrice"] = float(config.spot_max_price)

            # Use SpotInstance construct for spot instances
            instance = SpotInstance(
                self,
                config.name,
                instance_type=instance_type,
                machine_image=machine_image,
                vpc=self.vpc,
                vpc_subnets=subnet_selection,
                security_group=sg,
                role=role,
                user_data=user_data_script,
                block_devices=block_devices,
                spot_options=spot_options if spot_options else None,
            )
        else:
            # Regular on-demand instance
            instance = ec2.Instance(
                self,
                config.name,
                instance_name=config.name,
                instance_type=instance_type,
                machine_image=machine_image,
                vpc=self.vpc,
                vpc_subnets=subnet_selection,
                security_group=sg,
                role=role,
                user_data=user_data_script,
                block_devices=block_devices,
            )

        return instance

    def create_user_data_script(self, config: ComputeInstanceConfig) -> ec2.UserData:
        """Create minimal user data script - just basics"""

        user_data = ec2.UserData.for_linux()

        commands = [
            "#!/bin/bash",
            "set -e",
            "",
            "# Update system",
            "dnf update -y",
            "",
            "# Install basic tools",
            "dnf install -y wget curl vim htop tmux git",
            "",
            "# SSM Agent should already be installed and running on AlmaLinux AMIs",
            "# Just verify it's enabled",
            "systemctl enable amazon-ssm-agent || true",
            "systemctl start amazon-ssm-agent || true",
            "",
        ]

        # Add data volume mounting if configured
        if config.data_volume_size:
            commands.extend(
                [
                    "# Mount data volume",
                    f"DEVICE={config.data_volume_device_name}",
                    f"MOUNT_POINT={config.data_volume_mount_point}",
                    "",
                    "# Wait for device to be available",
                    "while [ ! -e $DEVICE ]; do sleep 1; done",
                    "",
                    "# Check if filesystem exists, if not create it",
                    "if ! blkid $DEVICE; then",
                    "  echo 'Creating filesystem on data volume...'",
                    "  mkfs -t xfs $DEVICE",
                    "fi",
                    "",
                    "# Create mount point",
                    "mkdir -p $MOUNT_POINT",
                    "",
                    "# Get UUID of the device",
                    "UUID=$(blkid -s UUID -o value $DEVICE)",
                    "",
                    "# Add to fstab if not already there",
                    "if ! grep -q $UUID /etc/fstab; then",
                    '  echo "UUID=$UUID $MOUNT_POINT xfs defaults,nofail 0 2" >> /etc/fstab',
                    "fi",
                    "",
                    "# Mount the volume",
                    "mount -a",
                    "",
                    "# Set permissions",
                    "chmod 755 $MOUNT_POINT",
                    "",
                ]
            )

        commands.extend(
            [
                "# Create README",
                "cat > /root/README.md << 'EOF'",
                f"# {config.name} - AlmaLinux {config.os_version}",
                "",
                "## Instance Details:",
                f"- Instance Type: {config.instance_type}",
                f"- OS: AlmaLinux {config.os_version} x86_64",
                f"- Root Volume: {config.ebs_volume_size}GB {config.ebs_volume_type}",
            ]
        )

        if config.data_volume_size:
            commands.extend(
                [
                    f"- Data Volume: {config.data_volume_size}GB {config.data_volume_type} (mounted at {config.data_volume_mount_point})",
                    f"- Data Persistence: YES - survives instance replacement",
                ]
            )

        commands.extend(
            [
                f"- Subnet: {config.subnet_type}",
                f"- Spot Instance: {'Yes' if config.use_spot else 'No'}",
                "",
                "## Access:",
                "- SSM: aws ssm start-session --target $(ec2-metadata --instance-id | cut -d' ' -f2)",
                "",
            ]
        )

        if config.data_volume_size:
            commands.extend(
                [
                    "## Data Volume:",
                    f"- Mounted at: {config.data_volume_mount_point}",
                    f"- Store your persistent data here (survives instance replacement)",
                    "- Check usage: df -h",
                    "",
                ]
            )

        commands.extend(
            [
                "## Networking:",
                "- Uses SimpleNetwork VPC with fck-nat for internet access",
                "- Cost-effective NAT (~$3/month vs $45/month for AWS NAT Gateway)",
                "",
                "## Verification:",
                "```bash",
                "# Check internet connectivity",
                "curl -s http://checkip.amazonaws.com/",
                "",
                "# Check SSM agent status",
                "systemctl status amazon-ssm-agent",
                "",
                "# Check disk space",
                "df -h",
                "",
            ]
        )

        if config.data_volume_size:
            commands.extend(
                [
                    "# Check data volume",
                    f"ls -la {config.data_volume_mount_point}",
                    "",
                ]
            )

        commands.extend(
            [
                "# Check OS info",
                "cat /etc/os-release",
                "```",
                "EOF",
                "",
                "chmod 644 /root/README.md",
            ]
        )

        user_data.add_commands(*commands)
        return user_data

    def get_ami_id(self, os: str, os_version: str) -> str:
        """Get AMI ID based on OS and version"""

        if os.lower() == "almalinux":
            region = self.infra_config.region
            if region in self.infra_config.compute.almalinux_amis:
                if os_version in self.infra_config.compute.almalinux_amis[region]:
                    return self.infra_config.compute.almalinux_amis[region][os_version]

            raise ValueError(
                f"AlmaLinux {os_version} AMI not found for region {region}. "
                f"Please add it to infrastructure.yaml under compute.almalinux_amis"
            )

        raise ValueError(
            f"Unsupported OS: {os}. Currently only 'almalinux' is supported."
        )

    def get_ebs_volume_type(self, volume_type_str: str) -> ec2.EbsDeviceVolumeType:
        """Convert string to EBS volume type enum"""

        mapping = {
            "GP2": ec2.EbsDeviceVolumeType.GP2,
            "GP3": ec2.EbsDeviceVolumeType.GP3,
            "IO1": ec2.EbsDeviceVolumeType.IO1,
            "IO2": ec2.EbsDeviceVolumeType.IO2,
            "ST1": ec2.EbsDeviceVolumeType.ST1,
            "SC1": ec2.EbsDeviceVolumeType.SC1,
        }

        return mapping.get(volume_type_str.upper(), ec2.EbsDeviceVolumeType.GP3)

    def create_outputs(self):
        """Create CloudFormation outputs"""

        if not hasattr(self, "instances") or not self.instances:
            CfnOutput(
                self,
                "NoInstancesCreated",
                value="No compute instances configured",
                description="Compute stack status",
            )
            return

        # Output instance IDs and SSM commands
        for i, instance in enumerate(self.instances):
            config = self.infra_config.compute.instances[i]

            CfnOutput(
                self,
                f"{config.name}InstanceId",
                value=instance.instance_id,
                description=f"{config.name} Instance ID",
            )

            CfnOutput(
                self,
                f"{config.name}PrivateIP",
                value=instance.instance_private_ip,
                description=f"{config.name} Private IP",
            )

            CfnOutput(
                self,
                f"{config.name}SSMCommand",
                value=f"aws ssm start-session --target {instance.instance_id}",
                description=f"SSM command to connect to {config.name}",
            )

            CfnOutput(
                self,
                f"{config.name}Details",
                value=f"{config.instance_type} | {config.ebs_volume_size}GB {config.ebs_volume_type} | AlmaLinux {config.os_version} | {'SPOT' if config.use_spot else 'ON-DEMAND'}",
                description=f"{config.name} configuration",
            )

        CfnOutput(
            self,
            "TotalInstances",
            value=str(len(self.instances)),
            description="Total number of compute instances created",
        )
