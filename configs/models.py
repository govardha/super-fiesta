# File: configs/models.py

from dataclasses import dataclass, field


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
    ami_id: str | None = None
    key_name: str | None = None


@dataclass
class ComputeInstanceConfig:
    """Configuration for a single compute instance - simple and minimal"""

    name: str
    instance_type: str  # Direct EC2 instance type like "t3.medium", "m5.large"
    ebs_volume_size: int = 100  # GB
    ebs_volume_type: str = "GP3"  # GP3, GP2, IO1, IO2, etc.
    ebs_iops: int | None = None  # For GP3, IO1, IO2
    ebs_throughput: int | None = None  # For GP3 only (MiB/s)
    os: str = "almalinux"
    os_version: str = "9"  # 8 or 9 for AlmaLinux
    subnet_type: str = "PRIVATE_WITH_EGRESS"  # or PUBLIC
    use_spot: bool = False
    spot_max_price: str | None = None
    spot_interruption_behavior: str = "terminate"
    data_volume_size: int | None = None  # GB for separate data volume
    data_volume_type: str = "GP3"
    data_volume_mount_point: str = "/data"
    data_volume_device_name: str = "/dev/sdf"


@dataclass
class ASGConfig:
    """Configuration for Auto Scaling Group"""

    enabled: bool = False
    primary_instance_type: str = "m5.large"
    alternative_instance_types: list[str] = field(default_factory=list)
    min_capacity: int = 1
    max_capacity: int = 1
    desired_capacity: int = 1
    on_demand_percentage: int = 20  # 0-100, percentage of on-demand vs spot
    health_check_grace_period: int = 300  # seconds
    notification_email: str | None = None
    # Automatic refresh configuration
    enable_daily_refresh: bool = False  # Auto-refresh to optimize spot pricing
    refresh_hour: int = 3  # UTC hour for daily refresh (0-23)
    refresh_only_on_demand: bool = True  # Only refresh if instance is on-demand
    enable_aggressive_spot_refresh: bool = False
    aggressive_refresh_interval_minutes: int = 15


@dataclass
class ComputeConfig:
    """Configuration for compute instances"""

    instances: list[ComputeInstanceConfig] = field(default_factory=list)
    almalinux_amis: dict[str, dict[str, str]] = field(default_factory=dict)
    asg: ASGConfig | None = None


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
    services: list[EndpointService]


@dataclass
class WafConfig:
    enabled: bool = False
    name: str = "DdevWaf"
    description: str = "WAF for DDEV Demo"
    cloudwatch_metrics_enabled: bool = True
    sampled_requests_enabled: bool = True
    allowed_ips: list[str] = field(default_factory=list)
    blocked_countries: list[str] = field(default_factory=list)
    aws_common_rule_set: bool = True
    aws_known_bad_inputs: bool = True
    aws_sql_injection: bool = True
    aws_xss_protection: bool = True
    aws_rate_limiting: bool = False
    rate_limit_requests: int = 2000


@dataclass
class InfrastructureSpec:
    account: str
    region: str
    vpc: VpcConfig | None = None
    ec2: Ec2Config | None = None
    compute: ComputeConfig | None = None
    logging: LoggingConfig | None = None
    endpoints: EndpointsConfig | None = None
    waf: WafConfig | None = None
