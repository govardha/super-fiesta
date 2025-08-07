# File: stacks/guacamole_workstation/guacamole_workstation_stack.py

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_certificatemanager as acm,
    aws_iam as iam,
    CfnOutput,
    Duration,
    Fn
)

import aws_cdk as cdk
from constructs import Construct
from configs.config import AppConfigs
from configs.models import InfrastructureSpec

class GuacamoleWorkstationStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Load configuration from infrastructure.yaml
        self.config_loader = AppConfigs()
        self.infra_config: InfrastructureSpec = self.config_loader.get_infrastructure_info(account_name)
        self.account_name = account_name

        # Import existing VPC from SimpleNetwork stack
        self.import_vpc()
        
        # Create Application Load Balancer for Guacamole
        self.create_application_load_balancer()
        
        # Create workstation instance.
        self.create_workstation_instance()  

        # Create target groups and ALB rules
        self.create_target_groups()
        
        # Create outputs
        self.create_outputs()
        self.add_workstation_outputs() 

    def import_vpc(self):
        """Import VPC by looking up by tags"""
        
        # Import VPC using lookup by tags
        self.vpc = ec2.Vpc.from_lookup(
            self,
            "ImportedVpc",
            tags={
                "aws:cloudformation:stack-name": "SimpleNetwork"
            }
        )
        
        # Use standard subnet selection - CDK will find them automatically
        self.public_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PUBLIC
        )
        
        self.private_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )

    def create_workstation_instance(self):
        """Create dev workstation instance with configurable EBS volume"""
        
        # Get workstation configuration
        workstation_config = self.infra_config.workstation
        
        # Choose instance type based on architecture and config
        if workstation_config.architecture == "arm64":
            instance_class = ec2.InstanceClass.BURSTABLE4_GRAVITON  # t4g
        else:
            instance_class = getattr(ec2.InstanceClass, workstation_config.instance_class)
        
        instance_size = getattr(ec2.InstanceSize, workstation_config.instance_size)
        
        # Use same AMI as DDEV stack
        ami_id = getattr(self.infra_config.ec2, 'ami_id', None)
        key_name = getattr(self.infra_config.ec2, 'key_name', None)
        
        if ami_id:
            machine_image = ec2.MachineImage.generic_linux({self.region: ami_id})
        else:
            # Default to Ubuntu 24.04 LTS
            if workstation_config.architecture == "arm64":
                machine_image = ec2.MachineImage.latest_ubuntu(
                    generation=ec2.UbuntuGeneration.UBUNTU_24_04,
                    cpu_type=ec2.AmazonLinuxCpuType.ARM_64
                )
            else:
                machine_image = ec2.MachineImage.latest_ubuntu(
                    generation=ec2.UbuntuGeneration.UBUNTU_24_04,
                    cpu_type=ec2.AmazonLinuxCpuType.X86_64
                )
        
        # Security Group for workstation
        self.workstation_sg = ec2.SecurityGroup(
            self,
            "WorkstationSecurityGroup",
            vpc=self.vpc,
            description="Security group for dev workstation instance",
            allow_all_outbound=True,
        )
        
        # Allow Guacamole port from ALB
        self.workstation_sg.add_ingress_rule(
            peer=ec2.Peer.security_group_id(self.alb_sg.security_group_id),
            connection=ec2.Port.tcp(workstation_config.guacamole_port),
            description=f"Guacamole access from ALB on port {workstation_config.guacamole_port}",
        )
        
        # Allow VNC port from ALB (for direct VNC access)
        self.workstation_sg.add_ingress_rule(
            peer=ec2.Peer.security_group_id(self.alb_sg.security_group_id),
            connection=ec2.Port.tcp(workstation_config.vnc_port),
            description=f"VNC access from ALB on port {workstation_config.vnc_port}",
        )
        
        # Allow SSH from within VPC
        self.workstation_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(22),
            description="SSH from within VPC",
        )
        
        # IAM role for workstation
        self.workstation_role = iam.Role(
            self,
            "WorkstationInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
            ],
        )
        
        # User data for workstation setup
        user_data_script = ec2.UserData.for_linux()
        self.create_workstation_userdata(user_data_script, workstation_config)
        
        # Map volume type
        volume_type_mapping = {
            "GP3": ec2.EbsDeviceVolumeType.GP3,
            "GP2": ec2.EbsDeviceVolumeType.GP2,
            "IO1": ec2.EbsDeviceVolumeType.IO1,
        }
        
        # Create workstation instance
        self.workstation_instance = ec2.Instance(
            self,
            "DevWorkstationInstance",
            instance_type=ec2.InstanceType.of(instance_class, instance_size),
            machine_image=machine_image,
            vpc=self.vpc,
            vpc_subnets=self.private_subnets,
            security_group=self.workstation_sg,
            role=self.workstation_role,
            key_pair=ec2.KeyPair.from_key_pair_name(
                self, "WorkstationKeyPair", key_name
            ) if key_name else None,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",  # Ubuntu root device
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=workstation_config.root_volume_size,
                        volume_type=volume_type_mapping.get(
                            workstation_config.root_volume_type, 
                            ec2.EbsDeviceVolumeType.GP3
                        ),
                        delete_on_termination=True,
                        encrypted=True,
                    )
                )
            ],
            user_data=user_data_script,
        )

    def create_workstation_userdata(self, user_data_script, workstation_config):
        """Create user data script for workstation setup"""
        
        user_data_script.add_commands(
            "#!/bin/bash",
            "set -e",
            "",
            "# Update system",
            "apt-get update -y",
            "apt-get upgrade -y",
            "",
            "# Install basic development tools",
            "apt-get install -y git curl wget vim htop tree unzip",
            "apt-get install -y build-essential python3-pip nodejs npm",
            "",
            "# Docker should already be installed from the AMI, but ensure it's running",
            "systemctl start docker",
            "systemctl enable docker",
            "usermod -a -G docker ubuntu",
            "",
            "# Install desktop environment (XFCE - lightweight)",
            "apt-get install -y xfce4 xfce4-goodies",
            "apt-get install -y firefox",
            "",
            "# Install VNC server",
            "apt-get install -y tightvncserver",
            "",
            "# Install development tools based on config",
        )
        
        # Install VSCode if configured
        if workstation_config.install_vscode:
            user_data_script.add_commands(
                "# Install Visual Studio Code",
                "wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > packages.microsoft.gpg",
                "install -o root -g root -m 644 packages.microsoft.gpg /etc/apt/trusted.gpg.d/",
                "sh -c 'echo \"deb [arch=amd64,arm64,armhf signed-by=/etc/apt/trusted.gpg.d/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main\" > /etc/apt/sources.list.d/vscode.list'",
                "apt-get update -y",
                "apt-get install -y code",
            )
        
        # Install IntelliJ if configured  
        if workstation_config.install_intellij:
            user_data_script.add_commands(
                "# Install IntelliJ IDEA Community Edition",
                "snap install intellij-idea-community --classic",
            )
        
        user_data_script.add_commands(
            "",
            "# Setup Apache Guacamole as Docker container",
            "mkdir -p /opt/guacamole",
            "cd /opt/guacamole",
            "",
            "# Create Guacamole docker-compose.yml",
            f"cat > docker-compose.yml << 'EOF'",
            "version: '3.8'",
            "services:",
            "  guacd:",
            "    image: guacamole/guacd:latest",
            "    container_name: guacd",
            "    restart: unless-stopped",
            "    volumes:",
            "      - guacd_data:/var/lib/guacamole",
            "  ",
            "  postgres:",
            "    image: postgres:13",
            "    container_name: guacamole_postgres",
            "    restart: unless-stopped",
            "    environment:",
            "      POSTGRES_DB: guacamole_db",
            "      POSTGRES_USER: guacamole_user", 
            "      POSTGRES_PASSWORD: guacamole_pass",
            "    volumes:",
            "      - postgres_data:/var/lib/postgresql/data",
            "  ",
            "  guacamole:",
            "    image: guacamole/guacamole:latest",
            "    container_name: guacamole",
            "    restart: unless-stopped",
            f"    ports:",
            f"      - '{workstation_config.guacamole_port}:8080'",
            "    environment:",
            "      GUACD_HOSTNAME: guacd",
            "      POSTGRES_HOSTNAME: postgres",
            "      POSTGRES_DATABASE: guacamole_db",
            "      POSTGRES_USER: guacamole_user",
            "      POSTGRES_PASSWORD: guacamole_pass",
            "    depends_on:",
            "      - guacd",
            "      - postgres",
            "",
            "volumes:",
            "  guacd_data:",
            "  postgres_data:",
            "EOF",
            "",
            "# Setup VNC server for ubuntu user",
            "sudo -u ubuntu bash << 'VNCSEOF'",
            f"mkdir -p /home/ubuntu/.vnc",
            f"echo 'vncpassword' | vncpasswd -f > /home/ubuntu/.vnc/passwd",
            f"chmod 600 /home/ubuntu/.vnc/passwd",
            f"cat > /home/ubuntu/.vnc/xstartup << 'XSTARTEOF'",
            "#!/bin/bash",
            "xrdb $HOME/.Xresources",
            "startxfce4 &",
            "XSTARTEOF",
            f"chmod +x /home/ubuntu/.vnc/xstartup",
            "VNCSEOF",
            "",
            "# Create systemd service for VNC",
            "cat > /etc/systemd/system/vncserver@.service << 'EOF'",
            "[Unit]",
            "Description=Start TightVNC server at startup",
            "After=syslog.target network.target",
            "",
            "[Service]",
            "Type=forking",
            "User=ubuntu",
            "Group=ubuntu",
            "WorkingDirectory=/home/ubuntu",
            "",
            "PIDFile=/home/ubuntu/.vnc/%H:%i.pid",
            f"ExecStartPre=-/usr/bin/vncserver -kill :%i > /dev/null 2>&1",
            f"ExecStart=/usr/bin/vncserver -depth 24 -geometry 1920x1080 :%i",
            f"ExecStop=/usr/bin/vncserver -kill :%i",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "EOF",
            "",
            "# Enable and start services",
            "systemctl daemon-reload",
            f"systemctl enable vncserver@1.service",
            f"systemctl start vncserver@1.service",
            "",
            "# Initialize Guacamole database and start containers",
            "cd /opt/guacamole",
            "docker-compose up -d postgres",
            "sleep 30",  # Wait for postgres to be ready
            "docker run --rm guacamole/guacamole /opt/guacamole/bin/initdb.sh --postgres > initdb.sql",
            "docker exec -i guacamole_postgres psql -U guacamole_user -d guacamole_db < initdb.sql",
            "docker-compose up -d",
            "",
            "# Create setup completion marker",
            "touch /home/ubuntu/workstation-setup-complete",
            "chown ubuntu:ubuntu /home/ubuntu/workstation-setup-complete",
            "",
            "echo 'Workstation setup completed successfully!' > /var/log/workstation-setup.log",
        )

