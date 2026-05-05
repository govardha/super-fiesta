from aws_cdk import (
    Environment,
    Stack,
    pipelines,
)
from aws_cdk import (
    aws_iam as iam,
)
from constructs import Construct

from configs.constants import code_star_connection, gov_github_repo
from stages.opnsense_lab_stage import OpnsenseLabStage


class OpnsenseLabPipelineStack(Stack):
    """
    CDK Pipeline that deploys OpnsenseLabStack into the sandbox account.
    This stack itself lives in the deployment account.
    """

    def __init__(
        self, scope: Construct, construct_id: str, sandbox_env: Environment, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        source = pipelines.CodePipelineSource.connection(
            gov_github_repo,
            "feature/opnsense-lab",
            connection_arn=code_star_connection,
        )

        pipeline = pipelines.CodePipeline(
            self,
            "OpnsenseLabPipeline",
            pipeline_name="OpnsenseLab",
            synth=pipelines.CodeBuildStep(
                "Synth",
                input=source,
                install_commands=[
                    "pip install -r requirements.txt",
                ],
                commands=[
                    "npx cdk synth",
                ],
                env={
                    "SANDBOX_ACCOUNT_ID": sandbox_env.account,
                    "SANDBOX_REGION": sandbox_env.region,
                },
                role_policy_statements=[
                    iam.PolicyStatement(
                        actions=["sts:AssumeRole"],
                        resources=[
                            f"arn:aws:iam::{sandbox_env.account}:role/cdk-govjuly25-*"
                        ],
                    ),
                ],
            ),
            cross_account_keys=True,
        )

        pipeline.add_stage(
            OpnsenseLabStage(
                self,
                "SandboxDeploy",
                account_name="sandbox",
                env=sandbox_env,
            )
        )
