#!/usr/bin/env python3
import os

import aws_cdk as cdk
from configs.config import AppConfigs

from stacks.super_fiesta.super_fiesta_stack import SuperFiestaStack
from stacks.vpc_endpoints.vpc_endpoints_stack import VpcInterfaceEndpointsStack

app = cdk.App()
SuperFiestaStack(app, "SuperFiestaStack",)
VpcInterfaceEndpointsStack(
    app, 
    "VpcInterfaceEndpointsStack",
    env=cdk.Environment(
        account=os.getenv('CDK_DEFAULT_ACCOUNT'), 
        region=os.getenv('CDK_DEFAULT_REGION')
    ),
)


app.synth()