# Don't forget to call this method in your __init__ method:
# Add this line after create_application_load_balancer():
# self.create_workstation_instance()

    def create_application_load_balancer(self):
        """Create Application Load Balancer for Guacamole access"""
        
        # Security Group for ALB
        self.alb_sg = ec2.SecurityGroup(
            self,
            "GuacamoleALBSecurityGroup",
            vpc=self.vpc,
            description="Security group for Guacamole Application Load Balancer",
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
            "GuacamoleLoadBalancer",
            vpc=self.vpc,
            internet_facing=True,
            security_group=self.alb_sg,
            vpc_subnets=self.public_subnets,
        )
        
        # Certificate for *.workstation.vadai.org
        self.certificate = acm.Certificate(
            self,
            "WorkstationWildcardCertificate",
            domain_name="*.workstation.vadai.org",
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
                message_body="Workstation not found"
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

    def create_target_groups(self):
        """Create target groups for Guacamole following DDEV pattern"""
        
        workstation_config = self.infra_config.workstation
        
        # Target group for Guacamole web interface (following DDEV pattern)
        self.guacamole_tg = elbv2.ApplicationTargetGroup(
            self,
            "GuacamoleTargetGroup",
            vpc=self.vpc,
            port=workstation_config.guacamole_port,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.INSTANCE,
            health_check=elbv2.HealthCheck(
                enabled=True,
                healthy_http_codes="200,302,404",
                path="/guacamole/",
                port=str(workstation_config.guacamole_port),
                protocol=elbv2.Protocol.HTTP,
                timeout=Duration.seconds(10),
                interval=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=5,
            ),
        )
        
        # Add listener rule for Guacamole access (following DDEV pattern)
        self.https_listener.add_action(
            "GuacamoleListenerRule",
            priority=10,
            conditions=[
                elbv2.ListenerCondition.host_headers(["guac.workstation.vadai.org"])
            ],
            action=elbv2.ListenerAction.forward([self.guacamole_tg])
        )

    def register_targets(self):
        """Register instance with target groups (separate method like DDEV)"""
        
        workstation_config = self.infra_config.workstation
        

    def add_workstation_outputs(self):
        """Add workstation-specific outputs"""
        
        workstation_config = self.infra_config.workstation
        
        CfnOutput(
            self,
            "GuacamoleURL",
            value="https://guac.workstation.vadai.org/guacamole/",
            description="Guacamole web interface URL",
        )
        
        CfnOutput(
            self,
            "WorkstationInstanceId",
            value=self.workstation_instance.instance_id,
            description="Dev workstation instance ID",
        )
        
        CfnOutput(
            self,
            "WorkstationPrivateIP",
            value=self.workstation_instance.instance_private_ip,
            description="Workstation instance private IP",
        )
        
        CfnOutput(
            self,
            "SSMConnectCommand",
            value=f"aws ssm start-session --target {self.workstation_instance.instance_id}",
            description="SSM command to connect to workstation",
        )
        
        CfnOutput(
            self,
            "WorkstationSpecs",
            value=f"{workstation_config.instance_class}.{workstation_config.instance_size} ({workstation_config.architecture}) - {workstation_config.root_volume_size}GB {workstation_config.root_volume_type}",
            description="Workstation specifications",
        )
        
        CfnOutput(
            self,
            "GuacamoleTargetGroupArn",
            value=self.guacamole_tg.target_group_arn,
            description="Guacamole target group ARN",
        )
        
        CfnOutput(
            self,
            "AccessInstructions",
            value="1. Wait 10-15 minutes for setup completion 2. Access via https://guac.workstation.vadai.org/guacamole/ 3. Default login: guacadmin/guacadmin 4. VNC password: vncpassword",
            description="How to access the workstation",
        )
        
        CfnOutput(
            self,
            "DevelopmentTools",
            value=f"VSCode: {workstation_config.install_vscode}, IntelliJ: {workstation_config.install_intellij}, Docker: {workstation_config.install_docker}",
            description="Installed development tools",
        )

    def create_outputs(self):
        """Create outputs for this step"""
        
        CfnOutput(
            self,
            "GuacamoleLoadBalancerDNS",
            value=self.alb.load_balancer_dns_name,
            description="Guacamole ALB DNS name",
        )
        
        CfnOutput(
            self,
            "WorkstationDomain",
            value="*.workstation.vadai.org → " + self.alb.load_balancer_dns_name,
            description="Domain pattern for workstation access",
        )
        
        CfnOutput(
            self,
            "VpcInfo",
            value=f"Using VPC: {self.vpc.vpc_id} from SimpleNetwork-{self.account_name}",
            description="VPC information",
        )
