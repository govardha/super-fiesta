# File: stacks/core_network/simple_network_stack.py

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct
from configs.config import AppConfigs
from configs.models import InfrastructureSpec


class SimpleNetworkStack(Stack):
    """
    Simple shared network stack following DDEV pattern:
    - Uses infrastructure.yaml for all configuration
    - Creates VPC with public/private subnets
    - Uses fck-nat following exact DDEV stack pattern
    - Internet Gateway
    - Code and config completely separate
    """
    
    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Load configuration from infrastructure.yaml (same as DDEV stack)
        self.config_loader = AppConfigs()
        self.infra_config: InfrastructureSpec = self.config_loader.get_infrastructure_info(account_name)
        self.account_name = account_name
        
        # Create VPC following DDEV stack pattern
        self.create_vpc()
        
        # Create outputs for cross-stack references
        self.create_outputs()

    def create_vpc(self):
        """Create VPC with fck-nat using exact same pattern as DDEV stack"""
        
        # Get key pair name from configuration (same as DDEV stack)
        key_name = getattr(self.infra_config.ec2, 'key_name', None) if hasattr(self.infra_config, 'ec2') and self.infra_config.ec2 else None
        
        # Create NAT provider using official fck-nat AMI (exact same as DDEV stack)
        nat_provider_config = {
            "instance_type": ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.NANO),
            "machine_image": ec2.LookupMachineImage(
                name="fck-nat-al2023-*-arm64-ebs",
                owners=["568608671756"]  # Official fck-nat AMI owner
            )
        }
        
        # Add key name if configured (same logic as DDEV stack)
        if key_name:
            nat_provider_config["key_name"] = key_name
            
        self.fck_nat_provider = ec2.NatInstanceProviderV2(**nat_provider_config)
        
        # Create VPC using all values from infrastructure.yaml
        self.vpc = ec2.Vpc(
            self,
            "SimpleNetworkVpc",
            vpc_name=f"SimpleNetwork-{self.account_name}",
            ip_addresses=ec2.IpAddresses.cidr(self.infra_config.vpc.cidr),
            max_azs=self.infra_config.vpc.max_azs,
            nat_gateways=1,  # Single NAT for cost optimization
            nat_gateway_provider=self.fck_nat_provider,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name=f"SimpleNetwork-{self.account_name}-Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=self.infra_config.vpc.subnet_mask,
                ),
                ec2.SubnetConfiguration(
                    name=f"SimpleNetwork-{self.account_name}-Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=self.infra_config.vpc.subnet_mask,
                ),
            ],
            enable_dns_hostnames=self.infra_config.vpc.enable_dns_hostnames,
            enable_dns_support=self.infra_config.vpc.enable_dns_support,
        )

        # Fix the security group - exact same as DDEV stack
        self.fck_nat_provider.security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.all_traffic(),
            description="Allow traffic from VPC CIDR for NAT"
        )

    def create_outputs(self):
        """Create CloudFormation outputs for cross-stack references"""
        
        CfnOutput(
            self,
            "VpcId",
            value=self.vpc.vpc_id,
            description="Simple Network VPC ID",
            export_name=f"SimpleNetwork-{self.account_name}-VpcId",
        )
        
        CfnOutput(
            self,
            "VpcCidr",
            value=self.vpc.vpc_cidr_block,
            description="Simple Network VPC CIDR Block",
            export_name=f"SimpleNetwork-{self.account_name}-VpcCidr",
        )
        
        CfnOutput(
            self,
            "PublicSubnetIds",
            value=",".join([subnet.subnet_id for subnet in self.vpc.public_subnets]),
            description="Public Subnet IDs (comma-separated)",
            export_name=f"SimpleNetwork-{self.account_name}-PublicSubnetIds",
        )
        
        CfnOutput(
            self,
            "PrivateSubnetIds",
            value=",".join([subnet.subnet_id for subnet in self.vpc.private_subnets]),
            description="Private Subnet IDs (comma-separated)",
            export_name=f"SimpleNetwork-{self.account_name}-PrivateSubnetIds",
        )
        
        CfnOutput(
            self,
            "AvailabilityZones",
            value=",".join(self.vpc.availability_zones),
            description="Availability Zones used by VPC",
            export_name=f"SimpleNetwork-{self.account_name}-AvailabilityZones",
        )
        
        CfnOutput(
            self,
            "NetworkSummary",
            value=f"VPC: {self.infra_config.vpc.cidr}, AZs: {self.infra_config.vpc.max_azs}, fck-nat: t4g.nano (~$3/month)",
            description="Network configuration summary",
        )
        
        CfnOutput(
            self,
            "FckNatAccess",
            value="Connect to fck-nat via SSH (key required) or check EC2 console for instance details",
            description="How to access fck-nat instance",
        )