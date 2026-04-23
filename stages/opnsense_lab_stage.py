from constructs import Construct
from aws_cdk import Stage, Environment

from stacks.opnsense_lab.opnsense_lab_stack import OpnsenseLabStack


class OpnsenseLabStage(Stage):
    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        OpnsenseLabStack(self, "OpnsenseLabStack", account_name=account_name, env=kwargs.get("env"))
