# Stacks Directory Structure and Lambda Integration README

## Directory Architecture

### Current Stacks Organization
```
stacks/
├── core_network/
│   └── simple_network_stack.py      # Shared VPC infrastructure
├── ddev_demo/
│   └── ddev_demo_stack.py           # DDEV development environment
├── super_fiesta/
│   ├── __init__.py
│   └── super_fiesta_stack.py        # Template/placeholder stack
└── vpc_endpoints/
    └── vpc_endpoints_stack.py       # VPC interface endpoints demo
```

## Stack Design Patterns

### 1. Configuration-Driven Stack Pattern
All stacks follow this pattern for consistency and maintainability:

```python
class DdevDemoStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # 1. Load configuration from infrastructure.yaml
        self.config_loader = AppConfigs()
        self.infra_config: InfrastructureSpec = self.config_loader.get_infrastructure_info(account_name)

        # 2. Create resources using configuration
        self.create_vpc()
        self.create_application_load_balancer()
        self.create_ec2_instance()
        
        # 3. Create outputs for cross-stack references
        self.create_outputs()
```

### 2. Method Organization Pattern
Each stack organizes functionality into focused methods:

```python
class ExampleStack(Stack):
    def __init__(self, ...):
        # Main orchestration
        self.create_network_infrastructure()
        self.create_compute_resources()
        self.create_security_components()
        self.create_outputs()
    
    def create_network_infrastructure(self):
        """Create VPC, subnets, security groups"""
        pass
    
    def create_compute_resources(self):
        """Create EC2, Auto Scaling, Load Balancers"""
        pass
    
    def create_security_components(self):
        """Create IAM roles, WAF, security groups"""
        pass
    
    def create_outputs(self):
        """Create CloudFormation outputs for cross-stack references"""
        pass
```

## Individual Stack Analysis

### 1. Core Network Stack (`core_network/`)

**Purpose**: Shared network infrastructure foundation

```python
class SimpleNetworkStack(Stack):
    """
    Simple shared network stack following DDEV pattern:
    - Uses infrastructure.yaml for all configuration
    - Creates VPC with public/private subnets
    - Uses fck-nat following exact DDEV stack pattern
    - Internet Gateway
    - Code and config completely separate
    """
```

**Key Features:**
- **Shared VPC**: Can be used by other stacks
- **fck-nat**: Cost-optimized NAT instance ($3/month vs $45/month NAT Gateway)
- **Cross-stack exports**: VPC ID, subnet IDs for other stacks to import

**Method Structure:**
```python
def create_vpc(self):
    # Creates VPC with fck-nat provider
    # Follows exact same pattern as DDEV stack
    
def create_outputs(self):
    # Exports VPC details for cross-stack references
    export_name=f"SimpleNetwork-{self.account_name}-VpcId"
```

### 2. DDEV Demo Stack (`ddev_demo/`)

**Purpose**: Complete web development environment platform

**Key Components:**
- **Application Load Balancer**: Routes *.webdev.vadai.org traffic
- **WAF Protection**: Country blocking, IP allow lists, managed rules
- **EC2 Instance**: Ubuntu 24.04 with DDEV pre-configured
- **Traefik Router**: Container routing for multiple sites

**Method Structure:**
```python
def create_vpc(self):
    # VPC with fck-nat for cost optimization
    
def create_application_load_balancer(self):
    # ALB with HTTPS termination and wildcard SSL
    
def create_waf(self):
    # WAF v2 with configurable rules
    
def create_ddev_instance(self):
    # EC2 with DDEV, Docker, development tools
    
def create_target_groups(self):
    # Single target group for Traefik router
```

### 3. VPC Endpoints Stack (`vpc_endpoints/`)

**Purpose**: Demonstrates private AWS API access without internet routing

**Key Features:**
- **Interface Endpoints**: SSM, EC2, STS, CloudWatch Logs
- **Private DNS**: Automatic resolution to private IPs
- **Test Instance**: Pre-configured with testing scripts
- **Flow Logs**: Network traffic monitoring

**Method Structure:**
```python
def create_vpc_endpoints(self):
    # Creates VPC interface endpoints based on configuration
    
def create_ec2_role(self):
    # IAM role for EC2 with necessary permissions
    
def create_test_instance(self):
    # EC2 instance with testing scripts
```

