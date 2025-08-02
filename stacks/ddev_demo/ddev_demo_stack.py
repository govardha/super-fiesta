# File: stacks/ddev_demo/ddev_demo_stack.py

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_certificatemanager as acm,
    aws_iam as iam,
    aws_ssm as ssm,
    CfnOutput,
    Duration,
    custom_resources as cr,
    CustomResource,
    aws_lambda as lambda_,
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
        self.create_vpc_with_fck_nat()
        
        # Create Application Load Balancer
        self.create_application_load_balancer()
        
        # Create Lambda functions
        self.create_lambda_functions()
        
        # Create CloudFlare DNS automation
        self.create_cloudflare_automation()
        
        # Create EC2 instance
        self.create_ddev_instance()
        
        # Create initial target groups for qa1 and qa2
        self.create_initial_target_groups()
        
        # Create outputs
        self.create_outputs()

    def create_vpc_with_fck_nat(self):
        """Create VPC with fck-nat for cost-effective NAT"""
        
        # Create VPC
        self.vpc = ec2.Vpc(
            self,
            "DdevDemoVpc",
            ip_addresses=ec2.IpAddresses.cidr(self.infra_config.vpc.cidr),
            max_azs=self.infra_config.vpc.max_azs,
            nat_gateways=0,  # We'll use fck-nat instead
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
            enable_dns_hostnames=self.infra_config.vpc.enable_dns_hostnames,
            enable_dns_support=self.infra_config.vpc.enable_dns_support,
        )

        # Security Group for fck-nat instance
        self.fck_nat_sg = ec2.SecurityGroup(
            self,
            "FckNatSecurityGroup",
            vpc=self.vpc,
            description="Security group for fck-nat instance",
            allow_all_outbound=True,
        )

        # Allow all traffic from VPC CIDR
        self.fck_nat_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.all_traffic(),
            description="All traffic from VPC",
        )

        # Allow SSH from anywhere (adjust as needed)
        self.fck_nat_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(22),
            description="SSH access",
        )

        # fck-nat instance (t4g.nano ARM64 for lowest cost)
        # Using us-east-1 AMI - update for other regions
        fck_nat_ami_id = "ami-0f69bc61d11ea4787"  # fck-nat ARM64 AMI for us-east-1
        
        self.fck_nat_instance = ec2.Instance(
            self,
            "FckNatInstance",
            instance_type=ec2.InstanceType("t4g.nano"),
            machine_image=ec2.MachineImage.generic_linux({
                self.region: fck_nat_ami_id
            }),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=self.fck_nat_sg,
            source_dest_check=False,  # Required for NAT functionality
        )

        # Update route tables for private subnets to use fck-nat
        for i, subnet in enumerate(self.vpc.private_subnets):
            # Create custom route table
            route_table = ec2.CfnRouteTable(
                self,
                f"PrivateRouteTable{i}",
                vpc_id=self.vpc.vpc_id,
                tags=[{"key": "Name", "value": f"PrivateRouteTable{i}"}]
            )
            
            # Associate route table with subnet
            ec2.CfnSubnetRouteTableAssociation(
                self,
                f"PrivateSubnetAssociation{i}",
                subnet_id=subnet.subnet_id,
                route_table_id=route_table.ref,
            )
            
            # Add route to fck-nat instance
            ec2.CfnRoute(
                self,
                f"PrivateRoute{i}",
                route_table_id=route_table.ref,
                destination_cidr_block="0.0.0.0/0",
                instance_id=self.fck_nat_instance.instance_id,
            )

    def create_application_load_balancer(self):
        """Create Application Load Balancer for DDEV sites"""
        
        # Security Group for ALB
        self.alb_sg = ec2.SecurityGroup(
            self,
            "ALBSecurityGroup",
            vpc=self.vpc,
            description="Security group for Application Load Balancer",
            allow_all_outbound=True,
        )
        
        # Allow HTTP and HTTPS from internet
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
        
        # Certificate for *.vadai.org
        self.certificate = acm.Certificate(
            self,
            "WildcardCertificate",
            domain_name="*.vadai.org",
            validation=acm.CertificateValidation.from_dns(),
        )
        
        # HTTPS Listener with default 404 response
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
        
        # HTTP Listener (redirect to HTTPS)
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

    def create_lambda_functions(self):
        """Create Lambda functions from separate directories"""
        
        # CloudFlare DNS Lambda
        self.dns_lambda = lambda_.Function(
            self,
            "CloudFlareDnsFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.minutes(5),
            code=lambda_.Code.from_asset("lambdas/cloudflare_dns"),
        )
        
        # Grant permissions to read SSM parameters
        self.dns_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/ddev-demo/cloudflare/*"
                ]
            )
        )

    def create_cloudflare_automation(self):
        """Setup CloudFlare DNS automation"""
        
        # Store CloudFlare credentials in SSM (placeholder values)
        ssm.StringParameter(
            self,
            "CloudFlareApiTokenParam",
            parameter_name="/ddev-demo/cloudflare/api-token",
            string_value="PLACEHOLDER-SET-MANUALLY",
            description="CloudFlare API Token (set manually after deployment)",
            # Remove deprecated type parameter - it defaults to String for secure strings
        )
        
        # For secure string, use CfnParameter directly
        ssm.CfnParameter(
            self,
            "CloudFlareApiTokenSecure",
            name="/ddev-demo/cloudflare/api-token-secure",
            value="PLACEHOLDER-SET-MANUALLY",
            type="SecureString",
            description="CloudFlare API Token (secure - set manually after deployment)",
        )
        
        ssm.StringParameter(
            self,
            "CloudFlareZoneIdParam", 
            parameter_name="/ddev-demo/cloudflare/zone-id",
            string_value="PLACEHOLDER-SET-MANUALLY",
            description="CloudFlare Zone ID for vadai.org (set manually after deployment)",
        )
        
        # Custom resource provider for DNS management
        self.dns_provider = cr.Provider(
            self,
            "CloudFlareDnsProvider",
            on_event_handler=self.dns_lambda,
        )

    def create_ddev_instance(self):
        """Create EC2 instance for DDEV"""
        
        # Security Group for DDEV instance
        self.ddev_sg = ec2.SecurityGroup(
            self,
            "DdevSecurityGroup",
            vpc=self.vpc,
            description="Security group for DDEV instance",
            allow_all_outbound=True,
        )
        
        # Allow SSH from anywhere
        self.ddev_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(22),
            description="SSH access",
        )
        
        # Allow ALB to access DDEV ports (8001-8010)
        self.ddev_sg.add_ingress_rule(
            peer=ec2.Peer.security_group_id(self.alb_sg.security_group_id),
            connection=ec2.Port.tcp_range(8001, 8010),
            description="DDEV ports from ALB",
        )
        
        # IAM role for the instance
        self.ddev_role = iam.Role(
            self,
            "DdevInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
            ],
        )
        
        # Minimal user data - just create a readme
        user_data_script = ec2.UserData.for_linux()
        user_data_script.add_commands(
            "#!/bin/bash",
            "yum update -y",
            "yum install -y git curl wget",
            "",
            "# Create setup instructions",
            "cat > /home/ec2-user/README.md << 'EOF'",
            "# DDEV Demo Instance Setup",
            "",
            "This instance is ready for DDEV setup.",
            "",
            "## Next Steps:",
            "1. Copy the ddev-setup.sh script to this instance",
            "2. Run: chmod +x ddev-setup.sh && sudo ./ddev-setup.sh",
            "",
            "## Connect via SSM:",
            "aws ssm start-session --target INSTANCE_ID",
            "",
            "## After DDEV setup, your sites will be:",
            "- https://qa1.vadai.org",
            "- https://qa2.vadai.org",
            "",
            "EOF",
            "",
            "chown ec2-user:ec2-user /home/ec2-user/README.md",
        )
        
        # Create the EC2 instance
        self.ddev_instance = ec2.Instance(
            self,
            "DdevInstance",
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE3, ec2.InstanceSize.MICRO),
            machine_image=ec2.MachineImage.latest_amazon_linux2(),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_group=self.ddev_sg,
            role=self.ddev_role,
            user_data=user_data_script,
        )

    def create_initial_target_groups(self):
        """Create target groups and listener rules for qa1 and qa2"""
        
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
        
        # Listener rules for qa1 and qa2
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
        
        # Create DNS records for qa1 and qa2
        CustomResource(
            self,
            "DnsRecordQA1",
            service_token=self.dns_provider.service_token,
            properties={
                "DomainName": "qa1.vadai.org",
                "TargetValue": self.alb.load_balancer_dns_name,
                "RecordType": "CNAME"
            }
        )
        
        CustomResource(
            self,
            "DnsRecordQA2",
            service_token=self.dns_provider.service_token,
            properties={
                "DomainName": "qa2.vadai.org",
                "TargetValue": self.alb.load_balancer_dns_name,
                "RecordType": "CNAME"
            }
        )

    def create_outputs(self):
        """Create CloudFormation outputs"""
        
        CfnOutput(
            self,
            "VpcId",
            value=self.vpc.vpc_id,
            description="VPC ID",
        )
        
        CfnOutput(
            self,
            "LoadBalancerDNS",
            value=self.alb.load_balancer_dns_name,
            description="Application Load Balancer DNS name",
        )
        
        CfnOutput(
            self,
            "LoadBalancerArn",
            value=self.alb.load_balancer_arn,
            description="Application Load Balancer ARN",
        )
        
        CfnOutput(
            self,
            "HTTPSListenerArn",
            value=self.https_listener.listener_arn,
            description="HTTPS Listener ARN for adding new rules",
        )
        
        CfnOutput(
            self,
            "DdevInstanceId",
            value=self.ddev_instance.instance_id,
            description="DDEV EC2 Instance ID",
        )
        
        CfnOutput(
            self,
            "FckNatInstanceId",
            value=self.fck_nat_instance.instance_id,
            description="FCK-NAT Instance ID",
        )
        
        CfnOutput(
            self,
            "CloudFlareDNSLambda",
            value=self.dns_lambda.function_name,
            description="CloudFlare DNS management Lambda function",
        )
        
        CfnOutput(
            self,
            "CertificateArn",
            value=self.certificate.certificate_arn,
            description="ACM Certificate ARN for *.vadai.org",
        )
        
        CfnOutput(
            self,
            "ConnectToInstance",
            value=f"aws ssm start-session --target {self.ddev_instance.instance_id}",
            description="Command to connect to DDEV instance via SSM",
        )
        
        CfnOutput(
            self,
            "InitialSites",
            value="qa1.vadai.org, qa2.vadai.org (configure manually after DDEV setup)",
            description="Initial sites - target groups created, configure DDEV manually",
        )
        
        CfnOutput(
            self,
            "SetupInstructions",
            value="1. Set CloudFlare credentials in SSM 2. Validate ACM certificate 3. SSH to instance and run ddev-setup.sh",
            description="Next steps after deployment",
        )