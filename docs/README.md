super-fiesta/
├── README.md                        # Main project intro (your Project Overview)
├── docs/
│   ├── 01-CONFIGURATION-SYSTEM.md  # Configuration deep dive
│   ├── 02-STACKS-ARCHITECTURE.md   # Stack patterns & Lambda
│   ├── 03-DEPLOYMENT-STAGES.md     # Multi-environment deployment
│   ├── 04-DEVELOPMENT-GUIDE.md     # Development workflows
│   ├── examples/                   # Sample configs & code
│   ├── troubleshooting/            # Problem resolution
│   └── stacks/                     # Stack-specific guides

# Super Fiesta CDK Project - Complete Overview

## Project Architecture Summary

This AWS CDK project implements a comprehensive, configuration-driven infrastructure platform with multiple deployment environments and advanced features like cost optimization, security, and development tooling.

## 🏗️ Architecture Components

### Core Infrastructure
```
super-fiesta/
├── app.py                    # Main CDK application entry point
├── cdk.json                  # CDK configuration and context
├── requirements.txt          # Python dependencies
│
├── configs/                  # Configuration management system
│   ├── config.py            # Configuration loader with env var support
│   ├── models.py            # Type-safe dataclass models
│   ├── infrastructure.yaml   # Environment-specific settings
│   └── constants.py         # Static configuration values
│
├── stacks/                  # CDK stack implementations
│   ├── core_network/        # Shared VPC infrastructure
│   ├── ddev_demo/           # DDEV development environment
│   ├── vpc_endpoints/       # VPC interface endpoints demo
│   └── super_fiesta/        # Template/placeholder stack
│
├── stages/                  # Multi-environment deployment stages
│   └── infrastructure_stage.py  # Stage orchestration
│
├── utils/                   # Utility functions
│   ├── logger.py           # Centralized logging
│   ├── converters.py       # Data conversion utilities
│   └── userdata_customizer.py  # EC2 user data templating
│
├── scripts/                 # Operational scripts
│   ├── create-site.sh      # DDEV site creation automation
│   └── verify-fck-nat.sh   # Network connectivity verification
│
└── tests/                   # Test suite
    ├── unit/               # Unit tests for stacks
    └── integration/        # Integration test scenarios
```

### Key Features

#### 1. **Cost-Optimized Networking**
- **fck-nat**: Replaces AWS NAT Gateway ($45/month → $3/month = 93% savings)
- **Shared VPC**: Reusable across multiple stacks
- **Right-sized instances**: Environment-appropriate instance types

#### 2. **Configuration-Driven Infrastructure**
- **YAML-based config**: All infrastructure parameters in `infrastructure.yaml`
- **Environment variables**: Secure account ID/region management
- **Type safety**: Python dataclasses for configuration validation
- **Multi-environment**: Sandbox, production, development configurations

#### 3. **Security & Compliance**
- **WAF Integration**: Country blocking, IP allow lists, managed rules
- **VPC Interface Endpoints**: Private AWS API access without internet routing
- **IAM Roles**: Least privilege access patterns
- **Security Groups**: Layered network security

#### 4. **Development Environment**
- **DDEV Platform**: Complete web development environment
- **Wildcard SSL**: `*.webdev.vadai.org` certificate management
- **Traefik Router**: Container-based routing for multiple sites
- **Application Load Balancer**: Production-grade load balancing

## 🚀 Quick Start Guide

### Prerequisites
```bash
# Install AWS CDK
npm install -g aws-cdk

# Install Python dependencies
pip install -r requirements.txt

# Configure AWS credentials
aws configure
# OR use AWS SSO/profiles
```

### Environment Setup
```bash
# 1. Create .env file with your account details
cat > .env << EOF
SANDBOX_ACCOUNT_ID=621648307412
SANDBOX_REGION=us-east-1
PRODUCTION_ACCOUNT_ID=766789219588
PRODUCTION_REGION=us-east-1
DEV_ACCOUNT_ID=123456789012
DEV_REGION=us-west-2
EOF

# 2. Bootstrap CDK (first time only)
cdk bootstrap

# 3. Verify configuration
python -c "
from configs.config import AppConfigs
config = AppConfigs()
info = config.get_infrastructure_info('sandbox')
print(f'Account: ***{info.account[-4:]}')
print(f'Region: {info.region}')
print(f'VPC CIDR: {info.vpc.cidr}')
"
```

### Deployment Options

#### Option 1: Deploy Everything
```bash
# Deploy all stacks to sandbox environment
cdk deploy --all

# Check deployment status
aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE
```

#### Option 2: Deploy Specific Stacks
```bash
# Deploy just the network foundation
cdk deploy SimpleNetwork

# Deploy DDEV development environment
cdk deploy DdevDemoStack

# Deploy VPC endpoints demo
cdk deploy VpcInterfaceEndpointsStack
```

