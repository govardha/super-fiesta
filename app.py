#!/usr/bin/env python3
import aws_cdk as cdk

from configs.config import AppConfigs
from stacks.opnsense_lab.network_stack import OpnsenseLabNetworkStack
from stacks.opnsense_lab.compute_stack import OpnsenseLabComputeStack
from stacks.pipeline.pipeline_stack import OpnsenseLabPipelineStack

app = cdk.App()

deployment_account = app.node.try_get_context("deployment_account_id")
deployment_region = app.node.try_get_context("deployment_account_region")
sandbox_account = app.node.try_get_context("sandbox_account_id")

config_loader = AppConfigs()
infra_config = config_loader.get_infrastructure_info("sandbox")
sandbox_env = cdk.Environment(account=infra_config.account, region=infra_config.region)

# Direct deploy targets — stack names match what the pipeline created
network = OpnsenseLabNetworkStack(app, "OpnsenseLabNetwork", account_name="sandbox", env=sandbox_env)
OpnsenseLabComputeStack(app, "OpnsenseLabCompute", network=network, account_name="sandbox", env=sandbox_env)

# Pipeline (deploy separately when ready)
OpnsenseLabPipelineStack(
    app,
    "OpnsenseLabPipeline",
    sandbox_env=cdk.Environment(account=sandbox_account, region=deployment_region),
    env=cdk.Environment(account=deployment_account, region=deployment_region),
)

app.synth()
