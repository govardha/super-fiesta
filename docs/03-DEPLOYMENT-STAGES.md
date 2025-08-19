# Stages Directory and Deployment Pipeline README

## Overview
The stages directory implements CDK's Stage construct for managing complex, multi-environment deployments with proper dependency management and progressive deployment strategies.

## Current Stages Architecture

### Directory Structure
```
stages/
└── infrastructure_stage.py    # Main infrastructure deployment stage
```

### Infrastructure Stage Implementation
```python
@dataclass
class InfrastructureStageProps:
    account_name: str           # Environment name (sandbox, production, development)
    audit_account_id: str       # Account for audit/compliance
    region: str                 # AWS region
    management_account_id: str = ""     # Management account (optional)
    enable_prowler: bool = False        # Security scanning (optional)

class InfrastructureStage(Stage):
    def __init__(self, scope: Construct, id: str, props: InfrastructureStageProps, **kwargs):
        super().__init__(scope, id, **kwargs)
        
        # Always deploy something to ensure stage has at least one stack
        stacks_deployed = False
```

## Enhanced Stages Implementation

### 1. Complete Infrastructure Stage

Let's enhance the current stage to deploy all stacks:

```python
# stages/infrastructure_stage.py
from dataclasses import dataclass
from constructs import Construct
from aws_cdk import Stage, Environment, Tags
import boto3
from typing import List, Optional

from stacks.core_network.simple_network_stack import SimpleNetworkStack
from stacks.ddev_demo.ddev_demo_stack import DdevDemoStack
from stacks.vpc_endpoints.vpc_endpoints_stack import VpcInterfaceEndpointsStack
from stacks.lambda_services.lambda_services_stack import LambdaServicesStack

@dataclass
class InfrastructureStageProps:
    account_name: str                    # Environment identifier
    account_id: str                      # AWS Account ID
    region: str                          # AWS Region
    audit_account_id: str = ""           # Audit account
    management_account_id: str = ""      # Management account
    enable_prowler: bool = False         # Security scanning
    enable_vpc_endpoints: bool = True    # VPC endpoints stack
    enable_ddev: bool = True             # DDEV development stack
    enable_lambda_services: bool = False # Lambda services stack
    stack_prefix: str = ""               # Optional prefix for stack names

class InfrastructureStage(Stage):
    """
    Infrastructure deployment stage that manages all application stacks
    for a specific environment (sandbox, production, development)
    """
    
    def __init__(self, scope: Construct, id: str, props: InfrastructureStageProps, **kwargs):
        super().__init__(scope, id, **kwargs)
        
        self.props = props
        self.stacks = {}
        
        # Create environment for all stacks in this stage
        self.env = Environment(
            account=props.account_id,
            region=props.region
        )
        
        # Deploy stacks in dependency order
        self.deploy_foundation_stacks()
        self.deploy_application_stacks()
        self.deploy_optional_stacks()
        
        # Apply common tags to all resources in this stage
        self.apply_stage_tags()
    
    def deploy_foundation_stacks(self):
        """Deploy foundational infrastructure stacks"""
        
        # Core network infrastructure (foundation for other stacks)
        self.stacks['network'] = SimpleNetworkStack(
            self,
            f"{self.props.stack_prefix}SimpleNetwork",
            account_name=self.props.account_name,
            env=self.env,
        )
    
    def deploy_application_stacks(self):
        """Deploy application-specific stacks"""
        
        # DDEV development environment
        if self.props.enable_ddev:
            self.stacks['ddev'] = DdevDemoStack(
                self,
                f"{self.props.stack_prefix}DdevDemo",
                account_name=self.props.account_name,
                env=self.env,
            )
    
    def deploy_optional_stacks(self):
        """Deploy optional/feature stacks based on configuration"""
        
        # VPC endpoints for secure AWS API access
        if self.props.enable_vpc_endpoints:
            self.stacks['vpc_endpoints'] = VpcInterfaceEndpointsStack(
                self,
                f"{self.props.stack_prefix}VpcEndpoints",
                account_name=self.props.account_name,
                env=self.env,
            )
        
        # Lambda services (API endpoints, processing functions)
        if self.props.enable_lambda_services:
            self.stacks['lambda_services'] = LambdaServicesStack(
                self,
                f"{self.props.stack_prefix}LambdaServices",
                account_name=self.props.account_name,
                # Pass VPC from network stack for VPC Lambda functions
                vpc=self.stacks['network'].vpc,
                env=self.env,
            )
            
            # Create explicit dependency
            self.stacks['lambda_services'].add_dependency(self.stacks['network'])
    
    def apply_stage_tags(self):
        """Apply consistent tags to all resources in this stage"""
        
        Tags.of(self).add("Environment", self.props.account_name)
        Tags.of(self).add("Stage", self.node.id)
        Tags.of(self).add("ManagedBy", "CDK")
        Tags.of(self).add("Region", self.props.region)
        
        if self.props.audit_account_id:
            Tags.of(self).add("AuditAccount", self.props.audit_account_id)
```

