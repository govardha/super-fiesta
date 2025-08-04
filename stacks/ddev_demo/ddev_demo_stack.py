# File: stacks/ddev_demo/ddev_demo_stack.py

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_certificatemanager as acm,
    aws_iam as iam,
    CfnOutput,
    Duration,
)
from constructs import Construct
from configs.config import AppConfigs
from configs.models import InfrastructureSpec


class DdevDemoStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Load configuration from infrastructure.yaml
        self.config_loader = AppConfigs()
        self.infra_config: InfrastructureSpec = self.config_loader.get_infrastructure_info(account_name)

        # Create VPC with fck-nat
        self.create_vpc()
        
        # Create Application Load Balancer
        self.create_application_load_balancer()
        
        # Create EC2 instance with Ubuntu 24.04 and 20GB storage
        self.create_ddev_instance()
        
        # Create target groups
        self.create_target_groups()
        
        # Create outputs
        self.create_outputs()

    def create_vpc(self):
        """Create VPC with fck-nat using official AMI"""
        
        # Get key pair name from configuration
        key_name = getattr(self.infra_config.ec2, 'key_name', None) if hasattr(self.infra_config, 'ec2') and self.infra_config.ec2 else None
        
        # Create NAT provider using official fck-nat AMI
        nat_provider_config = {
            "instance_type": ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.NANO),
            "machine_image": ec2.LookupMachineImage(
                name="fck-nat-al2023-*-arm64-ebs",
                owners=["568608671756"]  # Official fck-nat AMI owner
            )
        }
        
        # Add key name if configured
        if key_name:
            nat_provider_config["key_name"] = key_name
            
        self.fck_nat_provider = ec2.NatInstanceProviderV2(**nat_provider_config)
        
        # Create VPC
        self.vpc = ec2.Vpc(
            self,
            "DdevDemoVpc",
            ip_addresses=ec2.IpAddresses.cidr(self.infra_config.vpc.cidr),
            max_azs=self.infra_config.vpc.max_azs,
            nat_gateways=1,
            nat_gateway_provider=self.fck_nat_provider,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=self.infra_config.vpc.subnet_mask,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=self.infra_config.vpc.subnet_mask,
                ),
            ],
            enable_dns_hostnames=True,
            enable_dns_support=True,
        )

        # Fix the security group - add inbound rules for VPC traffic
        self.fck_nat_provider.security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.all_traffic(),
            description="Allow traffic from VPC CIDR for NAT"
        )

    def create_application_load_balancer(self):
        """Create Application Load Balancer"""
        
        # Security Group for ALB
        self.alb_sg = ec2.SecurityGroup(
            self,
            "ALBSecurityGroup",
            vpc=self.vpc,
            description="Security group for Application Load Balancer",
            allow_all_outbound=True,
        )
        
        self.alb_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(80),
            description="HTTP from internet",
        )
        
        self.alb_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="HTTPS from internet",
        )
        
        # Create ALB
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "DdevLoadBalancer",
            vpc=self.vpc,
            internet_facing=True,
            security_group=self.alb_sg,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )
        
        # Certificate
        self.certificate = acm.Certificate(
            self,
            "WildcardCertificate",
            domain_name="*.vadai.org",
            validation=acm.CertificateValidation.from_dns(),
        )
        
        # HTTPS Listener
        self.https_listener = self.alb.add_listener(
            "HTTPSListener",
            port=443,
            protocol=elbv2.ApplicationProtocol.HTTPS,
            certificates=[self.certificate],
            default_action=elbv2.ListenerAction.fixed_response(
                status_code=404,
                content_type="text/plain",
                message_body="Site not found"
            )
        )
        
        # HTTP Listener
        self.alb.add_listener(
            "HTTPListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_action=elbv2.ListenerAction.redirect(
                protocol="HTTPS",
                port="443",
                permanent=True
            )
        )

    def create_ddev_instance(self):
        """Create EC2 instance with Ubuntu 24.04 and 20GB storage in private subnet"""
        
        # Get configuration from infrastructure.yaml
        ami_id = getattr(self.infra_config.ec2, 'ami_id', None) if hasattr(self.infra_config, 'ec2') and self.infra_config.ec2 else None
        key_name = getattr(self.infra_config.ec2, 'key_name', None) if hasattr(self.infra_config, 'ec2') and self.infra_config.ec2 else None
        
        # Choose machine image based on configuration
        if ami_id:
            machine_image = ec2.MachineImage.generic_linux({self.region: ami_id})
        else:
            # Default to Ubuntu 24.04 LTS
            machine_image = ec2.MachineImage.latest_ubuntu(
                generation=ec2.UbuntuGeneration.UBUNTU_24_04,
            )
        
        # Security Group for instance (in private subnet)
        self.ddev_sg = ec2.SecurityGroup(
            self,
            "DdevSecurityGroup",
            vpc=self.vpc,
            description="Security group for DDEV instance in private subnet",
            allow_all_outbound=True,
        )
        
        # Allow traffic from ALB security group for DDEV ports
        self.ddev_sg.add_ingress_rule(
            peer=ec2.Peer.security_group_id(self.alb_sg.security_group_id),
            connection=ec2.Port.tcp_range(8001, 8010),
            description="DDEV ports from ALB",
        )
        
        # Optional: Allow SSH from within VPC (for debugging through bastion/fck-nat)
        self.ddev_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(22),
            description="SSH from within VPC",
        )
        
        # IAM role
        self.ddev_role = iam.Role(
            self,
            "DdevInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
            ],
        )
        
        # User data for Ubuntu 24.04
        user_data_script = ec2.UserData.for_linux()
        user_data_script.add_commands(
            "#!/bin/bash",
            "apt-get update -y",
            "apt-get install -y git curl wget docker.io docker-compose-v2",
            "",
            "# Start and enable Docker",
            "systemctl start docker",
            "systemctl enable docker",
            "usermod -a -G docker ubuntu",
            "",
            "# Install AWS SSM agent (should already be there on Ubuntu AMI)",
            "snap install amazon-ssm-agent --classic || apt-get install -y amazon-ssm-agent",
            "systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service || systemctl enable amazon-ssm-agent",
            "systemctl start snap.amazon-ssm-agent.amazon-ssm-agent.service || systemctl start amazon-ssm-agent",
            "",
            "cat > /home/ubuntu/README.md << 'EOF'",
            "# DDEV Demo Instance (Ubuntu 24.04) - Private Subnet with fck-nat",
            "This instance is in a private subnet and uses fck-nat for internet access.",
            "",
            "## Connection Options:",
            "- SSM: aws ssm start-session --target $(curl -s http://169.254.169.254/latest/meta-data/instance-id)",
            "- No direct SSH from internet (private subnet)",
            "",
            "## Network Verification:",
            "- Run: ./verify-fck-nat.sh to test internet connectivity through fck-nat",
            "- Check route: ip route show",
            "- Test DNS: nslookup google.com",
            "",
            "## Setup Steps:",
            "1. Run your ddev-setup.sh script",
            "2. Sites will be available at qa1.vadai.org, qa2.vadai.org, etc.",
            "",
            "## System Info:",
            "- OS: Ubuntu 24.04 LTS",
            "- Storage: 20GB GP3 EBS",
            "- Docker: Pre-installed",
            "- Network: Private subnet with fck-nat internet access",
            "EOF",
            "",
            "# Create network verification script",
            "cat > /home/ubuntu/verify-fck-nat.sh << 'EOF'",
            "#!/bin/bash",
            "echo '=== fck-nat Network Verification ==='",
            "echo",
            "echo '1. Current IP and routing:'",
            "echo 'Private IP:' $(curl -s http://169.254.169.254/latest/meta-data/local-ipv4)",
            "echo 'Public IP (through NAT):' $(curl -s http://checkip.amazonaws.com/ || echo 'Failed to get public IP')",
            "echo",
            "echo '2. Route table:'",
            "ip route show",
            "echo",
            "echo '3. DNS resolution:'",
            "nslookup google.com",
            "echo",
            "echo '4. Internet connectivity test:'",
            "curl -s -o /dev/null -w 'HTTP Status: %{http_code}\\n' http://google.com",
            "echo",
            "echo '5. Package manager test (apt):'",
            "apt list --upgradable 2>/dev/null | head -5",
            "echo",
            "echo '6. Docker registry test:'",
            "timeout 10 docker pull hello-world:latest >/dev/null 2>&1 && echo 'Docker registry: OK' || echo 'Docker registry: Failed'",
            "echo",
            "echo 'If all tests pass, fck-nat routing is working correctly!'",
            "EOF",
            "",
            "chmod +x /home/ubuntu/verify-fck-nat.sh",
            "chown ubuntu:ubuntu /home/ubuntu/README.md /home/ubuntu/verify-fck-nat.sh",
        )
        
        # Create the EC2 instance
        self.ddev_instance = ec2.Instance(
            self,
            "DdevInstance",
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE3, ec2.InstanceSize.MICRO),
            machine_image=machine_image,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_group=self.ddev_sg,
            role=self.ddev_role,
            key_pair=ec2.KeyPair.from_key_pair_name(self, "DdevKeyPair", key_name) if key_name else None,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",  # Ubuntu root device
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=20,  # 20 GB
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        delete_on_termination=True,
                        encrypted=False,
                    )
                )
            ],
            user_data=user_data_script,
        )

    def create_target_groups(self):
        """Create target groups"""
        
        # Target group for qa1
        self.qa1_tg = elbv2.ApplicationTargetGroup(
            self,
            "QA1TargetGroup",
            vpc=self.vpc,
            port=8001,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.INSTANCE,
            health_check=elbv2.HealthCheck(
                enabled=True,
                healthy_http_codes="200,404",
                path="/health",
                port="8001",
                protocol=elbv2.Protocol.HTTP,
                timeout=Duration.seconds(5),
                interval=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=5,
            ),
        )
        
        # Target group for qa2
        self.qa2_tg = elbv2.ApplicationTargetGroup(
            self,
            "QA2TargetGroup",
            vpc=self.vpc,
            port=8002,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.INSTANCE,
            health_check=elbv2.HealthCheck(
                enabled=True,
                healthy_http_codes="200,404",
                path="/health",
                port="8002",
                protocol=elbv2.Protocol.HTTP,
                timeout=Duration.seconds(5),
                interval=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=5,
            ),
        )
        
        # Listener rules
        self.https_listener.add_action(
            "QA1ListenerRule",
            priority=110,
            conditions=[
                elbv2.ListenerCondition.host_headers(["qa1.vadai.org"])
            ],
            action=elbv2.ListenerAction.forward([self.qa1_tg])
        )
        
        self.https_listener.add_action(
            "QA2ListenerRule",
            priority=120,
            conditions=[
                elbv2.ListenerCondition.host_headers(["qa2.vadai.org"])
            ],
            action=elbv2.ListenerAction.forward([self.qa2_tg])
        )

    def create_outputs(self):
        """Create outputs"""
        
        CfnOutput(
            self,
            "LoadBalancerDNS",
            value=self.alb.load_balancer_dns_name,
            description="ALB DNS name",
        )
        
        CfnOutput(
            self,
            "DdevInstancePrivateIP",
            value=self.ddev_instance.instance_private_ip,
            description="DDEV Instance Private IP",
        )
        
        CfnOutput(
            self,
            "DdevInstanceId",
            value=self.ddev_instance.instance_id,
            description="DDEV Instance ID",
        )
        
        CfnOutput(
            self,
            "SSMCommand",
            value=f"aws ssm start-session --target {self.ddev_instance.instance_id}",
            description="SSM command to connect to instance (primary access method)",
        )
        
        CfnOutput(
            self,
            "NetworkArchitecture",
            value="Private subnet → fck-nat (t4g.nano) → Internet Gateway → Internet",
            description="Network routing architecture",
        )
        
        CfnOutput(
            self,
            "QA1TargetGroupArn",
            value=self.qa1_tg.target_group_arn,
            description="QA1 Target Group ARN",
        )
        
        CfnOutput(
            self,
            "QA2TargetGroupArn",
            value=self.qa2_tg.target_group_arn,
            description="QA2 Target Group ARN",
        )
        
        CfnOutput(
            self,
            "AccessInstructions",
            value="1. Connect via SSM: aws ssm start-session --target " + self.ddev_instance.instance_id + " 2. Run: ./verify-fck-nat.sh to test network 3. SSH only from within VPC",
            description="How to access and verify the instance",
        )
        
        CfnOutput(
            self,
            "CostSavings",
            value="fck-nat (t4g.nano): ~$3/month vs AWS NAT Gateway: ~$45/month = 93% savings ($42/month saved)",
            description="Cost comparison and savings",
        )
        
        CfnOutput(
            self,
            "FckNatInfo",
            value="Using official fck-nat AMI with pre-configured NAT software - no user data installation needed",
            description="About the fck-nat setup",
        )