#### Option 3: Deploy to Different Environments
```bash
# Modify app.py to change environment:
# Change: infra_config = config_loader.get_infrastructure_info("production")

# Set production environment variables
export PRODUCTION_ACCOUNT_ID="766789219588"
export PRODUCTION_REGION="us-east-1"

# Deploy to production
cdk deploy --all
```

## 📋 Stack Details and Use Cases

### 1. SimpleNetworkStack - Shared Infrastructure
**Purpose**: Provides cost-optimized networking foundation

**Features**:
- VPC with public/private subnets
- fck-nat for internet access ($3/month vs $45/month NAT Gateway)
- Cross-stack exports for VPC sharing

**Use Cases**:
- Foundation for other stacks
- Cost-conscious development environments
- Multi-stack applications needing shared networking

**Access**:
```bash
# Get VPC details
aws cloudformation describe-stacks --stack-name SimpleNetwork \
  --query 'Stacks[0].Outputs'

# Connect to fck-nat instance
aws ec2 describe-instances --filters "Name=tag:Name,Values=*fck-nat*"
```

### 2. DdevDemoStack - Development Platform
**Purpose**: Complete web application development environment

**Features**:
- Application Load Balancer with wildcard SSL (`*.webdev.vadai.org`)
- WAF protection with country blocking and managed rules
- Ubuntu 24.04 EC2 instance with DDEV pre-installed
- Traefik router for container-based routing

**Use Cases**:
- Multiple QA/staging environments (qa1.webdev.vadai.org, qa2.webdev.vadai.org)
- Development team collaboration
- Client demos and testing

**Access**:
```bash
# Connect to instance
INSTANCE_ID=$(aws cloudformation describe-stacks --stack-name DdevDemoStack \
  --query 'Stacks[0].Outputs[?OutputKey==`DdevInstanceId`].OutputValue' --output text)
aws ssm start-session --target $INSTANCE_ID

# Create new site
./create-site.sh qa3

# Test sites
curl https://qa1.webdev.vadai.org/health.php
curl https://qa2.webdev.vadai.org/info.php
```

### 3. VpcInterfaceEndpointsStack - Secure AWS Access
**Purpose**: Demonstrates private AWS API access without internet routing

**Features**:
- VPC interface endpoints for SSM, EC2, STS, CloudWatch
- Private DNS resolution to AWS services
- Test instance with validation scripts
- VPC Flow Logs for traffic monitoring

**Use Cases**:
- Corporate networks with Direct Connect
- High-security environments
- Cost optimization for AWS API calls
- Compliance requirements for private communications

**Access**:
```bash
# Connect to test instance
INSTANCE_ID=$(aws cloudformation describe-stacks --stack-name VpcInterfaceEndpointsStack \
  --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' --output text)
aws ssm start-session --target $INSTANCE_ID

# Run tests on instance
./test-endpoints.sh
./test-network.sh

# Verify DNS resolution
dig ssm.us-east-1.amazonaws.com  # Should resolve to private IP
```

## 🔧 Configuration Management

### Infrastructure.yaml Structure
```yaml
globals:                    # Default settings for all environments
  vpc:
    cidr: "10.0.0.0/16"
    max_azs: 2
    subnet_mask: 24
  ec2:
    instance_type: "t3.micro"
    key_name: "your-key-name"
  waf:
    enabled: true
    blocked_countries: ["RU", "CN", "KP"]

accounts:                   # Environment-specific overrides
  - name: sandbox
    account: "${SANDBOX_ACCOUNT_ID}"
    region: "${SANDBOX_REGION}"
    vpc:
      cidr: "10.1.0.0/16"
      
  - name: production
    account: "${PRODUCTION_ACCOUNT_ID}"
    region: "${PRODUCTION_REGION}"
    vpc:
      cidr: "10.2.0.0/16"
      max_azs: 3
    ec2:
      instance_type: "t3.small"
    logging:
      retention_days: 30
```

### Environment Variable Management
```bash
# Required environment variables per environment:
# Sandbox:
SANDBOX_ACCOUNT_ID=621648307412
SANDBOX_REGION=us-east-1

# Production:
PRODUCTION_ACCOUNT_ID=766789219588
PRODUCTION_REGION=us-east-1

# Development:
DEV_ACCOUNT_ID=123456789012
DEV_REGION=us-west-2
```

## 🛠️ Development Workflows

