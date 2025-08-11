# File: configs/models.py

from dataclasses import dataclass
from typing import List, Optional
@dataclass
class VpcConfig:
    cidr: str
    max_azs: int = 2
    subnet_mask: int = 24
    enable_dns_hostnames: bool = True
    enable_dns_support: bool = True
    nat_gateways: int = 0

@dataclass
class Ec2Config:
    instance_type: str
    instance_class: str = "BURSTABLE3"
    instance_size: str = "MICRO"
    amazon_linux_edition: str = "STANDARD"
    virtualization: str = "HVM"
    storage: str = "GENERAL_PURPOSE"
    ami_id: Optional[str] = None  # Custom AMI ID override
    key_name: Optional[str] = None  # SSH key pair name

@dataclass
class LoggingConfig:
    flow_logs_group_name: str = "/aws/vpc/flowlogs"
    retention_days: int = 7

@dataclass
class EndpointService:
    name: str
    service: str

@dataclass
class EndpointsConfig:
    services: List[EndpointService]

@dataclass
class WafConfig:
    enabled: bool = False
    name: str = "DdevWaf"
    description: str = "WAF for DDEV Demo"
    cloudwatch_metrics_enabled: bool = True
    sampled_requests_enabled: bool = True
    # IP Allow List
    allowed_ips: List[str] = None
    allowed_fqdns: List[str] = None
    # Country Blocking (ISO 3166-1 alpha-2 country codes)
    blocked_countries: List[str] = None
    # AWS Managed Rule Controls
    aws_common_rule_set: bool = True
    aws_known_bad_inputs: bool = True
    aws_sql_injection: bool = True
    aws_xss_protection: bool = True  # Will map to Common Rule Set
    aws_rate_limiting: bool = False
    rate_limit_requests: int = 2000  # requests per 5 minutes
    
    def __post_init__(self):
        if self.allowed_ips is None:
            self.allowed_ips = []
        if self.blocked_countries is None:
            self.blocked_countries = []


@dataclass
class GuacamoleConfig:
    instance_type: str = "t3.medium"
    instance_class: str = "BURSTABLE3"
    instance_size: str = "MEDIUM"
    ebs_volume_size: int = 30  # GB
    ebs_volume_type: str = "GP3"
    enable_monitoring: bool = True
    # Optional: separate AMI for Guacamole if needed
    ami_id: Optional[str] = None
@dataclass
class WorkstationConfig:
    """Configuration for dev workstation instances"""
    # Instance configuration
    instance_class: str = "BURSTABLE3"
    instance_size: str = "MEDIUM"
    architecture: str = "x86_64"  # or "arm64"
    
    # Storage configuration
    root_volume_size: int = 10  # GB
    root_volume_type: str = "GP3"
    
    # Service ports
    guacamole_port: int = 8080
    vnc_port: int = 5901
    rdp_port: int = 3389
    
    # Domain configuration
    domain_pattern: str = "*.workstation.vadai.org"
    
    # Development tools (what to install)
    install_vscode: bool = False
    install_intellij: bool = False
    install_docker: bool = True

@dataclass
class CognitoConfig:
    user_pool_name: str = "GuacamolePool"
    domain_prefix: str = "guacamole-auth"
    callback_urls: List[str] = None  
    logout_urls: List[str] = None
    saml_provider_name: str = "Zitadel"
    saml_metadata_url: str = "https://dev-ugeino.us1.zitadel.cloud/saml/v2/metadata"
    oidc_provider_name: str = "ZitadelOidc"
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_issuer_url: Optional[str] = None
    attribute_mapping: dict = None

@dataclass
class InfrastructureSpec:
    account: str
    region: str
    vpc: Optional[VpcConfig] = None
    ec2: Optional[Ec2Config] = None
    logging: Optional[LoggingConfig] = None
    guacamole: Optional[GuacamoleConfig] = None  
    endpoints: Optional[EndpointsConfig] = None
    waf: Optional[WafConfig] = None
    cognito: Optional[CognitoConfig] = None
    workstation: Optional[WorkstationConfig] = None  