### 2. Multi-Environment Stage Configuration

Create stage configurations for different environments:

```python
# stages/stage_config.py
from dataclasses import dataclass
from typing import Dict, Any
import os

@dataclass
class StageConfig:
    """Configuration for a deployment stage"""
    account_name: str
    account_id: str
    region: str
    enable_ddev: bool = True
    enable_vpc_endpoints: bool = True
    enable_lambda_services: bool = False
    stack_prefix: str = ""
    
    # Security settings
    enable_prowler: bool = False
    audit_account_id: str = ""
    
    # Cost optimization settings
    use_nat_gateway: bool = False  # Use fck-nat instead
    
    @classmethod
    def from_environment_variables(cls, account_name: str) -> 'StageConfig':
        """Create stage config from environment variables"""
        
        env_mapping = {
            "sandbox": {
                "account_id_var": "SANDBOX_ACCOUNT_ID",
                "region_var": "SANDBOX_REGION",
                "enable_lambda_services": False,
            },
            "production": {
                "account_id_var": "PRODUCTION_ACCOUNT_ID", 
                "region_var": "PRODUCTION_REGION",
                "enable_lambda_services": True,
                "enable_prowler": True,
                "stack_prefix": "Prod-",
            },
            "development": {
                "account_id_var": "DEV_ACCOUNT_ID",
                "region_var": "DEV_REGION",
                "enable_lambda_services": False,
                "stack_prefix": "Dev-",
            }
        }
        
        config = env_mapping.get(account_name, {})
        
        return cls(
            account_name=account_name,
            account_id=os.environ[config["account_id_var"]],
            region=os.environ[config["region_var"]],
            enable_lambda_services=config.get("enable_lambda_services", False),
            enable_prowler=config.get("enable_prowler", False),
            stack_prefix=config.get("stack_prefix", ""),
        )

class StageConfigManager:
    """Manage stage configurations for all environments"""
    
    @staticmethod
    def get_all_stage_configs() -> Dict[str, StageConfig]:
        """Get configurations for all defined stages"""
        
        stages = {}
        
        for env_name in ["sandbox", "production", "development"]:
            try:
                stages[env_name] = StageConfig.from_environment_variables(env_name)
            except KeyError as e:
                print(f"Skipping {env_name} stage - missing environment variable: {e}")
        
        return stages
    
    @staticmethod
    def get_stage_config(account_name: str) -> StageConfig:
        """Get configuration for a specific stage"""
        return StageConfig.from_environment_variables(account_name)
```

### 3. Pipeline Integration with Stages

