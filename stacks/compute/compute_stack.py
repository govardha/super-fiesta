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

    def import_vpc(self):
        """Import VPC from SimpleNetwork stack using cross-stack references"""

        vpc_id = Fn.import_value(f"{self.network_stack_name}-{self.account_name}-VpcId")
        vpc_cidr = Fn.import_value(
            f"{self.network_stack_name}-{self.account_name}-VpcCidr"
        )

        # For subnet selection, we'll just use the VPC's default subnet selection
        # This is simpler and avoids token issues
        self.vpc = ec2.Vpc.from_vpc_attributes(
            self,
            "ImportedVpc",
            vpc_id=vpc_id,
            availability_zones=["us-east-1a", "us-east-1b"],  # Hardcode for now
        )

        self.vpc_cidr = vpc_cidr

    def create_compute_instances(self):
        """Create compute instances based on configuration"""

        self.instances = []

        for instance_config in self.infra_config.compute.instances:
            instance = self.create_single_instance(instance_config)
            self.instances.append(instance)

    def create_single_instance(self, config: ComputeInstanceConfig) -> ec2.Instance:
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

        # EBS volume configuration
        block_device_config = {
            "device_name": "/dev/sda1",  # Standard for most Linux AMIs
            "volume": ec2.BlockDeviceVolume.ebs(
                volume_size=config.ebs_volume_size,
                volume_type=self.get_ebs_volume_type(config.ebs_volume_type),
                delete_on_termination=True,
                encrypted=True,
            ),
        }

        # Add IOPS if specified (for GP3, IO1, IO2)
        if config.ebs_iops and config.ebs_volume_type in ["GP3", "IO1", "IO2"]:
            block_device_config["volume"] = ec2.BlockDeviceVolume.ebs(
                volume_size=config.ebs_volume_size,
                volume_type=self.get_ebs_volume_type(config.ebs_volume_type),
                iops=config.ebs_iops,
                throughput=config.ebs_throughput
                if config.ebs_volume_type == "GP3"
                else None,
                delete_on_termination=True,
                encrypted=True,
            )

        # Create instance
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
            block_devices=[ec2.BlockDevice(**block_device_config)],
        )

        return instance

    def create_user_data_script(self, config: ComputeInstanceConfig) -> ec2.UserData:
        """Create minimal user data script - just basics, no Tailscale"""

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
            "# Create README",
            "cat > /root/README.md << 'EOF'",
            f"# {config.name} - AlmaLinux {config.os_version}",
            "",
            "## Instance Details:",
            f"- Instance Type: {config.instance_type}",
            f"- OS: AlmaLinux {config.os_version} x86_64",
            f"- EBS Volume: {config.ebs_volume_size}GB {config.ebs_volume_type}",
            f"- Subnet: {config.subnet_type}",
            "",
            "## Access:",
            "- SSM: aws ssm start-session --target $(ec2-metadata --instance-id | cut -d' ' -f2)",
            "",
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
            "df -h /",
            "",
            "# Check OS info",
            "cat /etc/os-release",
            "```",
            "EOF",
            "",
            "chmod 644 /root/README.md",
        ]

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
                value=f"{config.instance_type} | {config.ebs_volume_size}GB {config.ebs_volume_type} | AlmaLinux {config.os_version}",
                description=f"{config.name} configuration",
            )

        CfnOutput(
            self,
            "TotalInstances",
            value=str(len(self.instances)),
            description="Total number of compute instances created",
        )
