# Main Application Structure (app.py) README

## Overview
The `app.py` file serves as the entry point for your AWS CDK application. It orchestrates the deployment of multiple stacks and manages their dependencies, configurations, and environments.

## Architecture Pattern

### 1. Configuration-First Approach
```python
# Load configuration to get the correct account/region
config_loader = AppConfigs()
infra_config = config_loader.get_infrastructure_info("sandbox")
```

The application follows a configuration-first pattern where:
- All infrastructure parameters are defined in `configs/infrastructure.yaml`
- Environment-specific settings (sandbox, production, development) are loaded dynamically
- Account IDs and regions are pulled from environment variables or `.env` files

### 2. Stack Organization

The application deploys four main stacks:

#### a) SimpleNetworkStack (Core Infrastructure)
```python
simple_network = SimpleNetworkStack(
    app, 
    "SimpleNetwork",
    env=cdk.Environment(
        account=infra_config.account,
        region=infra_config.region
    ),
)
```
- **Purpose**: Provides shared network infrastructure
- **Features**: VPC with public/private subnets, fck-nat for cost optimization
- **Dependencies**: None (deployed first)

#### b) SuperFiestaStack (Legacy/Template)
```python
SuperFiestaStack(app, "SuperFiestaStack")
```
- **Purpose**: Template stack for future development
- **Features**: Minimal placeholder stack
- **Dependencies**: None

#### c) VpcInterfaceEndpointsStack (VPC Endpoints Demo)
```python
VpcInterfaceEndpointsStack(
    app, 
    "VpcInterfaceEndpointsStack",
    account_name="sandbox",
    env=cdk.Environment(
        account=infra_config.account,
        region=infra_config.region
    ),
)
```
- **Purpose**: Demonstrates VPC interface endpoints for AWS services
- **Features**: Private subnets with endpoints for SSM, EC2, STS, CloudWatch
- **Use Case**: Secure AWS API access without internet routing

#### d) DdevDemoStack (DDEV Development Environment)
```python
DdevDemoStack(
    app, 
    "DdevDemoStack",
    account_name="sandbox",
    env=cdk.Environment(
        account=infra_config.account,
        region=infra_config.region
    ),
)
```
- **Purpose**: Complete development environment for multiple web applications
- **Features**: ALB, WAF, EC2 with DDEV, wildcard SSL, Traefik routing
- **Use Case**: Host multiple QA/staging sites (qa1.webdev.vadai.org, qa2.webdev.vadai.org)

## Environment Management

### Account-Specific Deployment
```python
# Change this line to deploy to different environments:
infra_config = config_loader.get_infrastructure_info("sandbox")  # or "production" or "development"
```

Each environment has:
- **Separate AWS accounts**: Isolated for security
- **Different VPC CIDRs**: Prevents IP conflicts
- **Scaled resources**: t3.micro for sandbox, t3.small for production
- **Environment variables**: `SANDBOX_ACCOUNT_ID`, `PRODUCTION_ACCOUNT_ID`, etc.

### CDK Environment Configuration
```python
env=cdk.Environment(
    account=infra_config.account,  # From infrastructure.yaml
    region=infra_config.region     # From infrastructure.yaml
)
```

## Deployment Commands

### Standard Deployment
```bash
# Deploy all stacks to sandbox
cdk deploy --all

# Deploy specific stack
cdk deploy DdevDemoStack

# Deploy with confirmation
cdk deploy --require-approval never
```

### Environment-Specific Deployment
```bash
# 1. Set environment variables
export SANDBOX_ACCOUNT_ID="621648307412"
export SANDBOX_REGION="us-east-1"

# 2. Deploy
cdk deploy DdevDemoStack

# Or use .env file:
echo "SANDBOX_ACCOUNT_ID=621648307412" > .env
echo "SANDBOX_REGION=us-east-1" >> .env
cdk deploy DdevDemoStack
```

