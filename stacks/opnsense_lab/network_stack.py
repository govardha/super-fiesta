from aws_cdk import Stack, aws_ec2 as ec2
from constructs import Construct

from configs.config import AppConfigs
from configs.models import InfrastructureSpec


class OpnsenseLabNetworkStack(Stack):
    """
    OPNsense Lab networking: VPC, subnets, IGW, SSM VPC endpoints.

    Deployed once and shared with ComputeStack.
    """

    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        config_loader = AppConfigs()
        infra: InfrastructureSpec = config_loader.get_infrastructure_info(account_name)
        lab = infra.opnsense_lab

        # --- VPC: public + private isolated, 0 NAT (OPNsense IS the NAT) ---
        self.vpc = ec2.Vpc(
            self, "OpnsenseLabVpc",
            vpc_name=f"OpnsenseLab-{account_name}",
            ip_addresses=ec2.IpAddresses.cidr(lab.vpc.cidr),
            max_azs=1,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=lab.vpc.subnet_mask),
                ec2.SubnetConfiguration(name="PrivateIsolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=lab.vpc.subnet_mask),
            ],
            enable_dns_hostnames=True,
            enable_dns_support=True,
        )

        self.public_subnet = self.vpc.public_subnets[0]
        self.private_subnet = self.vpc.isolated_subnets[0]

        # --- SSM VPC endpoints (AlmaLinux needs SSM before OPNsense NAT is configured) ---
        self.endpoint_sg = ec2.SecurityGroup(self, "EndpointSG", vpc=self.vpc, description="SSM VPC Endpoints", allow_all_outbound=False)
        self.endpoint_sg.add_ingress_rule(ec2.Peer.ipv4(self.vpc.vpc_cidr_block), ec2.Port.tcp(443), "HTTPS from VPC")

        for svc_name, svc in [
            ("ssm", ec2.InterfaceVpcEndpointAwsService.SSM),
            ("ssm-messages", ec2.InterfaceVpcEndpointAwsService.SSM_MESSAGES),
            ("ec2-messages", ec2.InterfaceVpcEndpointAwsService.EC2_MESSAGES),
        ]:
            ec2.InterfaceVpcEndpoint(
                self, f"{svc_name}-endpoint", vpc=self.vpc, service=svc,
                security_groups=[self.endpoint_sg], private_dns_enabled=True,
                subnets=ec2.SubnetSelection(subnets=[self.private_subnet]),
            )
