#!/usr/bin/env python3
import os

import aws_cdk as cdk
from configs.config import AppConfigs

from stacks.super_fiesta.super_fiesta_stack import SuperFiestaStack
from stacks.core_network.simple_network_stack import SimpleNetworkStack
from stacks.vpc_endpoints.vpc_endpoints_stack import VpcInterfaceEndpointsStack
from stacks.ddev_demo.ddev_demo_stack import DdevDemoStack
from stacks.guacamole_workstation.guacamole_workstation_stack import GuacamoleWorkstationStack

app = cdk.App()
# Load configuration to get the correct account/region
config_loader = AppConfigs()
infra_config = config_loader.get_infrastructure_info("sandbox")

# Create the simple network stack first
simple_network = SimpleNetworkStack(
    app, 
    "SimpleNetwork",
    env=cdk.Environment(
        account=infra_config.account,  # Use account from config
        region=infra_config.region     # Use region from config
    ),
)


# Original SuperFiesta Stack
SuperFiestaStack(app, "SuperFiestaStack")

# VPC Interface Endpoints Demo Stack
VpcInterfaceEndpointsStack(
    app, 
    "VpcInterfaceEndpointsStack",
    account_name="sandbox",
    env=cdk.Environment(
        account=infra_config.account,  # Use account from config
        region=infra_config.region     # Use region from config
    ),
)

# DDEV Demo Stack with fck-nat
DdevDemoStack(
    app, 
    "DdevDemoStack",
    account_name="sandbox",
    env=cdk.Environment(
        account=infra_config.account,
        region=infra_config.region
    ),
)

# Guacamole Workstation Stack (uses SimpleNetwork VPC)
guacamole_stack = GuacamoleWorkstationStack(
    app, 
    "GuacamoleWorkstationStack",
    account_name="sandbox",
    env=cdk.Environment(
        account=infra_config.account,
        region=infra_config.region
    ),
)

guacamole_stack.add_dependency(simple_network)

app.synth()