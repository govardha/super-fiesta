from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
    CfnOutput,
    RemovalPolicy,
)
from constructs import Construct
from configs.config import AppConfigs
from configs.models import InfrastructureSpec


class VpcInterfaceEndpointsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Load configuration from infrastructure.yaml
        self.config_loader = AppConfigs()
        self.infra_config: InfrastructureSpec = self.config_loader.get_infrastructure_info(account_name)

        # Create VPC with configuration from infrastructure.yaml
        self.vpc = ec2.Vpc(
            self,
            "VpcEndpointsDemo",
            ip_addresses=ec2.IpAddresses.cidr(self.infra_config.vpc.cidr),
            max_azs=self.infra_config.vpc.max_azs,
            nat_gateways=self.infra_config.vpc.nat_gateways,  # No NAT gateways to force traffic through endpoints
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=self.infra_config.vpc.subnet_mask,
                )
            ],
            enable_dns_hostnames=self.infra_config.vpc.enable_dns_hostnames,
            enable_dns_support=self.infra_config.vpc.enable_dns_support,
        )

        # Security Group for VPC Endpoints
        self.endpoint_sg = ec2.SecurityGroup(
            self,
            "VpcEndpointSecurityGroup",
            vpc=self.vpc,
            description="Security group for VPC Interface Endpoints",
            allow_all_outbound=False,
        )

        # Allow HTTPS traffic from VPC CIDR
        self.endpoint_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(443),
            description="Allow HTTPS from VPC",
        )

        # Security Group for EC2 instances
        self.instance_sg = ec2.SecurityGroup(
            self,
            "InstanceSecurityGroup",
            vpc=self.vpc,
            description="Security group for EC2 instances using VPC endpoints",
            allow_all_outbound=True,
        )

        # CloudWatch Logs Group for VPC Flow Logs (from config)
        retention_mapping = {
            1: logs.RetentionDays.ONE_DAY,
            3: logs.RetentionDays.THREE_DAYS,
            5: logs.RetentionDays.FIVE_DAYS,
            7: logs.RetentionDays.ONE_WEEK,
            14: logs.RetentionDays.TWO_WEEKS,
            30: logs.RetentionDays.ONE_MONTH,
            60: logs.RetentionDays.TWO_MONTHS,
            90: logs.RetentionDays.THREE_MONTHS,
            120: logs.RetentionDays.FOUR_MONTHS,
            150: logs.RetentionDays.FIVE_MONTHS,
            180: logs.RetentionDays.SIX_MONTHS,
            365: logs.RetentionDays.ONE_YEAR,
        }
        
        retention_days = retention_mapping.get(
            self.infra_config.logging.retention_days, 
            logs.RetentionDays.ONE_WEEK
        )
        
        self.flow_logs_group = logs.LogGroup(
            self,
            "VpcFlowLogsGroup",
            log_group_name=self.infra_config.logging.flow_logs_group_name,
            removal_policy=RemovalPolicy.DESTROY,
            retention=retention_days,
        )

        # VPC Flow Logs Role
        self.flow_logs_role = iam.Role(
            self,
            "FlowLogsRole",
            assumed_by=iam.ServicePrincipal("vpc-flow-logs.amazonaws.com"),
            inline_policies={
                "FlowLogsDeliveryRolePolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                                "logs:DescribeLogGroups",
                                "logs:DescribeLogStreams",
                            ],
                            resources=["*"],
                        )
                    ]
                )
            },
        )

        # Enable VPC Flow Logs
        ec2.FlowLog(
            self,
            "VpcFlowLog",
            resource_type=ec2.FlowLogResourceType.from_vpc(self.vpc),
            destination=ec2.FlowLogDestination.to_cloud_watch_logs(
                self.flow_logs_group, self.flow_logs_role
            ),
            traffic_type=ec2.FlowLogTrafficType.ALL,
        )

        # Create VPC Interface Endpoints for the required services
        self.create_vpc_endpoints()

        # Create IAM role for EC2 instances to use Systems Manager
        self.create_ec2_role()

        # Create test EC2 instance
        self.create_test_instance()

        # Outputs
        self.create_outputs()

    def create_vpc_endpoints(self):
        """Create VPC Interface Endpoints for AWS services from configuration"""
        
        # Create endpoints based on configuration
        service_mapping = {
            "SSM": ec2.InterfaceVpcEndpointAwsService.SSM,
            "SSM_MESSAGES": ec2.InterfaceVpcEndpointAwsService.SSM_MESSAGES,
            "EC2_MESSAGES": ec2.InterfaceVpcEndpointAwsService.EC2_MESSAGES,
            "EC2": ec2.InterfaceVpcEndpointAwsService.EC2,
            "STS": ec2.InterfaceVpcEndpointAwsService.STS,
            "CLOUDWATCH_LOGS": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
        }
        
        self.endpoints = {}
        
        for endpoint_service in self.infra_config.endpoints.services:
            service_name = endpoint_service.service
            endpoint_name = endpoint_service.name
            
            if service_name not in service_mapping:
                continue
                
            endpoint = ec2.InterfaceVpcEndpoint(
                self,
                f"{endpoint_name.title()}Endpoint",
                vpc=self.vpc,
                service=service_mapping[service_name],
                security_groups=[self.endpoint_sg],
                private_dns_enabled=True,
                subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            )
            
            # Add policy to SSM endpoint after creation
            if service_name == "SSM":
                endpoint.add_to_policy(
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        principals=[iam.AnyPrincipal()],
                        actions=["ssm:*"],
                        resources=["*"],
                    )
                )
            
            self.endpoints[endpoint_name] = endpoint

    def create_ec2_role(self):
        """Create IAM role for EC2 instances with necessary permissions"""
        
        self.ec2_role = iam.Role(
            self,
            "Ec2VpcEndpointRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
                iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"),
            ],
            inline_policies={
                "VpcEndpointTestPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "ec2:DescribeInstances",
                                "ec2:DescribeVpcs",
                                "ec2:DescribeVpcEndpoints",
                                "sts:GetCallerIdentity",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                                "logs:DescribeLogStreams",
                            ],
                            resources=["*"],
                        )
                    ]
                )
            },
        )

        self.instance_profile = iam.InstanceProfile(
            self,
            "Ec2InstanceProfile",
            role=self.ec2_role,
        )

    def create_test_instance(self):
        """Create EC2 instance for testing VPC endpoints using configuration"""
        
        # User data script for testing VPC endpoints
        user_data_script = ec2.UserData.for_linux()
        user_data_script.add_commands(
            "yum update -y",
            "yum install -y aws-cli dig tcpdump nmap-ncat",
            
            # Install CloudWatch agent
            "wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm",
            "rpm -U ./amazon-cloudwatch-agent.rpm",
            
            # Create test scripts
            "cat > /home/ec2-user/test-endpoints.sh << 'EOF'",
            "#!/bin/bash",
            "echo '=== VPC Endpoints DNS Resolution Test ==='",
            "echo",
            "echo 'Testing SSM endpoint:'",
            f"dig ssm.{self.infra_config.region}.amazonaws.com",
            "echo",
            "echo 'Testing EC2 endpoint:'", 
            f"dig ec2.{self.infra_config.region}.amazonaws.com",
            "echo",
            "echo 'Testing STS endpoint:'",
            f"dig sts.{self.infra_config.region}.amazonaws.com",
            "echo",
            "echo '=== AWS CLI Tests ==='",
            "echo 'Getting caller identity (STS):'",
            f"aws sts get-caller-identity --region {self.infra_config.region}",
            "echo",
            "echo 'Listing EC2 instances:'",
            f"aws ec2 describe-instances --region {self.infra_config.region} --max-items 1",
            "echo",
            "echo 'Testing SSM:'",
            f"aws ssm describe-instance-information --region {self.infra_config.region} --max-items 1",
            "EOF",
            
            "chmod +x /home/ec2-user/test-endpoints.sh",
            "chown ec2-user:ec2-user /home/ec2-user/test-endpoints.sh",
            
            # Create network testing script
            "cat > /home/ec2-user/test-network.sh << 'EOF'",
            "#!/bin/bash",
            "echo '=== Network Connectivity Test ==='",
            "echo",
            "echo 'Testing connectivity to SSM endpoint on port 443:'",
            f"nc -zv ssm.{self.infra_config.region}.amazonaws.com 443",
            "echo",
            "echo 'Testing connectivity to EC2 endpoint on port 443:'",
            f"nc -zv ec2.{self.infra_config.region}.amazonaws.com 443",
            "echo",
            "echo 'Route table:'",
            "ip route",
            "echo",
            "echo 'DNS configuration:'",
            "cat /etc/resolv.conf",
            "EOF",
            
            "chmod +x /home/ec2-user/test-network.sh",
            "chown ec2-user:ec2-user /home/ec2-user/test-network.sh",
        )

        # Map configuration to CDK enums
        instance_class_mapping = {
            "BURSTABLE2": ec2.InstanceClass.BURSTABLE2,
            "BURSTABLE3": ec2.InstanceClass.BURSTABLE3,
            "STANDARD5": ec2.InstanceClass.STANDARD5,
            "MEMORY5": ec2.InstanceClass.MEMORY5,
        }
        
        instance_size_mapping = {
            "NANO": ec2.InstanceSize.NANO,
            "MICRO": ec2.InstanceSize.MICRO,
            "SMALL": ec2.InstanceSize.SMALL,
            "MEDIUM": ec2.InstanceSize.MEDIUM,
            "LARGE": ec2.InstanceSize.LARGE,
        }
        
        edition_mapping = {
            "STANDARD": ec2.AmazonLinuxEdition.STANDARD,
            "MINIMAL": ec2.AmazonLinuxEdition.MINIMAL,
        }
        
        virt_mapping = {
            "HVM": ec2.AmazonLinuxVirt.HVM,
            "PV": ec2.AmazonLinuxVirt.PV,
        }
        
        storage_mapping = {
            "GENERAL_PURPOSE": ec2.AmazonLinuxStorage.GENERAL_PURPOSE,
            "EBS": ec2.AmazonLinuxStorage.EBS,
        }

        # Amazon Linux 2 AMI with configuration
        amzn_linux = ec2.MachineImage.latest_amazon_linux2(
            edition=edition_mapping.get(self.infra_config.ec2.amazon_linux_edition, ec2.AmazonLinuxEdition.STANDARD),
            virtualization=virt_mapping.get(self.infra_config.ec2.virtualization, ec2.AmazonLinuxVirt.HVM),
            storage=storage_mapping.get(self.infra_config.ec2.storage, ec2.AmazonLinuxStorage.GENERAL_PURPOSE),
        )

        # Create EC2 instance with configuration
        instance_class = instance_class_mapping.get(self.infra_config.ec2.instance_class, ec2.InstanceClass.BURSTABLE3)
        instance_size = instance_size_mapping.get(self.infra_config.ec2.instance_size, ec2.InstanceSize.MICRO)
        
        # Get key name from configuration
        key_name = getattr(self.infra_config.ec2, 'key_name', None) if hasattr(self.infra_config, 'ec2') and self.infra_config.ec2 else None
        
        # Create instance configuration dictionary
        instance_config = {
            "scope": self,
            "id": "VpcEndpointTestInstance",
            "instance_type": ec2.InstanceType.of(instance_class, instance_size),
            "machine_image": amzn_linux,
            "vpc": self.vpc,
            "vpc_subnets": ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            "security_group": self.instance_sg,
            "role": self.ec2_role,
            "user_data": user_data_script,
        }
        
        # Add key pair if configured (using new CDK v2 syntax)
        if key_name:
            instance_config["key_pair"] = ec2.KeyPair.from_key_pair_name(
                self, "VpcEndpointTestKeyPair", key_name
            )
        
        self.test_instance = ec2.Instance(**instance_config)

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
            "InstanceId",
            value=self.test_instance.instance_id,
            description="Test EC2 Instance ID",
        )

        CfnOutput(
            self,
            "SsmEndpointId",
            value=self.endpoints.get("ssm", self.endpoints.get("SSM", "")).vpc_endpoint_id if self.endpoints.get("ssm", self.endpoints.get("SSM")) else "Not created",
            description="SSM VPC Endpoint ID",
        )

        CfnOutput(
            self,
            "TestCommands",
            value="Connect via SSM: aws ssm start-session --target " + self.test_instance.instance_id,
            description="Commands to test the VPC endpoints",
        )
