# File: stacks/ddev_demo/ddev_demo_stack.py

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_wafv2 as wafv2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_targets as elbv2_targets, 
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

        # Create WAF (if enabled in configuration)
        self.create_waf()
    
        # Associate WAF with ALB (after ALB is created)  
        self.associate_waf_with_alb()
        
        # Create EC2 instance with Ubuntu 24.04 and 20GB storage
        self.create_ddev_instance()
        
        # Create target groups
        self.create_target_groups()

        # Add after self.create_target_groups()
        self.create_guacamole_security_group() 
        self.create_guacamole_target_group()
        self.create_guacamole_listener_rule()
        self.create_guacamole_instance()

        self.add_guacamole_outputs()
        
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
            domain_name="*.webdev.vadai.org",
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
        
        # Allow traffic from ALB security group for port 80 (traefik router)
        self.ddev_sg.add_ingress_rule(
            peer=ec2.Peer.security_group_id(self.alb_sg.security_group_id),
            connection=ec2.Port.tcp(80),
             description="HTTP traffic from ALB to traefik router",
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
            "# Enable error handling and logging",
            "set -e",
            "exec > >(tee /var/log/user-data.log) 2>&1",
            "echo 'Starting user data script at $(date)'",
            "",
            "# Update package lists",
            "apt-get update -y",
            "",
            "# Install packages that we know work",
            "echo 'Installing core packages...'",
            "apt-get install -y \\",
            "    docker.io \\",
            "    docker-compose-plugin \\",
            "    nginx \\",
            "    python3-pip \\",
            "    unzip \\",
            "    curl \\",
            "    wget \\",
            "    ubuntu-desktop-minimal \\",
            "    xrdp \\",
            "    firefox \\",
            "    git",
            "",
            "# Install AWS CLI v2 (the way that actually works)",
            "echo 'Installing AWS CLI v2...'",
            "cd /tmp",
            'curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"',
            "unzip awscliv2.zip",
            "./aws/install",
            "rm -rf awscliv2.zip aws/",
            "",
            "# Configure Docker",
            "echo 'Configuring Docker...'",
            "systemctl start docker",
            "systemctl enable docker",
            "usermod -a -G docker ubuntu",
            "",
            "# Configure XRDP",
            "echo 'Configuring XRDP...'",
            "systemctl enable xrdp",
            "systemctl start xrdp",
            "",
            "# Set up proper XRDP config (the one that worked)",
            "cat > /etc/xrdp/xrdp.ini << 'XRDP_EOF'",
            "[Globals]",
            "ini_version=1",
            "fork=true",
            "port=3389",
            "tcp_nodelay=true",
            "tcp_keepalive=true",
            "security_layer=rdp",
            "crypt_level=none",
            "certificate=",
            "key_file=",
            "ssl_protocols=TLSv1.2, TLSv1.3",
            "autorun=",
            "allow_channels=true",
            "allow_multimon=true",
            "bitmap_cache=true",
            "bitmap_compression=true",
            "bulk_compression=true",
            "",
            "[Logging]",
            "LogFile=xrdp.log",
            "LogLevel=INFO",
            "EnableSyslog=true",
            "",
            "[Channels]",
            "rdpdr=true",
            "rdpsnd=true",
            "drdynvc=true",
            "cliprdr=true",
            "rail=true",
            "xrdpvr=true",
            "tcutils=true",
            "",
            "[xrdp1]",
            "name=sesman-Xvnc",
            "lib=libvnc.so",
            "username=ask",
            "password=ask",
            "ip=127.0.0.1",
            "port=-1",
            "xserverbpp=24",
            "",
            "[xrdp2]",
            "name=sesman-X11rdp",
            "lib=libxrdp.so",
            "username=ask",
            "password=ask",
            "ip=127.0.0.1",
            "port=-1",
            "xserverbpp=24",
            "",
            "[xrdp3]",
            "name=sesman-Xorg",
            "lib=libxrdp.so",
            "username=ask",
            "password=ask",
            "ip=127.0.0.1",
            "port=-1",
            "xserverbpp=24",
            "XRDP_EOF",
            "",
            "# Restart XRDP with new config",
            "systemctl restart xrdp",
            "",
            "# Set up ubuntu user for RDP",
            "echo 'Setting up ubuntu user...'",
            "echo 'ubuntu:test123' | chpasswd",
            "",
            "# Configure desktop environment for ubuntu user",
            "sudo -u ubuntu bash << 'USER_SETUP'",
            "cd /home/ubuntu",
            "echo 'gnome-session' > .xsession",
            "chmod +x .xsession",
            "mkdir -p Desktop Documents Downloads",
            "USER_SETUP",
            "",
            "# Create simple health check",
            "mkdir -p /var/www/html",
            "cat > /var/www/html/index.html << 'HTML_EOF'",
            "<h1>Guacamole Instance Ready</h1>",
            f"<p>Instance Type: {self.infra_config.ec2.instance_type}</p>",
            "<p>Storage: 20GB GP3</p>",  # Or use actual values from your config
            "<p>Status: Ready for development!</p>",
            "HTML_EOF",
            "",
            "# Configure nginx",
            "cat > /etc/nginx/sites-available/default << 'NGINX_EOF'",
            "server {",
            "    listen 8080 default_server;",
            "    listen [::]:8080 default_server;",
            "    root /var/www/html;",
            "    index index.html index.htm;",
            "    server_name _;",
            "    location / {",
            "        try_files $uri $uri/ =404;",
            "    }",
            "}",
            "NGINX_EOF",
            "",
            "# Start nginx",
            "systemctl start nginx",
            "systemctl enable nginx",
            "# Create completion marker",
            "touch /home/ubuntu/setup-complete",
            "chown ubuntu:ubuntu /home/ubuntu/setup-complete",
            "",
            "echo 'User data script completed successfully at $(date)'",
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
            """Create single target group for traefik router"""
            
            # Single target group for traefik router on port 80
            self.traefik_tg = elbv2.ApplicationTargetGroup(
                self,
                "TraefikTargetGroup",
                vpc=self.vpc,
                port=80,
                protocol=elbv2.ApplicationProtocol.HTTP,
                target_type=elbv2.TargetType.INSTANCE,
                health_check=elbv2.HealthCheck(
                    enabled=True,
                    healthy_http_codes="200,404",
                    path="/",  # Traefik will handle health checks
                    port="80",
                    protocol=elbv2.Protocol.HTTP,
                    timeout=Duration.seconds(5),
                    interval=Duration.seconds(30),
                    healthy_threshold_count=2,
                    unhealthy_threshold_count=5,
                ),
            )
            
            # Catch-all listener rule for *.webdev.vadai.org
            self.https_listener.add_action(
                "TraefikListenerRule",
                priority=10,  # Lower number = higher priority (changed from 100 to 10)
                conditions=[
                    elbv2.ListenerCondition.host_headers(["*.webdev.vadai.org"])
                ],
                action=elbv2.ListenerAction.forward([self.traefik_tg])
            )

    def create_waf(self):
        """Create WAF v2 Web ACL with IP allow list, country blocking, and managed rules"""
        
        if not self.infra_config.waf or not self.infra_config.waf.enabled:
            return None
        
        waf_config = self.infra_config.waf
        rules = []
        priority = 1
        
        # IP Allow List Rule (highest priority - these IPs always get through)
        if waf_config.allowed_ips and waf_config.allowed_ips != ["0.0.0.0/0"]:
            # Create IP set for allowed IPs
            self.allowed_ip_set = wafv2.CfnIPSet(
                self,
                "AllowedIPSet",
                addresses=waf_config.allowed_ips,
                ip_address_version="IPV4",
                scope="REGIONAL",
                name=f"{waf_config.name}-AllowedIPs",
                description="Allowed IP addresses - always permitted",
            )
            
            # Rule to allow IPs in the allow list (highest priority)
            rules.append(wafv2.CfnWebACL.RuleProperty(
                name="AllowedIPsRule",
                priority=priority,
                statement=wafv2.CfnWebACL.StatementProperty(
                    ip_set_reference_statement=wafv2.CfnWebACL.IPSetReferenceStatementProperty(
                        arn=self.allowed_ip_set.attr_arn
                    )
                ),
                action=wafv2.CfnWebACL.RuleActionProperty(allow={}),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    sampled_requests_enabled=waf_config.sampled_requests_enabled,
                    cloud_watch_metrics_enabled=waf_config.cloudwatch_metrics_enabled,
                    metric_name=f"{waf_config.name}-AllowedIPs",
                ),
            ))
            priority += 1
        
        # Country Blocking Rule (second priority - block before other processing)
        if waf_config.blocked_countries:
            rules.append(wafv2.CfnWebACL.RuleProperty(
                name="BlockedCountriesRule",
                priority=priority,
                statement=wafv2.CfnWebACL.StatementProperty(
                    geo_match_statement=wafv2.CfnWebACL.GeoMatchStatementProperty(
                        country_codes=waf_config.blocked_countries
                    )
                ),
                action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    sampled_requests_enabled=waf_config.sampled_requests_enabled,
                    cloud_watch_metrics_enabled=waf_config.cloudwatch_metrics_enabled,
                    metric_name=f"{waf_config.name}-BlockedCountries",
                ),
            ))
            priority += 1
        
        # AWS Managed Rules (using correct names from CLI)
        managed_rules = []
        
        if waf_config.aws_common_rule_set:
            managed_rules.append(("AWSManagedRulesCommonRuleSet", "AWSManagedRulesCommonRuleSet"))
        
        if waf_config.aws_known_bad_inputs:
            managed_rules.append(("AWSManagedRulesKnownBadInputsRuleSet", "AWSManagedRulesKnownBadInputsRuleSet"))
        
        if waf_config.aws_sql_injection:
            managed_rules.append(("AWSManagedRulesSQLiRuleSet", "AWSManagedRulesSQLiRuleSet"))
        
        # Add managed rule groups
        for rule_name, rule_group in managed_rules:
            rules.append(wafv2.CfnWebACL.RuleProperty(
                name=rule_name,
                priority=priority,
                override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                statement=wafv2.CfnWebACL.StatementProperty(
                    managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                        vendor_name="AWS",
                        name=rule_group,
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    sampled_requests_enabled=waf_config.sampled_requests_enabled,
                    cloud_watch_metrics_enabled=waf_config.cloudwatch_metrics_enabled,
                    metric_name=f"{waf_config.name}-{rule_name}",
                ),
            ))
            priority += 1
        
        # Rate limiting rule (if enabled)
        if waf_config.aws_rate_limiting:
            rules.append(wafv2.CfnWebACL.RuleProperty(
                name="RateLimitRule",
                priority=priority,
                statement=wafv2.CfnWebACL.StatementProperty(
                    rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                        limit=waf_config.rate_limit_requests,
                        aggregate_key_type="IP",
                    )
                ),
                action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    sampled_requests_enabled=waf_config.sampled_requests_enabled,
                    cloud_watch_metrics_enabled=waf_config.cloudwatch_metrics_enabled,
                    metric_name=f"{waf_config.name}-RateLimit",
                ),
            ))
        
        # Custom response for blocked requests
        custom_response_body = """<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Access Denied</title>
        <style>
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; margin: 0; padding: 40px; text-align: center; min-height: 100vh;
                display: flex; align-items: center; justify-content: center;
            }
            .container { 
                background: rgba(255,255,255,0.1); padding: 40px; border-radius: 20px; 
                backdrop-filter: blur(15px); border: 1px solid rgba(255,255,255,0.2);
                max-width: 600px; box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            }
            h1 { font-size: 3em; margin-bottom: 20px; }
            .shield { font-size: 4em; margin-bottom: 20px; }
            .reason { background: rgba(255,255,255,0.2); padding: 15px; border-radius: 10px; margin: 20px 0; }
            .contact { margin-top: 30px; font-size: 0.9em; opacity: 0.8; }
            .timestamp { font-family: monospace; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="shield">🛡️</div>
            <h1>Access Denied</h1>
            <p>Your request has been blocked by our Web Application Firewall.</p>
            <div class="reason">
                <strong>Possible reasons:</strong><br>
                • Geographic restrictions (RU, CN, KP blocked)<br>
                • IP address not in allow list<br>
                • Suspicious request pattern detected<br>
                • Rate limiting threshold exceeded
            </div>
            <p>If you believe this is an error, please contact the site administrator.</p>
            <div class="contact">
                <div class="timestamp">Blocked at: <span id="currentTime"></span></div>
                <div>Protected by AWS WAF • DDEV Demo Stack</div>
            </div>
        </div>
        <script>
            // Set current timestamp in the browser
            const now = new Date();
            const dateString = now.toISOString().split('T')[0]; // Gets YYYY-MM-DD part
            document.getElementById('currentTime').textContent = dateString;;
        </script>
    </body>
    </html>"""

        # Default action with custom response: 
        # - If we have IP allow list: BLOCK everything else (whitelist mode)
        # - If no IP restrictions: ALLOW (managed rules will block bad traffic)
        if waf_config.allowed_ips and waf_config.allowed_ips != ["0.0.0.0/0"]:
            default_action = wafv2.CfnWebACL.DefaultActionProperty(
                block=wafv2.CfnWebACL.BlockActionProperty(
                    custom_response=wafv2.CfnWebACL.CustomResponseProperty(
                        response_code=403,
                        custom_response_body_key="AccessDeniedPage"
                    )
                )
            )
        else:
            default_action = wafv2.CfnWebACL.DefaultActionProperty(allow={})
        
        # Create the Web ACL
        self.web_acl = wafv2.CfnWebACL(
            self,
            "DdevWebACL",
            scope="REGIONAL",
            default_action=default_action,
            name=waf_config.name,
            description=waf_config.description,
            rules=rules,
            # Custom response bodies
            custom_response_bodies={
                "AccessDeniedPage": wafv2.CfnWebACL.CustomResponseBodyProperty(
                    content_type="TEXT_HTML",
                    content=custom_response_body
                )
            },
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=waf_config.sampled_requests_enabled,
                cloud_watch_metrics_enabled=waf_config.cloudwatch_metrics_enabled,
                metric_name=waf_config.name,
            ),
        )
        
        return self.web_acl

    # Add this method to associate WAF with ALB:
    def associate_waf_with_alb(self):
        """Associate WAF with Application Load Balancer"""
        
        if not hasattr(self, 'web_acl') or not self.web_acl:
            return
        
        # Associate Web ACL with ALB
        self.waf_association = wafv2.CfnWebACLAssociation(
            self,
            "WAFALBAssociation",
            resource_arn=self.alb.load_balancer_arn,
            web_acl_arn=self.web_acl.attr_arn,
        )

    def create_guacamole_security_group(self):
        """Create security group for Guacamole instance"""
        
        self.guacamole_sg = ec2.SecurityGroup(
            self,
            "GuacamoleSecurityGroup",
            vpc=self.vpc,
            description="Security group for Apache Guacamole instance",
            allow_all_outbound=True,
        )
        
        # Allow HTTP from ALB security group (Guacamole web interface)
        self.guacamole_sg.add_ingress_rule(
            peer=ec2.Peer.security_group_id(self.alb_sg.security_group_id),
            connection=ec2.Port.tcp(8080),
            description="HTTP from ALB to Guacamole web interface",
        )
        
        # Allow SSH from within VPC (for management)
        self.guacamole_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(22),
            description="SSH from within VPC",
        )


    def create_guacamole_target_group(self):
        """Create target group for Guacamole"""
        
        self.guacamole_tg = elbv2.ApplicationTargetGroup(
            self,
            "GuacamoleTargetGroup",
            vpc=self.vpc,
            port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.INSTANCE,
            health_check=elbv2.HealthCheck(
                enabled=True,
                healthy_http_codes="200",
                path="/guacamole/",  # Guacamole default path
                port="8080",
                protocol=elbv2.Protocol.HTTP,
                timeout=Duration.seconds(10),
                interval=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=5,
            ),
        )
    
    def create_guacamole_listener_rule(self):
        """Add listener rule for Guacamole subdomain"""
        self.https_listener.add_action(
            "GuacamoleListenerRule",
            priority=5,  # Higher priority than traefik (lower number = higher priority)
            conditions=[
                elbv2.ListenerCondition.host_headers(["guac.webdev.vadai.org"])
            ],
            action=elbv2.ListenerAction.forward([self.guacamole_tg])
    )


    
    def add_guacamole_outputs(self):
        """Add outputs for Guacamole resources"""
        
        guac_config = self.infra_config.guacamole or self.infra_config.ec2
        
        # ... your existing outputs ...
        
        CfnOutput(
            self,
            "GuacamoleSpecs",
            value=f"Instance: {guac_config.instance_type}, Storage: {guac_config.ebs_volume_size}GB {guac_config.ebs_volume_type}",
            description="Guacamole instance specifications",
        )
        
        CfnOutput(
            self,
            "GuacamoleMonitoring",
            value="Enabled" if guac_config.enable_monitoring else "Disabled",
            description="Detailed monitoring status",
        )
    
        
    def create_guacamole_instance(self):
        """Create EC2 instance for Apache Guacamole using configuration"""
        
        # Get Guacamole-specific configuration
        guac_config = self.infra_config.guacamole
        if not guac_config:
            guac_config = self.infra_config.ec2
        
        # Get AMI and key configuration
        ami_id = getattr(guac_config, 'ami_id', None) or getattr(self.infra_config.ec2, 'ami_id', None)
        key_name = getattr(self.infra_config.ec2, 'key_name', None)
        
        # Choose machine image
        if ami_id:
            machine_image = ec2.MachineImage.generic_linux({self.region: ami_id})
        else:
            machine_image = ec2.MachineImage.latest_ubuntu(
                generation=ec2.UbuntuGeneration.UBUNTU_24_04,
            )
        
        # Map configuration to CDK enums
        instance_class_mapping = {
            "BURSTABLE2": ec2.InstanceClass.BURSTABLE2,
            "BURSTABLE3": ec2.InstanceClass.BURSTABLE3,
            "BURSTABLE4_GRAVITON": ec2.InstanceClass.BURSTABLE4_GRAVITON,
            "STANDARD5": ec2.InstanceClass.STANDARD5,
            "MEMORY5": ec2.InstanceClass.MEMORY5,
            "COMPUTE5": ec2.InstanceClass.COMPUTE5,
        }
        
        instance_size_mapping = {
            "NANO": ec2.InstanceSize.NANO,
            "MICRO": ec2.InstanceSize.MICRO,
            "SMALL": ec2.InstanceSize.SMALL,
            "MEDIUM": ec2.InstanceSize.MEDIUM,
            "LARGE": ec2.InstanceSize.LARGE,
            "XLARGE": ec2.InstanceSize.XLARGE,
            "XLARGE2": ec2.InstanceSize.XLARGE2,
            "XLARGE4": ec2.InstanceSize.XLARGE4,
        }
        
        volume_type_mapping = {
            "GP2": ec2.EbsDeviceVolumeType.GP2,
            "GP3": ec2.EbsDeviceVolumeType.GP3,
            "IO1": ec2.EbsDeviceVolumeType.IO1,
            "IO2": ec2.EbsDeviceVolumeType.IO2,
        }
        
        # Get instance specifications from config
        instance_class = instance_class_mapping.get(guac_config.instance_class, ec2.InstanceClass.BURSTABLE3)
        instance_size = instance_size_mapping.get(guac_config.instance_size, ec2.InstanceSize.MEDIUM)
        volume_type = volume_type_mapping.get(guac_config.ebs_volume_type, ec2.EbsDeviceVolumeType.GP3)
        
        # User data script (following DDEV pattern)
        user_data_script = ec2.UserData.for_linux()
        user_data_script.add_commands(
            "#!/bin/bash",
            "apt-get update -y",
            "apt-get install -y docker.io docker-compose-v2 nginx awscli",
            "systemctl start docker",
            "systemctl enable docker",
            "usermod -a -G docker ubuntu",
            "",
            "# Create simple health check for testing",
            "mkdir -p /var/www/html",
            "cat > /var/www/html/index.html << 'EOF'",
            "<h1>Guacamole Instance Ready</h1>",
            "<p>Instance is running and ready for Guacamole installation</p>",
            f"<p>Instance Type: {guac_config.instance_type}</p>",
            f"<p>Storage: {guac_config.ebs_volume_size}GB {guac_config.ebs_volume_type}</p>",
            "EOF",
            "",
            "# Configure nginx to serve on port 8080 temporarily",
            "cat > /etc/nginx/sites-available/default << 'EOF'",
            "server {",
            "    listen 8080 default_server;",
            "    root /var/www/html;",
            "    index index.html;",
            "    location / {",
            "        try_files $uri $uri/ =404;",
            "    }",
            "}",
            "EOF",
            "",
            "systemctl restart nginx",
            "systemctl enable nginx",
            "",
            "# Auto-register with target group (following DDEV pattern)",
            f"INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)",
            f"TARGET_GROUP_ARN='{self.guacamole_tg.target_group_arn}'",
            f"aws elbv2 register-targets --target-group-arn $TARGET_GROUP_ARN --targets Id=$INSTANCE_ID,Port=8080 --region {self.region}",
        )
        
        # Create the instance (NO target registration in CDK)
        self.guacamole_instance = ec2.Instance(
            self,
            "GuacamoleInstance",
            instance_type=ec2.InstanceType.of(instance_class, instance_size),
            machine_image=machine_image,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_group=self.guacamole_sg,
            role=self.ddev_role,  # Reuse existing role that has ELB permissions
            key_pair=ec2.KeyPair.from_key_pair_name(self, "GuacamoleKeyPair", key_name) if key_name else None,
            user_data=user_data_script,
            detailed_monitoring=guac_config.enable_monitoring,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=guac_config.ebs_volume_size,
                        volume_type=volume_type,
                        delete_on_termination=True,
                        encrypted=False,
                    )
                )
            ],
        )
        
        # NO target registration here - it's done via user data script
        # This follows the same pattern as your DDEV instance

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
            "TraefikTargetGroupArn",
            value=self.traefik_tg.target_group_arn,
            description="Traefik Router Target Group ARN",
        )

        CfnOutput(
            self,
            "TraefikInfo",
            value="All *.webdev.vadai.org requests route to traefik on port 80",
            description="Traefik routing information",
        )

        CfnOutput(
            self,
            "ExampleSites",
            value="Example: qa1.webdev.vadai.org, qa2.webdev.vadai.org, qa99.webdev.vadai.org",
            description="Example site URLs that will route through traefik",
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
                # WAF Outputs (only if WAF is enabled)
        if hasattr(self, 'web_acl') and self.web_acl:
            CfnOutput(
                self,
                "WebACLArn",
                value=self.web_acl.attr_arn,
                description="WAF Web ACL ARN",
            )
            
            # Output WAF configuration summary
            waf_features = []
            if self.infra_config.waf.allowed_ips:
                waf_features.append(f"IP Allow List ({len(self.infra_config.waf.allowed_ips)} IPs)")
            if self.infra_config.waf.aws_common_rule_set:
                waf_features.append("Common Rules")
            if self.infra_config.waf.aws_sql_injection:
                waf_features.append("SQLi Protection")
            if self.infra_config.waf.aws_xss_protection:
                waf_features.append("XSS Protection")
            if self.infra_config.waf.aws_rate_limiting:
                waf_features.append(f"Rate Limiting ({self.infra_config.waf.rate_limit_requests}/5min)")
            
            CfnOutput(
                self,
                "WAFFeatures",
                value=", ".join(waf_features) if waf_features else "Basic WAF",
                description="Enabled WAF features",
            )
            
            CfnOutput(
                self,
                "WAFDefaultAction",
                value="BLOCK (IP whitelist mode)" if self.infra_config.waf.allowed_ips else "ALLOW (managed rules mode)",
                description="WAF default action behavior",
            )
        else:
            CfnOutput(
                self,
                "WAFStatus",
                value="WAF is disabled in configuration",
                description="WAF Configuration Status",
            )