### Production Deployment
```bash
# 1. Update app.py to use production environment
# Change: infra_config = config_loader.get_infrastructure_info("production")

# 2. Set production environment variables
export PRODUCTION_ACCOUNT_ID="766789219588"
export PRODUCTION_REGION="us-east-1"

# 3. Deploy
cdk deploy --all
```

## Stack Dependencies and Ordering

### Current Architecture
```
SimpleNetworkStack (Independent)
├── Shared VPC infrastructure
├── fck-nat for cost optimization
└── Exports for cross-stack references

SuperFiestaStack (Independent)
├── Template/placeholder stack
└── Future development base

VpcInterfaceEndpointsStack (Independent)
├── Own VPC with endpoints
├── Demonstrates private AWS API access
└── Test EC2 instance included

DdevDemoStack (Independent)
├── Complete web application platform
├── ALB with wildcard SSL
├── WAF protection
├── DDEV-ready EC2 instance
└── Traefik routing for *.webdev.vadai.org
```

### Future Cross-Stack References
To make stacks depend on SimpleNetworkStack:

```python
# Import shared VPC
from aws_cdk import Fn

# In another stack constructor:
shared_vpc_id = Fn.import_value("SimpleNetwork-sandbox-VpcId")
shared_vpc = ec2.Vpc.from_lookup(self, "SharedVpc", vpc_id=shared_vpc_id)
```

## Configuration Integration

### Environment Variables Priority
1. **System environment variables** (highest priority)
2. **`.env` file** (if present)
3. **infrastructure.yaml defaults** (lowest priority)

### Account Management
```python
# Account selection logic in AppConfigs:
def get_infrastructure_info(self, account_name: str):
    # Validates required environment variables exist
    # Merges global config with account-specific config
    # Returns InfrastructureSpec object with all settings
```

## Error Handling

### Missing Environment Variables
```bash
# Error message example:
ValueError: Missing required environment variables for 'sandbox' environment: ['SANDBOX_ACCOUNT_ID']
Please set these variables or create a .env file. See .env.example for reference.
```

### Account Validation
The application validates that required environment variables are set before deployment:
- `SANDBOX_ACCOUNT_ID` + `SANDBOX_REGION` for sandbox
- `PRODUCTION_ACCOUNT_ID` + `PRODUCTION_REGION` for production
- `DEV_ACCOUNT_ID` + `DEV_REGION` for development

## Best Practices

### 1. Environment Separation
```python
# Use different account_name for each environment
if os.getenv("ENVIRONMENT") == "production":
    account_name = "production"
elif os.getenv("ENVIRONMENT") == "development":
    account_name = "development"
else:
    account_name = "sandbox"  # default
```

### 2. Stack Naming
- Use descriptive stack names that indicate purpose
- Include environment in stack names for clarity
- Consider resource limits (CDK has 100 stack limit per app)

### 3. Resource Tagging
```python
# Add to each stack:
cdk.Tags.of(self).add("Environment", account_name)
cdk.Tags.of(self).add("Project", "SuperFiesta")
cdk.Tags.of(self).add("ManagedBy", "CDK")
```

## Monitoring and Debugging

### CloudFormation Stack Status
```bash
# Check stack status
aws cloudformation describe-stacks --stack-name DdevDemoStack

# View stack events
aws cloudformation describe-stack-events --stack-name DdevDemoStack
```

### CDK Debugging
```bash
# See what CDK will deploy
cdk diff DdevDemoStack

# View synthesized CloudFormation
cdk synth DdevDemoStack

# List all stacks
cdk list
```

## Extension Points

### Adding New Stacks
1. Create new stack in `stacks/new_feature/`
2. Import in `app.py`
3. Add to synthesis with appropriate environment
4. Update `infrastructure.yaml` if needed

### Cross-Stack Dependencies
```python
# Example: Make DdevDemoStack use SimpleNetworkStack VPC
ddev_stack = DdevDemoStack(
    app, 
    "DdevDemoStack",
    vpc=simple_network.vpc,  # Pass VPC reference
    account_name="sandbox"
)
```

This architecture provides a solid foundation for multi-environment, multi-stack AWS CDK applications with centralized configuration management.