```python
# stages/deployment_pipeline.py
from aws_cdk import (
    Stack,
    pipelines as pipelines,
    aws_codebuild as codebuild,
    aws_iam as iam,
)
from constructs import Construct
from stages.infrastructure_stage import InfrastructureStage, InfrastructureStageProps
from stages.stage_config import StageConfigManager

class DeploymentPipelineStack(Stack):
    """
    CDK Pipeline for deploying infrastructure across multiple environments
    """
    
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # Create the pipeline
        self.pipeline = pipelines.CodePipeline(
            self,
            "InfrastructurePipeline",
            pipeline_name="SuperFiestaInfrastructure",
            
            # Source configuration
            synth=pipelines.ShellStep(
                "Synth",
                input=pipelines.CodePipelineSource.connection(
                    repo_string="govardha/super-fiesta",
                    branch="main",
                    connection_arn="arn:aws:codeconnections:us-east-1:766789219588:connection/edbc6e08-9fa9-4c2e-9d09-8dd228a3b370"
                ),
                commands=[
                    "npm install -g aws-cdk",
                    "pip install -r requirements.txt",
                    "cdk synth"
                ],
                primary_output_directory="cdk.out"
            ),
            
            # Build configuration
            code_build_defaults=pipelines.CodeBuildOptions(
                build_environment=codebuild.BuildEnvironment(
                    build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                    compute_type=codebuild.ComputeType.SMALL,
                )
            )
        )
        
        # Add deployment stages
        self.add_deployment_stages()
    
    def add_deployment_stages(self):
        """Add deployment stages for each environment"""
        
        stage_configs = StageConfigManager.get_all_stage_configs()
        
        # Development stage (deploys first for testing)
        if "development" in stage_configs:
            dev_config = stage_configs["development"]
            dev_stage = InfrastructureStage(
                self,
                "Development",
                InfrastructureStageProps(
                    account_name=dev_config.account_name,
                    account_id=dev_config.account_id,
                    region=dev_config.region,
                    enable_ddev=dev_config.enable_ddev,
                    enable_vpc_endpoints=dev_config.enable_vpc_endpoints,
                    enable_lambda_services=dev_config.enable_lambda_services,
                    stack_prefix=dev_config.stack_prefix,
                )
            )
            
            self.pipeline.add_stage(
                dev_stage,
                pre=[
                    pipelines.ShellStep(
                        "DevValidation",
                        commands=[
                            "echo 'Running development validation'",
                            "python -m pytest tests/unit/ -v",
                        ]
                    )
                ]
            )
        
        # Sandbox stage (parallel with development)
        if "sandbox" in stage_configs:
            sandbox_config = stage_configs["sandbox"]
            sandbox_stage = InfrastructureStage(
                self,
                "Sandbox",
                InfrastructureStageProps(
                    account_name=sandbox_config.account_name,
                    account_id=sandbox_config.account_id,
                    region=sandbox_config.region,
                    enable_ddev=sandbox_config.enable_ddev,
                    enable_vpc_endpoints=sandbox_config.enable_vpc_endpoints,
                    enable_lambda_services=sandbox_config.enable_lambda_services,
                )
            )
            
            self.pipeline.add_stage(sandbox_stage)
        
        # Production stage (deploys after sandbox with approval)
        if "production" in stage_configs:
            prod_config = stage_configs["production"]
            prod_stage = InfrastructureStage(
                self,
                "Production",
                InfrastructureStageProps(
                    account_name=prod_config.account_name,
                    account_id=prod_config.account_id,
                    region=prod_config.region,
                    enable_ddev=False,  # No DDEV in production
                    enable_vpc_endpoints=prod_config.enable_vpc_endpoints,
                    enable_lambda_services=prod_config.enable_lambda_services,
                    enable_prowler=prod_config.enable_prowler,
                    stack_prefix=prod_config.stack_prefix,
                )
            )
            
            self.pipeline.add_stage(
                prod_stage,
                pre=[
                    pipelines.ManualApprovalStep("PromoteToProduction"),
                    pipelines.ShellStep(
                        "ProdValidation",
                        commands=[
                            "echo 'Running production validation'",
                            "python -m pytest tests/integration/ -v",
                            "python scripts/security_check.py",
                        ]
                    )
                ],
                post=[
                    pipelines.ShellStep(
                        "ProductionSmokeTests",
                        commands=[
                            "echo 'Running production smoke tests'",
                            "python scripts/smoke_tests.py --environment production",
                        ]
                    )
                ]
            )
```

### 4. Cross-Account Deployment

For cross-account deployments, create account-specific stages:

