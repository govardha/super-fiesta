from aws_cdk import (
    CfnOutput,
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
)
from constructs import Construct

from configs.config import AppConfigs
from configs.models import InfrastructureSpec
from stacks.opnsense_lab.network_stack import OpnsenseLabNetworkStack


class OpnsenseLabComputeStack(Stack):
    """
    OPNsense Lab compute: OPNsense firewall (dual ENI) + private AlmaLinux EC2.

    Depends on OpnsenseLabNetworkStack for VPC and subnets.
    """

    def __init__(self, scope: Construct, construct_id: str, network: OpnsenseLabNetworkStack,
                 account_name: str = "sandbox", **kwargs) -> None:
        kwargs.setdefault("stack_name", "SandboxDeploy-OpnsenseLabCompute")
        super().__init__(scope, construct_id, **kwargs)

        config_loader = AppConfigs()
        infra: InfrastructureSpec = config_loader.get_infrastructure_info(account_name)
        lab = infra.opnsense_lab
        region = infra.region

        vpc = network.vpc
        public_subnet = network.public_subnet
        private_subnet = network.private_subnet

        # --- Security Groups ---
        wan_sg = ec2.SecurityGroup(self, "WanSG", vpc=vpc, description="OPNsense WAN", allow_all_outbound=True)
        wan_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(22), "SSH")
        wan_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS Web GUI")
        wan_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(8443), "HTTPS Web GUI alt")

        lan_sg = ec2.SecurityGroup(self, "LanSG", vpc=vpc, description="OPNsense LAN", allow_all_outbound=True)
        lan_sg.add_ingress_rule(ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.all_traffic(), "All from VPC")

        # --- WAN ENI (public subnet) ---
        wan_eni = ec2.CfnNetworkInterface(
            self, "OpnsenseWanENI",
            subnet_id=public_subnet.subnet_id,
            group_set=[wan_sg.security_group_id],
            source_dest_check=False,
            description="OPNsense WAN interface",
        )

        # --- LAN ENI (private subnet) ---
        lan_eni = ec2.CfnNetworkInterface(
            self, "OpnsenseLanENI",
            subnet_id=private_subnet.subnet_id,
            group_set=[lan_sg.security_group_id],
            source_dest_check=False,
            description="OPNsense LAN interface",
        )

        # --- OPNsense EC2 with WAN ENI only (attach LAN after serial console config) ---
        opnsense_instance = ec2.CfnInstance(
            self, "OpnsenseInstance",
            instance_type=lab.opnsense_instance_type,
            image_id=lab.opnsense_ami,
            key_name=lab.key_pair_name,
            network_interfaces=[
                ec2.CfnInstance.NetworkInterfaceProperty(device_index="0", network_interface_id=wan_eni.ref),
            ],
            tags=[{"key": "Name", "value": f"OpnsenseLab-fw-{account_name}"}],
        )

        # --- EIP for OPNsense WAN ENI ---
        eip = ec2.CfnEIP(self, "OpnsenseEIP")
        ec2.CfnEIPAssociation(self, "OpnsenseEIPAssoc", allocation_id=eip.attr_allocation_id, network_interface_id=wan_eni.ref)

        # --- Private subnet route: 0.0.0.0/0 → OPNsense LAN ENI ---
        ec2.CfnRoute(
            self, "PrivateDefaultRoute",
            route_table_id=private_subnet.route_table.route_table_id,
            destination_cidr_block="0.0.0.0/0",
            network_interface_id=lan_eni.ref,
        )

        # --- AlmaLinux EC2 in private subnet ---
        instance_sg = ec2.SecurityGroup(self, "InstanceSG", vpc=vpc, description="AlmaLinux instance", allow_all_outbound=True)
        instance_sg.add_ingress_rule(ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.all_traffic(), "VPC internal")

        role = iam.Role(
            self, "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")],
        )

        alma_ami_id = infra.compute.almalinux_amis.get(region, {}).get(lab.os_version)
        if not alma_ami_id:
            raise ValueError(f"AlmaLinux {lab.os_version} AMI not found for {region}")

        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "#!/bin/bash", "set -e",
            "dnf update -y",
            "dnf install -y curl vim htop tmux",
            "systemctl enable amazon-ssm-agent || true",
            "systemctl start amazon-ssm-agent || true",
        )

        self.alma_instance = ec2.Instance(
            self, "AlmaLinuxInstance",
            instance_name=f"OpnsenseLab-alma-{account_name}",
            instance_type=ec2.InstanceType(lab.instance_type),
            machine_image=ec2.MachineImage.generic_linux({region: alma_ami_id}),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnets=[private_subnet]),
            security_group=instance_sg,
            role=role,
            user_data=user_data,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",
                    volume=ec2.BlockDeviceVolume.ebs(volume_size=lab.ebs_volume_size, volume_type=ec2.EbsDeviceVolumeType.GP3,
                                                     delete_on_termination=True, encrypted=True),
                )
            ],
        )

        # --- Outputs ---
        CfnOutput(self, "VpcId", value=vpc.vpc_id)
        CfnOutput(self, "OpnsenseInstanceId", value=opnsense_instance.ref)
        CfnOutput(self, "OpnsenseLanEniId", value=lan_eni.ref, description="Attach this ENI to OPNsense as device index 1 after boot")
        CfnOutput(self, "OpnsensePublicIP", value=eip.attr_public_ip, description="OPNsense public IP for Web GUI and SSH")
        CfnOutput(self, "AttachLanCmd", value=f"aws ec2 attach-network-interface --instance-id INSTANCE_ID --network-interface-id {lan_eni.ref} --device-index 1 --region {region}",
                  description="Run after OPNsense is up to attach LAN ENI")
        CfnOutput(self, "OpnsenseWebGUI", value=f"https://{eip.attr_public_ip}:443", description="OPNsense Web GUI (default: root/opnsense)")
        CfnOutput(self, "OpnsenseSSH", value=f"ssh root@{eip.attr_public_ip}", description="SSH to OPNsense")
        CfnOutput(self, "AlmaInstanceId", value=self.alma_instance.instance_id)
        CfnOutput(self, "AlmaSSMCommand", value=f"aws ssm start-session --target {self.alma_instance.instance_id}")
        CfnOutput(self, "KeyPairImportCmd", value=f"aws ec2 import-key-pair --key-name {lab.key_pair_name} --public-key-material fileb://$HOME/.ssh/id_ed25519.pub --region {region}",
                  description="Run this BEFORE deploying if key pair doesn't exist yet")
