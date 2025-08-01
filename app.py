#!/usr/bin/env python3
import os

import aws_cdk as cdk
from configs.config import AppConfigs

from stacks.super_fiesta.super_fiesta_stack import SuperFiestaStack
from stacks.vpc_endpoints.vpc_endpoints_stack import VpcInterfaceEndpointsStack

app = cdk.App()
# Load configuration to get the correct account/region
config_loader = AppConfigs()
infra_config = config_loader.get_infrastructure_info("sandbox")

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

app.synth()