## Adding Lambda Functions to Stacks

### 1. Lambda Integration Pattern

Create a new stack with Lambda functions:

```python
# stacks/lambda_services/lambda_services_stack.py
from aws_cdk import (
    Stack,
    aws_lambda as lambda_,
    aws_apigateway as apigateway,
    aws_iam as iam,
    Duration,
)

class LambdaServicesStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # Load configuration
        self.config_loader = AppConfigs()
        self.infra_config = self.config_loader.get_infrastructure_info(account_name)
        
        # Create Lambda functions
        self.create_lambda_functions()
        self.create_api_gateway()
        self.create_outputs()
    
    def create_lambda_functions(self):
        """Create Lambda functions"""
        
        # Lambda execution role
        self.lambda_role = iam.Role(
            self,
            "LambdaExecutionRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
            ],
        )
        
        # Hello World Lambda
        self.hello_lambda = lambda_.Function(
            self,
            "HelloWorldFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            code=lambda_.Code.from_inline("""
import json
import boto3

def handler(event, context):
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'message': 'Hello from Lambda!',
            'environment': event.get('environment', 'unknown'),
            'account': context.invoked_function_arn.split(':')[4]
        })
    }
            """),
            role=self.lambda_role,
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "ENVIRONMENT": self.infra_config.account,
                "REGION": self.infra_config.region,
            }
        )
        
        # Data Processing Lambda
        self.processor_lambda = lambda_.Function(
            self,
            "DataProcessorFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="processor.handler",
            code=lambda_.Code.from_asset("lambda_code/processor"),  # External code
            role=self.lambda_role,
            timeout=Duration.seconds(300),
            memory_size=512,
        )
    
    def create_api_gateway(self):
        """Create API Gateway for Lambda functions"""
        
        # REST API
        self.api = apigateway.RestApi(
            self,
            "LambdaAPI",
            rest_api_name="Lambda Services API",
            description="API for Lambda functions",
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=apigateway.Cors.ALL_METHODS,
            )
        )
        
        # Hello endpoint
        hello_resource = self.api.root.add_resource("hello")
        hello_integration = apigateway.LambdaIntegration(self.hello_lambda)
        hello_resource.add_method("GET", hello_integration)
        
        # Processor endpoint
        processor_resource = self.api.root.add_resource("process")
        processor_integration = apigateway.LambdaIntegration(self.processor_lambda)
        processor_resource.add_method("POST", processor_integration)
```

### 2. Lambda Code Organization

Create directory structure for Lambda code:

```
lambda_code/
├── processor/
│   ├── processor.py         # Main handler
│   ├── requirements.txt     # Dependencies
│   └── utils/
│       └── helper.py        # Utility functions
├── authorizer/
│   ├── authorizer.py
│   └── requirements.txt
└── shared/
    └── common_utils.py      # Shared utilities
```

**Example Lambda function:**
```python
# lambda_code/processor/processor.py
import json
import boto3
import os
from utils.helper import process_data

def handler(event, context):
    """
    Process incoming data and return results
    """
    try:
        # Get environment configuration
        environment = os.environ.get('ENVIRONMENT', 'sandbox')
        
        # Parse input
        body = json.loads(event.get('body', '{}'))
        data = body.get('data', [])
        
        # Process data
        result = process_data(data)
        
        # Return response
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'processed_data': result,
                'environment': environment,
                'processed_count': len(result)
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'error': str(e),
                'message': 'Processing failed'
            })
        }
```

### 3. Lambda with VPC Integration

For Lambda functions that need VPC access:

```python
def create_vpc_lambda(self):
    """Create Lambda function with VPC access"""
    
    # Import shared VPC (if using cross-stack references)
    vpc_id = Fn.import_value("SimpleNetwork-sandbox-VpcId")
    vpc = ec2.Vpc.from_lookup(self, "SharedVpc", vpc_id=vpc_id)
    
    # Security group for Lambda
    lambda_sg = ec2.SecurityGroup(
        self,
        "LambdaSecurityGroup",
        vpc=vpc,
        description="Security group for Lambda functions",
        allow_all_outbound=True,
    )
    
    # VPC Lambda function
    self.vpc_lambda = lambda_.Function(
        self,
        "VpcLambdaFunction",
        runtime=lambda_.Runtime.PYTHON_3_11,
        handler="vpc_handler.handler",
        code=lambda_.Code.from_asset("lambda_code/vpc_function"),
        role=self.lambda_role,
        vpc=vpc,
        vpc_subnets=ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        ),
        security_groups=[lambda_sg],
        timeout=Duration.seconds(30),
    )
```

