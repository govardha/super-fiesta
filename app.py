#!/usr/bin/env python3
import os

import aws_cdk as cdk

from configs.config import AppConfigs
from stacks.alma_asg.alma_asg_stack import AlmaASGStack
from stacks.compute.compute_stack import ComputeStack
from stacks.core_network.simple_network_stack import SimpleNetworkStack
from stacks.ddev_demo.ddev_demo_stack import DdevDemoStack
from stacks.super_fiesta.super_fiesta_stack import SuperFiestaStack
from stacks.vpc_endpoints.vpc_endpoints_stack import VpcInterfaceEndpointsStack

from stacks.pipeline.pipeline_stack import OpnsenseLabPipelineStack

app = cdk.App()

# Deployment account (where pipelines live)
deployment_account = app.node.try_get_context("deployment_account_id")
deployment_region = app.node.try_get_context("deployment_account_region")
sandbox_account = app.node.try_get_context("sandbox_account_id")

# Load configuration to get the correct account/region
config_loader = AppConfigs()
infra_config = config_loader.get_infrastructure_info("sandbox")

# Create the simple network stack first
simple_network = SimpleNetworkStack(
    app,
    "SimpleNetwork",
    account_name="sandbox",
    env=cdk.Environment(account=infra_config.account, region=infra_config.region),
)

# Create the compute stack (depends on SimpleNetwork)
compute_stack = ComputeStack(
    app,
    "ComputeStack",
    vpc=simple_network.vpc,  # Pass VPC directly from network stack
    account_name="sandbox",
    env=cdk.Environment(account=infra_config.account, region=infra_config.region),
)
# Ensure compute stack depends on network stack
compute_stack.add_dependency(simple_network)

if (
    infra_config.compute
    and infra_config.compute.asg
    and infra_config.compute.asg.enabled
):
    alma_asg = AlmaASGStack(
        app,
        "AlmaASGStack",
        vpc=simple_network.vpc,
        account_name="sandbox",
        notification_email=infra_config.compute.asg.notification_email
        or os.getenv("NOTIFICATION_EMAIL"),
        env=cdk.Environment(account=infra_config.account, region=infra_config.region),
    )
    alma_asg.add_dependency(simple_network)

# Original SuperFiesta Stack
SuperFiestaStack(app, "SuperFiestaStack")

# VPC Interface Endpoints Demo Stack
VpcInterfaceEndpointsStack(
    app,
    "VpcInterfaceEndpointsStack",
    account_name="sandbox",
    env=cdk.Environment(account=infra_config.account, region=infra_config.region),
)

# DDEV Demo Stack with fck-nat
DdevDemoStack(
    app,
    "DdevDemoStack",
    account_name="sandbox",
    env=cdk.Environment(account=infra_config.account, region=infra_config.region),
)

# OPNsense Lab Pipeline (lives in deployment account, deploys to sandbox)
OpnsenseLabPipelineStack(
    app,
    "OpnsenseLabPipeline",
    sandbox_env=cdk.Environment(account=sandbox_account, region=deployment_region),
    env=cdk.Environment(account=deployment_account, region=deployment_region),
)

app.synth()
