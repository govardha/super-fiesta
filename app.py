#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.pipeline.pipeline_stack import OpnsenseLabPipelineStack

app = cdk.App()

deployment_account = app.node.try_get_context("deployment_account_id")
deployment_region = app.node.try_get_context("deployment_account_region")
sandbox_account = app.node.try_get_context("sandbox_account_id")

OpnsenseLabPipelineStack(
    app,
    "OpnsenseLabPipeline",
    sandbox_env=cdk.Environment(account=sandbox_account, region=deployment_region),
    env=cdk.Environment(account=deployment_account, region=deployment_region),
)

app.synth()