### 4. Lambda Environment-Specific Configuration

Add Lambda configuration to `infrastructure.yaml`:

```yaml
# Add to infrastructure.yaml
globals:
  lambda:
    runtime: "python3.11"
    timeout_seconds: 30
    memory_size: 128
    log_retention_days: 7
    
accounts:
  - name: production
    lambda:
      memory_size: 512        # More memory for production
      timeout_seconds: 300    # Longer timeout
      log_retention_days: 30  # Longer log retention
```

**Configuration model in `models.py`:**
```python
@dataclass
class LambdaConfig:
    runtime: str = "python3.11"
    timeout_seconds: int = 30
    memory_size: int = 128
    log_retention_days: int = 7
    enable_vpc: bool = False
```

## Stack Method Patterns

### 1. Resource Creation Methods

**Naming Convention:**
- `create_*()` for creating AWS resources
- `configure_*()` for setting up configurations
- `setup_*()` for complex multi-step processes

**Example patterns:**
```python
def create_security_groups(self):
    """Create all security groups for the stack"""
    
    # ALB Security Group
    self.alb_sg = ec2.SecurityGroup(
        self,
        "ALBSecurityGroup",
        vpc=self.vpc,
        description="Security group for Application Load Balancer",
        allow_all_outbound=True,
    )
    
    # Application Security Group
    self.app_sg = ec2.SecurityGroup(
        self,
        "ApplicationSecurityGroup", 
        vpc=self.vpc,
        description="Security group for application servers",
        allow_all_outbound=True,
    )
    
    # Configure security group rules
    self.configure_security_group_rules()

def configure_security_group_rules(self):
    """Configure security group ingress/egress rules"""
    
    # ALB allows HTTP/HTTPS from internet
    self.alb_sg.add_ingress_rule(
        peer=ec2.Peer.any_ipv4(),
        connection=ec2.Port.tcp(80),
        description="HTTP from internet",
    )
    
    # Application servers allow traffic from ALB
    self.app_sg.add_ingress_rule(
        peer=ec2.Peer.security_group_id(self.alb_sg.security_group_id),
        connection=ec2.Port.tcp(80),
        description="HTTP from ALB",
    )
```

### 2. Conditional Resource Creation

```python
def create_optional_resources(self):
    """Create resources based on configuration"""
    
    # Create WAF only if enabled
    if self.infra_config.waf and self.infra_config.waf.enabled:
        self.create_waf()
        self.associate_waf_with_alb()
    
    # Create Lambda functions only for certain environments
    if self.account_name in ["production", "staging"]:
        self.create_lambda_functions()
    
    # Create monitoring only if configured
    if hasattr(self.infra_config, 'monitoring') and self.infra_config.monitoring.enabled:
        self.create_cloudwatch_dashboards()
```

### 3. Configuration Mapping Methods

```python
def map_configuration_to_cdk(self):
    """Map configuration strings to CDK enums"""
    
    # Instance type mapping
    instance_class_mapping = {
        "BURSTABLE2": ec2.InstanceClass.BURSTABLE2,
        "BURSTABLE3": ec2.InstanceClass.BURSTABLE3,
        "STANDARD5": ec2.InstanceClass.STANDARD5,
        "MEMORY5": ec2.InstanceClass.MEMORY5,
    }
    
    instance_size_mapping = {
        "NANO": ec2.InstanceSize.NANO,
        "MICRO": ec2.InstanceSize.MICRO,
        "SMALL": ec2.InstanceSize.SMALL,
        "MEDIUM": ec2.InstanceSize.MEDIUM,
        "LARGE": ec2.InstanceSize.LARGE,
    }
    
    # Convert configuration to CDK types
    self.instance_class = instance_class_mapping.get(
        self.infra_config.ec2.instance_class, 
        ec2.InstanceClass.BURSTABLE3
    )
    
    self.instance_size = instance_size_mapping.get(
        self.infra_config.ec2.instance_size,
        ec2.InstanceSize.MICRO
    )
```

