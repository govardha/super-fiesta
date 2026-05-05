from aws_cdk import (
    CfnOutput,
    Stack,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_iam as iam,
)
from constructs import Construct

from configs.config import AppConfigs
from configs.models import InfrastructureSpec


class OpnsenseLabStack(Stack):
    """
    OPNsense Lab: VPC with OPNsense firewall (dual ENI) + private AlmaLinux EC2.

    Architecture:
      Internet → IGW → [Public Subnet: OPNsense WAN ENI + EIP]
                        [Private Subnet: OPNsense LAN ENI ← AlmaLinux EC2]
      Private route table: 0.0.0.0/0 → OPNsense LAN ENI
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        account_name: str = "sandbox",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        config_loader = AppConfigs()
        infra: InfrastructureSpec = config_loader.get_infrastructure_info(account_name)
        lab = infra.opnsense_lab
        region = infra.region

        # --- VPC: public + private isolated, 0 NAT (OPNsense IS the NAT) ---
        self.vpc = ec2.Vpc(
            self,
            "OpnsenseLabVpc",
            vpc_name=f"OpnsenseLab-{account_name}",
            ip_addresses=ec2.IpAddresses.cidr(lab.vpc.cidr),
            max_azs=1,  # Single AZ for lab simplicity
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=lab.vpc.subnet_mask,
                ),
                ec2.SubnetConfiguration(
                    name="PrivateIsolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=lab.vpc.subnet_mask,
                ),
            ],
            enable_dns_hostnames=True,
            enable_dns_support=True,
        )

        public_subnet = self.vpc.public_subnets[0]
        private_subnet = self.vpc.isolated_subnets[0]

        # --- Security Groups ---

        # WAN SG: allow SSH, HTTPS (web GUI), 8443 from anywhere (lock down later)
        wan_sg = ec2.SecurityGroup(
            self,
            "WanSG",
            vpc=self.vpc,
            description="OPNsense WAN",
            allow_all_outbound=True,
        )
        wan_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(22), "SSH")
        wan_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS Web GUI")
        wan_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.tcp(8443), "HTTPS Web GUI alt"
        )

        # LAN SG: allow all from VPC
        lan_sg = ec2.SecurityGroup(
            self,
            "LanSG",
            vpc=self.vpc,
            description="OPNsense LAN",
            allow_all_outbound=True,
        )
        lan_sg.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            ec2.Port.all_traffic(),
            "All from VPC",
        )

        # --- WAN ENI (public subnet, primary interface) ---
        wan_eni = ec2.CfnNetworkInterface(
            self,
            "OpnsenseWanENI",
            subnet_id=public_subnet.subnet_id,
            group_set=[wan_sg.security_group_id],
            source_dest_check=False,
            description="OPNsense WAN interface",
        )

        # --- LAN ENI (private subnet) ---
        lan_eni = ec2.CfnNetworkInterface(
            self,
            "OpnsenseLanENI",
            subnet_id=private_subnet.subnet_id,
            group_set=[lan_sg.security_group_id],
            source_dest_check=False,
            description="OPNsense LAN interface",
        )

        # --- OPNsense EC2 with explicit ENI attachments ---
        opnsense_instance = ec2.CfnInstance(
            self,
            "OpnsenseInstance",
            instance_type=lab.opnsense_instance_type,
            image_id=lab.opnsense_ami,
            key_name=lab.key_pair_name,
            network_interfaces=[
                ec2.CfnInstance.NetworkInterfaceProperty(
                    device_index="0",
                    network_interface_id=wan_eni.ref,
                ),
                ec2.CfnInstance.NetworkInterfaceProperty(
                    device_index="1",
                    network_interface_id=lan_eni.ref,
                ),
            ],
            block_device_mappings=[
                ec2.CfnInstance.BlockDeviceMappingProperty(
                    device_name="/dev/sda1",
                    ebs=ec2.CfnInstance.EbsProperty(
                        volume_size=8, volume_type="gp3", delete_on_termination=True
                    ),
                )
            ],
            tags=[{"key": "Name", "value": f"OpnsenseLab-fw-{account_name}"}],
        )

        # --- EIP for OPNsense WAN ENI ---
        eip = ec2.CfnEIP(self, "OpnsenseEIP")
        ec2.CfnEIPAssociation(
            self,
            "OpnsenseEIPAssoc",
            allocation_id=eip.attr_allocation_id,
            network_interface_id=wan_eni.ref,
        )

        # --- Private subnet route table: 0.0.0.0/0 → OPNsense LAN ENI ---
        for rt_assoc in private_subnet.node.children:
            if hasattr(rt_assoc, "route_table_id"):
                break

        private_rt = ec2.CfnRoute(
            self,
            "PrivateDefaultRoute",
            route_table_id=private_subnet.route_table.route_table_id,
            destination_cidr_block="0.0.0.0/0",
            network_interface_id=lan_eni.ref,
        )

        # --- SSM VPC endpoints (AlmaLinux needs SSM, no internet path yet until OPNsense configured) ---
        endpoint_sg = ec2.SecurityGroup(
            self,
            "EndpointSG",
            vpc=self.vpc,
            description="SSM VPC Endpoints",
            allow_all_outbound=False,
        )
        endpoint_sg.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block), ec2.Port.tcp(443), "HTTPS from VPC"
        )

        for svc_name, svc in [
            ("ssm", ec2.InterfaceVpcEndpointAwsService.SSM),
            ("ssm-messages", ec2.InterfaceVpcEndpointAwsService.SSM_MESSAGES),
            ("ec2-messages", ec2.InterfaceVpcEndpointAwsService.EC2_MESSAGES),
        ]:
            ec2.InterfaceVpcEndpoint(
                self,
                f"{svc_name}-endpoint",
                vpc=self.vpc,
                service=svc,
                security_groups=[endpoint_sg],
                private_dns_enabled=True,
                subnets=ec2.SubnetSelection(subnets=[private_subnet]),
            )

        # --- AlmaLinux EC2 in private subnet ---
        instance_sg = ec2.SecurityGroup(
            self,
            "InstanceSG",
            vpc=self.vpc,
            description="AlmaLinux instance",
            allow_all_outbound=True,
        )
        instance_sg.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            ec2.Port.all_traffic(),
            "VPC internal",
        )

        role = iam.Role(
            self,
            "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                )
            ],
        )

        alma_ami_id = infra.compute.almalinux_amis.get(region, {}).get(lab.os_version)
        if not alma_ami_id:
            raise ValueError(f"AlmaLinux {lab.os_version} AMI not found for {region}")

        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "#!/bin/bash",
            "set -e",
            "dnf update -y",
            "dnf install -y curl vim htop tmux",
            "systemctl enable amazon-ssm-agent || true",
            "systemctl start amazon-ssm-agent || true",
        )

        self.alma_instance = ec2.Instance(
            self,
            "AlmaLinuxInstance",
            instance_name=f"OpnsenseLab-alma-{account_name}",
            instance_type=ec2.InstanceType(lab.instance_type),
            machine_image=ec2.MachineImage.generic_linux({region: alma_ami_id}),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnets=[private_subnet]),
            security_group=instance_sg,
            role=role,
            user_data=user_data,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=lab.ebs_volume_size,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        delete_on_termination=True,
                        encrypted=True,
                    ),
                )
            ],
        )

        # --- Outputs ---
        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
        CfnOutput(self, "OpnsenseInstanceId", value=opnsense_instance.ref)
        CfnOutput(
            self,
            "OpnsensePublicIP",
            value=eip.attr_public_ip,
            description="OPNsense public IP for Web GUI and SSH",
        )
        CfnOutput(
            self,
            "OpnsenseWebGUI",
            value=f"https://{eip.attr_public_ip}:443",
            description="OPNsense Web GUI (default: root/opnsense)",
        )
        CfnOutput(
            self,
            "OpnsenseSSH",
            value=f"ssh root@{eip.attr_public_ip}",
            description="SSH to OPNsense",
        )
        CfnOutput(self, "AlmaInstanceId", value=self.alma_instance.instance_id)
        CfnOutput(
            self,
            "AlmaSSMCommand",
            value=f"aws ssm start-session --target {self.alma_instance.instance_id}",
        )
        CfnOutput(
            self,
            "KeyPairImportCmd",
            value=f"aws ec2 import-key-pair --key-name {lab.key_pair_name} --public-key-material fileb://$HOME/.ssh/id_ed25519.pub --region {region}",
            description="Run this BEFORE deploying if key pair doesn't exist yet",
        )