### Adding New Stacks
```bash
# 1. Create new stack directory
mkdir -p stacks/new_feature

# 2. Create stack file
cat > stacks/new_feature/new_feature_stack.py << EOF
from aws_cdk import Stack
from constructs import Construct
from configs.config import AppConfigs

class NewFeatureStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # Load configuration
        self.config_loader = AppConfigs()
        self.infra_config = self.config_loader.get_infrastructure_info(account_name)
        
        # Create resources
        self.create_resources()
    
    def create_resources(self):
        # Implementation here
        pass
EOF

# 3. Add to app.py
# Import and instantiate in app.py

# 4. Deploy
cdk deploy NewFeatureStack
```

### Adding Lambda Functions
```bash
# 1. Create Lambda code directory
mkdir -p lambda_code/my_function

# 2. Create handler
cat > lambda_code/my_function/index.py << EOF
import json

def handler(event, context):
    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Hello from Lambda!'})
    }
EOF

# 3. Add to stack
# See Lambda integration examples in stacks README

# 4. Deploy
cdk deploy LambdaServicesStack
```

### Configuration Changes
```bash
# 1. Modify infrastructure.yaml
vim configs/infrastructure.yaml

# 2. Validate configuration
python -c "
from configs.config import AppConfigs
config = AppConfigs()
info = config.get_infrastructure_info('sandbox')
print('Configuration valid!')
"

# 3. Preview changes
cdk diff

# 4. Deploy changes
cdk deploy
```

## 🧪 Testing and Validation

### Unit Tests
```bash
# Run unit tests
python -m pytest tests/unit/ -v

# Test specific stack
python -m pytest tests/unit/test_ddev_demo_stack.py -v

# Test with coverage
python -m pytest tests/unit/ --cov=stacks --cov-report=html
```

### Integration Tests
```bash
# Deploy to test environment
cdk deploy --all --require-approval never

# Run integration tests
python -m pytest tests/integration/ -v

# Run smoke tests
python scripts/smoke_tests.py --environment sandbox
```

### Manual Validation
```bash
# Validate DDEV environment
curl https://qa1.webdev.vadai.org/health.php

# Validate VPC endpoints
aws ssm start-session --target $INSTANCE_ID
# Then run: ./test-endpoints.sh

# Validate network connectivity
curl -H "Host: qa1.webdev.vadai.org" http://localhost/
```

## 📊 Monitoring and Troubleshooting

### CloudFormation Stack Status
```bash
# Check all stack statuses
aws cloudformation list-stacks --stack-status-filter \
  CREATE_COMPLETE UPDATE_COMPLETE CREATE_IN_PROGRESS UPDATE_IN_PROGRESS

# Get stack outputs
aws cloudformation describe-stacks --stack-name DdevDemoStack \
  --query 'Stacks[0].Outputs'

# View stack events
aws cloudformation describe-stack-events --stack-name DdevDemoStack
```

### Application Monitoring
```bash
# Check ALB target health
aws elbv2 describe-target-health --target-group-arn $TG_ARN

# View VPC Flow Logs
aws logs describe-log-streams --log-group-name /aws/vpc/flowlogs

# Check EC2 instance status
aws ec2 describe-instance-status --instance-ids $INSTANCE_ID
```

### Cost Monitoring
```bash
# Get current month costs by service
aws ce get-cost-and-usage \
  --time-period Start=2025-01-01,End=2025-02-01 \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE

# Estimated monthly costs:
# - SimpleNetwork (fck-nat): ~$3/month
# - DdevDemoStack: ~$28/month (EC2 + ALB + EBS)
# - VpcEndpoints: ~$15/month (endpoints)
```

## 🔒 Security Best Practices

### Access Control
```bash
# Use IAM roles instead of access keys
# Configure AWS SSO where possible
# Use least privilege principles

# Example: Connect via SSM instead of SSH
aws ssm start-session --target $INSTANCE_ID
```

### Network Security
```bash
# WAF blocking by country
# Security groups with minimal access
# VPC interface endpoints for private API access
# Private subnets for application instances
```

### Configuration Security
```bash
# Store sensitive values in environment variables
# Use AWS Secrets Manager for application secrets
# Rotate access keys regularly
# Enable CloudTrail for audit logging
```

## 🚀 Production Deployment

### Pre-Production Checklist
- [ ] Set production environment variables
- [ ] Review infrastructure.yaml production settings
- [ ] Enable WAF and security features
- [ ] Configure monitoring and alerting
- [ ] Set up backup strategies
- [ ] Review IAM policies

### Production Deployment
```bash
# 1. Set production environment
export PRODUCTION_ACCOUNT_ID="766789219588"
export PRODUCTION_REGION="us-east-1"

# 2. Update app.py for production
# Change: infra_config = config_loader.get_infrastructure_info("production")

# 3. Deploy with approval
cdk deploy --all

# 4. Validate deployment
python scripts/production_validation.py
```

This comprehensive architecture provides a solid foundation for building, testing, and deploying complex AWS infrastructure with proper configuration management, security, and cost optimization.