```python
# stages/cross_account_stage.py
class CrossAccountInfrastructureStage(Stage):
    """
    Stage for deploying to external AWS accounts with cross-account roles
    """
    
    def __init__(self, scope: Construct, id: str, 
                 target_account: str, 
                 target_region: str,
                 cross_account_role: str,
                 **kwargs):
        
        # Configure cross-account environment
        env = Environment(
            account=target_account,
            region=target_region
        )
        
        super().__init__(scope, id, env=env, **kwargs)
        
        # Deploy stacks with cross-account role
        self.deploy_with_cross_account_role(cross_account_role)
    
    def deploy_with_cross_account_role(self, role_arn: str):
        """Deploy stacks using cross-account role"""
        
        # Create stacks that assume the cross-account role
        network_stack = SimpleNetworkStack(
            self,
            "CrossAccountNetwork",
            account_name="external",
        )
        
        # Add role assumption to stack's execution role
        # (Implementation depends on your cross-account setup)
```

## Stage Usage Patterns

### 1. Single Environment Deployment

```python
# app.py - Deploy single environment
from stages.infrastructure_stage import InfrastructureStage, InfrastructureStageProps
from stages.stage_config import StageConfigManager

app = cdk.App()

# Get configuration for specific environment
config = StageConfigManager.get_stage_config("sandbox")

# Create single stage
stage = InfrastructureStage(
    app,
    "SandboxInfrastructure", 
    InfrastructureStageProps(
        account_name=config.account_name,
        account_id=config.account_id,
        region=config.region,
        enable_ddev=config.enable_ddev,
        enable_vpc_endpoints=config.enable_vpc_endpoints,
        enable_lambda_services=config.enable_lambda_services,
    )
)

app.synth()
```

### 2. Multi-Environment Deployment

```python
# app.py - Deploy multiple environments
app = cdk.App()

# Get all stage configurations
stage_configs = StageConfigManager.get_all_stage_configs()

# Deploy to all configured environments
for env_name, config in stage_configs.items():
    stage = InfrastructureStage(
        app,
        f"{env_name.title()}Infrastructure",
        InfrastructureStageProps(
            account_name=config.account_name,
            account_id=config.account_id,
            region=config.region,
            enable_ddev=config.enable_ddev,
            enable_vpc_endpoints=config.enable_vpc_endpoints,
            enable_lambda_services=config.enable_lambda_services,
            stack_prefix=config.stack_prefix,
        )
    )

app.synth()
```

### 3. Pipeline-Based Deployment

```python
# app.py - Pipeline deployment
from stages.deployment_pipeline import DeploymentPipelineStack

app = cdk.App()

# Create deployment pipeline
pipeline_stack = DeploymentPipelineStack(
    app,
    "SuperFiestaPipeline",
    env=Environment(
        account="766789219588",  # Management account
        region="us-east-1"
    )
)

app.synth()
```

## Stage Testing and Validation

### 1. Stage Unit Tests

```python
# tests/unit/test_stages.py
import aws_cdk as cdk
from stages.infrastructure_stage import InfrastructureStage, InfrastructureStageProps

def test_infrastructure_stage_creation():
    app = cdk.App()
    
    stage = InfrastructureStage(
        app,
        "TestStage",
        InfrastructureStageProps(
            account_name="sandbox",
            account_id="123456789012",
            region="us-east-1"
        )
    )
    
    # Verify stage contains expected stacks
    assert "SimpleNetwork" in [stack.node.id for stack in stage.node.children]
```

### 2. Integration Tests

```python
# tests/integration/test_stage_deployment.py
def test_stage_deployment():
    """Test that stage deploys successfully"""
    
    # Deploy to test account
    result = subprocess.run([
        "cdk", "deploy", "TestStage/*", "--require-approval", "never"
    ], capture_output=True, text=True)
    
    assert result.returncode == 0
    assert "successfully" in result.stdout.lower()
```

## Deployment Commands

### Stage-Specific Deployment

```bash
# Deploy specific stage
cdk deploy SandboxInfrastructure/*

# Deploy specific stack within stage
cdk deploy SandboxInfrastructure/SimpleNetwork

# Deploy all stages
cdk deploy --all

# Deploy with approval bypass
cdk deploy SandboxInfrastructure/* --require-approval never
```

### Pipeline Deployment

```bash
# Deploy the pipeline itself
cdk deploy SuperFiestaPipeline

# Pipeline will automatically deploy stages based on configuration
# Check pipeline status in AWS Console
```

This stages architecture provides a robust foundation for managing complex, multi-environment deployments with proper dependency management, configuration separation, and progressive deployment strategies.
