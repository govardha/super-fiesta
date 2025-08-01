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
class InfrastructureSpec:
    account: str
    region: str
    vpc: Optional[VpcConfig] = None
    ec2: Optional[Ec2Config] = None
    logging: Optional[LoggingConfig] = None
    endpoints: Optional[EndpointsConfig] = None