## Cross-Stack Integration Patterns

### 1. Exporting Values for Cross-Stack Use

```python
def create_outputs(self):
    """Create CloudFormation outputs for cross-stack references"""
    
    # Export VPC details
    CfnOutput(
        self,
        "VpcId",
        value=self.vpc.vpc_id,
        description="VPC ID for cross-stack reference",
        export_name=f"SimpleNetwork-{self.account_name}-VpcId",
    )
    
    # Export Lambda function ARNs
    CfnOutput(
        self,
        "ProcessorLambdaArn",
        value=self.processor_lambda.function_arn,
        description="Data processor Lambda function ARN",
        export_name=f"LambdaServices-{self.account_name}-ProcessorArn",
    )
```

### 2. Importing Cross-Stack References

```python
# In another stack
from aws_cdk import Fn

def import_shared_resources(self):
    """Import resources from other stacks"""
    
    # Import VPC from SimpleNetworkStack
    vpc_id = Fn.import_value(f"SimpleNetwork-{self.account_name}-VpcId")
    self.shared_vpc = ec2.Vpc.from_lookup(self, "SharedVpc", vpc_id=vpc_id)
    
    # Import Lambda function ARN
    lambda_arn = Fn.import_value(f"LambdaServices-{self.account_name}-ProcessorArn")
    self.processor_function = lambda_.Function.from_function_arn(
        self, "ImportedProcessor", lambda_arn
    )
```

## Advanced Stack Patterns

### 1. Stack Dependencies

**Explicit dependencies:**
```python
# In app.py
network_stack = SimpleNetworkStack(app, "SimpleNetwork")
lambda_stack = LambdaServicesStack(app, "LambdaServices")
api_stack = ApiGatewayStack(app, "ApiGateway", 
                           lambda_functions=lambda_stack.functions)

# Create explicit dependency
api_stack.add_dependency(lambda_stack)
```

### 2. Stack Parameters

```python
class ParameterizedStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, 
                 vpc: ec2.Vpc, 
                 lambda_functions: dict,
                 **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # Use passed-in resources
        self.vpc = vpc
        self.lambda_functions = lambda_functions
```

### 3. Stack Composition Pattern

```python
class CompositeStack(Stack):
    """Stack that combines multiple logical components"""
    
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # Create foundation
        self.create_network_foundation()
        
        # Create application layers
        self.create_data_layer()
        self.create_application_layer()
        self.create_presentation_layer()
        
        # Create cross-cutting concerns
        self.create_monitoring()
        self.create_security()
    
    def create_data_layer(self):
        """Create databases, storage"""
        pass
    
    def create_application_layer(self):
        """Create Lambda functions, containers"""
        pass
    
    def create_presentation_layer(self):
        """Create API Gateway, CloudFront"""
        pass
```

## Testing Stack Methods

### 1. Unit Testing Individual Methods

```python
# tests/unit/test_stack_methods.py
import aws_cdk as cdk
from stacks.lambda_services.lambda_services_stack import LambdaServicesStack

def test_lambda_creation():
    app = cdk.App()
    stack = LambdaServicesStack(app, "TestStack", account_name="sandbox")
    
    # Test that Lambda function was created
    template = cdk.assertions.Template.from_stack(stack)
    template.has_resource_properties("AWS::Lambda::Function", {
        "Runtime": "python3.11",
        "Handler": "index.handler"
    })
```

### 2. Integration Testing

```python
def test_stack_integration():
    app = cdk.App()
    
    # Create dependent stacks
    network_stack = SimpleNetworkStack(app, "Network")
    lambda_stack = LambdaServicesStack(app, "Lambda")
    
    # Verify cross-stack references work
    template = cdk.assertions.Template.from_stack(lambda_stack)
    template.has_output("ProcessorLambdaArn")
```

This stack architecture provides a solid foundation for building complex, maintainable AWS CDK applications with proper separation of concerns, configuration management, and cross-stack integration capabilities.
