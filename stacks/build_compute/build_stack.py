"""
Build compute stack — ephemeral high-performance instances for Python builds.

Reuses SimpleNetworkStack VPC (lego-block pattern).
Parameterized by cpu_arch to create either x86 or ARM instances.
UserData lives in userdata/build_setup.sh — edit once, both stacks get it.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from constructs import Construct

from configs.config import AppConfigs
from configs.models import InfrastructureSpec


class BuildStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,
        cpu_arch: str,  # "x86_64" or "arm_64"
        account_name: str = "sandbox",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        config_loader = AppConfigs()
        infra: InfrastructureSpec = config_loader.get_infrastructure_info(account_name)
        build_cfg = infra.build_compute

        # --- Instance type based on arch ---
        if cpu_arch == "arm_64":
            instance_type = ec2.InstanceType(build_cfg.arm_instance_type)
            machine_image = ec2.MachineImage.latest_amazon_linux2023(
                cpu_type=ec2.AmazonLinuxCpuType.ARM_64
            )
        else:
            instance_type = ec2.InstanceType(build_cfg.x86_instance_type)
            machine_image = ec2.MachineImage.latest_amazon_linux2023(
                cpu_type=ec2.AmazonLinuxCpuType.X86_64
            )

        # --- Security group: egress-only (HTTP/HTTPS out, no inbound) ---
        sg = ec2.SecurityGroup(
            self,
            "BuildSG",
            vpc=vpc,
            description=f"Build instance SG ({cpu_arch}) - egress only",
            allow_all_outbound=False,
        )
        sg.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS out")
        sg.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "HTTP out")
        sg.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.udp(53), "DNS out")
        sg.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(53), "DNS out (TCP)")

        # --- IAM role: SSM + scoped S3 access ---
        role = iam.Role(
            self,
            "BuildRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                ),
            ],
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
                resources=[
                    build_cfg.s3_bucket_arn,
                    f"{build_cfg.s3_bucket_arn}/{build_cfg.s3_prefix}/*",
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{Stack.of(self).region}:{Stack.of(self).account}:parameter/notify/gh-pat",
                ],
            )
        )

        # --- UserData from shared script ---
        user_data = ec2.UserData.for_linux()
        script_path = Path(__file__).parent / "userdata" / "build_setup.sh"
        user_data.add_commands(script_path.read_text())

        # --- Instance ---
        instance = ec2.Instance(
            self,
            "BuildInstance",
            instance_name=f"build-{cpu_arch.replace('_', '-')}-{account_name}",
            instance_type=instance_type,
            machine_image=machine_image,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_group=sg,
            role=role,
            user_data=user_data,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=build_cfg.ebs_volume_size,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        delete_on_termination=True,
                        encrypted=True,
                    ),
                )
            ],
        )

        # --- Outputs ---
        CfnOutput(
            self,
            "InstanceId",
            value=instance.instance_id,
            description=f"Build instance ID ({cpu_arch})",
        )
        CfnOutput(
            self,
            "SSMCommand",
            value=f"aws ssm start-session --target {instance.instance_id}",
            description="Connect via SSM",
        )
