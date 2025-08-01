from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
    CfnOutput,
    RemovalPolicy,
)
from constructs import Construct


class VpcInterfaceEndpointsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create VPC with private subnets
        self.vpc = ec2.Vpc(
            self,
            "VpcEndpointsDemo",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=2,
            nat_gateways=0,  # No NAT gateways to force traffic through endpoints
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                )
            ],
            enable_dns_hostnames=True,
            enable_dns_support=True,
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

        # CloudWatch Logs Group for VPC Flow Logs
        self.flow_logs_group = logs.LogGroup(
            self,
            "VpcFlowLogsGroup",
            log_group_name="/aws/vpc/flowlogs",
            removal_policy=RemovalPolicy.DESTROY,
            retention=logs.RetentionDays.ONE_WEEK,
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
        """Create VPC Interface Endpoints for AWS services"""
        
        # SSM VPC Endpoint
        self.ssm_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "SsmEndpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.SSM,
            security_groups=[self.endpoint_sg],
            private_dns_enabled=True,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            policy_document=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        principals=[iam.AnyPrincipal()],
                        actions=["ssm:*"],
                        resources=["*"],
                    )
                ]
            ),
        )

        # SSM Messages VPC Endpoint
        self.ssm_messages_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "SsmMessagesEndpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.SSM_MESSAGES,
            security_groups=[self.endpoint_sg],
            private_dns_enabled=True,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
        )

        # EC2 Messages VPC Endpoint
        self.ec2_messages_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "Ec2MessagesEndpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.EC2_MESSAGES,
            security_groups=[self.endpoint_sg],
            private_dns_enabled=True,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
        )

        # EC2 VPC Endpoint
        self.ec2_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "Ec2Endpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.EC2,
            security_groups=[self.endpoint_sg],
            private_dns_enabled=True,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
        )

        # STS VPC Endpoint
        self.sts_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "StsEndpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.STS,
            security_groups=[self.endpoint_sg],
            private_dns_enabled=True,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
        )

        # CloudWatch Logs VPC Endpoint (for additional testing)
        self.logs_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "LogsEndpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            security_groups=[self.endpoint_sg],
            private_dns_enabled=True,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
        )

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
        """Create EC2 instance for testing VPC endpoints"""
        
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
            "dig ssm.us-east-1.amazonaws.com",
            "echo",
            "echo 'Testing EC2 endpoint:'", 
            "dig ec2.us-east-1.amazonaws.com",
            "echo",
            "echo 'Testing STS endpoint:'",
            "dig sts.us-east-1.amazonaws.com",
            "echo",
            "echo '=== AWS CLI Tests ==='",
            "echo 'Getting caller identity (STS):'",
            "aws sts get-caller-identity --region us-east-1",
            "echo",
            "echo 'Listing EC2 instances:'",
            "aws ec2 describe-instances --region us-east-1 --max-items 1",
            "echo",
            "echo 'Testing SSM:'",
            "aws ssm describe-instance-information --region us-east-1 --max-items 1",
            "EOF",
            
            "chmod +x /home/ec2-user/test-endpoints.sh",
            "chown ec2-user:ec2-user /home/ec2-user/test-endpoints.sh",
            
            # Create network testing script
            "cat > /home/ec2-user/test-network.sh << 'EOF'",
            "#!/bin/bash",
            "echo '=== Network Connectivity Test ==='",
            "echo",
            "echo 'Testing connectivity to SSM endpoint on port 443:'",
            "nc -zv ssm.us-east-1.amazonaws.com 443",
            "echo",
            "echo 'Testing connectivity to EC2 endpoint on port 443:'",
            "nc -zv ec2.us-east-1.amazonaws.com 443",
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

        # Amazon Linux 2 AMI
        amzn_linux = ec2.MachineImage.latest_amazon_linux2(
            edition=ec2.AmazonLinuxEdition.STANDARD,
            virtualization=ec2.AmazonLinuxVirt.HVM,
            storage=ec2.AmazonLinuxStorage.GENERAL_PURPOSE,
        )

        # Create EC2 instance
        self.test_instance = ec2.Instance(
            self,
            "VpcEndpointTestInstance",
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE3, ec2.InstanceSize.MICRO
            ),
            machine_image=amzn_linux,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            security_group=self.instance_sg,
            role=self.ec2_role,
            user_data=user_data_script,
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
            "InstanceId",
            value=self.test_instance.instance_id,
            description="Test EC2 Instance ID",
        )

        CfnOutput(
            self,
            "SsmEndpointId",
            value=self.ssm_endpoint.vpc_endpoint_id,
            description="SSM VPC Endpoint ID",
        )

        CfnOutput(
            self,
            "TestCommands",
            value="Connect via SSM: aws ssm start-session --target " + self.test_instance.instance_id,
            description="Commands to test the VPC endpoints",
        )