from constructs import Construct
from aws_cdk import Stage, Environment

from stacks.opnsense_lab.network_stack import OpnsenseLabNetworkStack
from stacks.opnsense_lab.compute_stack import OpnsenseLabComputeStack


class OpnsenseLabStage(Stage):
    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = kwargs.get("env")
        network = OpnsenseLabNetworkStack(
            self, "OpnsenseLabNetwork",
            stack_name="SandboxDeploy-OpnsenseLabNetwork",
            account_name=account_name, env=env,
        )
        OpnsenseLabComputeStack(
            self, "OpnsenseLabCompute",
            stack_name="SandboxDeploy-OpnsenseLabCompute",
            network=network, account_name=account_name, env=env,
        )
