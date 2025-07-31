from dataclasses import dataclass
from constructs import Construct
from aws_cdk import Stage, Environment
import boto3
from typing import List

@dataclass
class InfrastructureStageProps:
    account_name: str
    audit_account_id: str
    region: str
    # Add Prowler configuration
    management_account_id: str = ""
    enable_prowler: bool = False

class InfrastructureStage(Stage):
    def __init__(
        self, scope: Construct, id: str, props: InfrastructureStageProps, **kwargs
    ):
        super().__init__(scope, id, **kwargs)
        
        # Always deploy something to ensure stage has at least one stack
        stacks_deployed = False
