from aws_cdk import (
    Stack,
    Environment,
    pipelines,
)
from constructs import Construct

from configs.constants import code_star_connection, gov_github_repo
from stages.opnsense_lab_stage import OpnsenseLabStage


class OpnsenseLabPipelineStack(Stack):
    """
    CDK Pipeline that deploys OpnsenseLabStack into the sandbox account.
    This stack itself lives in the deployment account.
    """

    def __init__(self, scope: Construct, construct_id: str, sandbox_env: Environment, **kwargs) -> None:
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
            synth=pipelines.ShellStep(
                "Synth",
                input=source,
                install_commands=[
                    "pip install -r requirements.txt",
                ],
                commands=[
                    "npx cdk synth",
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
