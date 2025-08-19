# Configuration System Architecture README

## Overview
This project uses a sophisticated configuration management system that separates infrastructure definitions from code, supports multiple environments, and provides type safety through Python dataclasses.

## Architecture Components

### 1. Configuration Files Structure
```
configs/
├── config.py           # Configuration loader and validation logic
├── models.py           # Type-safe dataclass models  
├── infrastructure.yaml # Environment-specific infrastructure definitions
└── constants.py        # Static configuration values
```

## Core Configuration Flow

### 1. Configuration Loading Process
```python
# From app.py or any stack
config_loader = AppConfigs()
infra_config = config_loader.get_infrastructure_info("sandbox")
```

**Step-by-step process:**
1. **Environment validation**: Checks required env vars exist
2. **YAML loading**: Loads and processes `infrastructure.yaml` with templating
3. **Configuration merging**: Combines global + account-specific settings
4. **Type conversion**: Converts to strongly-typed dataclass objects
5. **Returns**: `InfrastructureSpec` object with all configuration

### 2. Environment Variable Integration
```python
# configs/config.py
def __init__(self):
    # Load environment variables from .env file if it exists
    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file)
```

**Priority order:**
1. **System environment variables** (highest)
2. **`.env` file variables**
3. **YAML template defaults** (lowest)

## Infrastructure.yaml Structure

### Template Processing
```yaml
# Uses Python string.Template for variable substitution
accounts:
  - name: sandbox
    account: "${SANDBOX_ACCOUNT_ID}"    # Environment variable
    region: "${SANDBOX_REGION}"         # Environment variable
```

### Global Configuration Section
```yaml
globals:
  vpc:
    cidr: "10.0.0.0/16"           # Default VPC CIDR
    max_azs: 2                    # Availability zones
    subnet_mask: 24               # Subnet sizing
    enable_dns_hostnames: true
    enable_dns_support: true
    nat_gateways: 0               # Cost optimization
  
  ec2:
    instance_type: "t3.micro"     # Default instance size
    instance_class: "BURSTABLE2"
    instance_size: "MICRO"
    amazon_linux_edition: "STANDARD"
    key_name: "govardha-ddev-demo"
  
  logging:
    flow_logs_group_name: "/aws/vpc/flowlogs"
    retention_days: 2
  
  endpoints:                      # VPC Interface Endpoints
    services:
      - name: "ssm"
        service: "SSM"
      - name: "ec2"
        service: "EC2"
```

### Account-Specific Overrides
```yaml
accounts:
  - name: sandbox
    account: "${SANDBOX_ACCOUNT_ID}"
    region: "${SANDBOX_REGION}"
    vpc:
      cidr: "10.1.0.0/16"          # Override global CIDR
    ec2:
      instance_type: "t3.micro"     # Override instance size
  
  - name: production
    account: "${PRODUCTION_ACCOUNT_ID}"
    region: "${PRODUCTION_REGION}"
    vpc:
      cidr: "10.2.0.0/16"
      max_azs: 3                   # More AZs for production
    ec2:
      instance_type: "t3.small"     # Larger instances for production
    logging:
      retention_days: 30           # Longer retention for production
```

## Models.py - Type Safety System

### Core Infrastructure Model
```python
@dataclass
class InfrastructureSpec:
    account: str                              # AWS Account ID
    region: str                               # AWS Region
    vpc: Optional[VpcConfig] = None           # VPC configuration
    ec2: Optional[Ec2Config] = None           # EC2 configuration
    logging: Optional[LoggingConfig] = None   # Logging configuration
    endpoints: Optional[EndpointsConfig] = None # VPC Endpoints
    waf: Optional[WafConfig] = None           # WAF configuration
```

### Detailed Configuration Models

#### VPC Configuration
```python
@dataclass
class VpcConfig:
    cidr: str                       # VPC CIDR block
    max_azs: int = 2               # Number of availability zones
    subnet_mask: int = 24          # Subnet size
    enable_dns_hostnames: bool = True
    enable_dns_support: bool = True
    nat_gateways: int = 0          # Number of NAT gateways
```

#### EC2 Configuration
```python
@dataclass
class Ec2Config:
    instance_type: str                           # t3.micro, t3.small, etc.
    instance_class: str = "BURSTABLE3"          # BURSTABLE2, BURSTABLE3, STANDARD5
    instance_size: str = "MICRO"                # NANO, MICRO, SMALL, MEDIUM
    amazon_linux_edition: str = "STANDARD"     # STANDARD, MINIMAL
    virtualization: str = "HVM"                # HVM, PV
    storage: str = "GENERAL_PURPOSE"           # GENERAL_PURPOSE, EBS
    ami_id: Optional[str] = None               # Custom AMI override
    key_name: Optional[str] = None             # SSH key pair name
```

#### WAF Configuration
```python
@dataclass
class WafConfig:
    enabled: bool = False
    name: str = "DdevWaf"
    description: str = "WAF for DDEV Demo"
    cloudwatch_metrics_enabled: bool = True
    sampled_requests_enabled: bool = True
    # IP Allow List
    allowed_ips: List[str] = None
    # Country Blocking (ISO 3166-1 alpha-2 codes)
    blocked_countries: List[str] = None
    # AWS Managed Rule Controls
    aws_common_rule_set: bool = True
    aws_known_bad_inputs: bool = True
    aws_sql_injection: bool = True
    aws_xss_protection: bool = True
    aws_rate_limiting: bool = False
    rate_limit_requests: int = 2000
```

### Type Conversion Process
```python
# In config.py - converts YAML dict to typed objects
vpc_config = from_dict(data_class=VpcConfig, data=merged_config["vpc"])
ec2_config = from_dict(data_class=Ec2Config, data=merged_config["ec2"])
waf_config = from_dict(data_class=WafConfig, data=merged_config["waf"])
```

## Configuration Usage in Stacks

### Basic Usage Pattern
```python
class DdevDemoStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, account_name: str = "sandbox", **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # Load configuration
        self.config_loader = AppConfigs()
        self.infra_config: InfrastructureSpec = self.config_loader.get_infrastructure_info(account_name)
        
        # Use configuration values
        self.vpc = ec2.Vpc(
            self,
            "DdevDemoVpc",
            ip_addresses=ec2.IpAddresses.cidr(self.infra_config.vpc.cidr),  # From config
            max_azs=self.infra_config.vpc.max_azs,                          # From config
        )
```

### Conditional Resource Creation
```python
# WAF creation based on configuration
if self.infra_config.waf and self.infra_config.waf.enabled:
    self.create_waf()
```

### Mapping Configuration to CDK Enums
```python
# Map configuration strings to CDK enums
instance_class_mapping = {
    "BURSTABLE2": ec2.InstanceClass.BURSTABLE2,
    "BURSTABLE3": ec2.InstanceClass.BURSTABLE3,
    "STANDARD5": ec2.InstanceClass.STANDARD5,
}

instance_class = instance_class_mapping.get(
    self.infra_config.ec2.instance_class, 
    ec2.InstanceClass.BURSTABLE3
)
```

## Environment Management

### Environment Variable Validation
```python
def validate_required_env_vars(self, account_name: str):
    """Validate that required environment variables are set"""
    required_vars = []
    
    if account_name == "sandbox":
        required_vars = ["SANDBOX_ACCOUNT_ID", "SANDBOX_REGION"]
    elif account_name == "production":
        required_vars = ["PRODUCTION_ACCOUNT_ID", "PRODUCTION_REGION"]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables for '{account_name}' environment: {missing_vars}"
        )
```

### .env File Support
```bash
# .env file example
SANDBOX_ACCOUNT_ID=621648307412
SANDBOX_REGION=us-east-1
PRODUCTION_ACCOUNT_ID=766789219588
PRODUCTION_REGION=us-east-1
DEV_ACCOUNT_ID=123456789012
DEV_REGION=us-west-2
```

## Configuration Merging Logic

### Global + Account-Specific Merge
```python
# From config.py
globals_config = data.get("globals", {})
account = next((x for x in accounts if x["name"] == account_name), {})

# Deep merge: account settings override global settings
merged_config = update(globals_config.copy(), account)
```

### Merge Examples
```yaml
# Global setting
globals:
  vpc:
    cidr: "10.0.0.0/16"
    max_azs: 2

# Account override
accounts:
  - name: production
    vpc:
      max_azs: 3  # Only overrides max_azs, keeps global cidr

# Result: cidr="10.0.0.0/16", max_azs=3
```

## Advanced Features

### Template String Processing
```python
def string_constructor(loader, node):
    t = string.Template(node.value)
    # Substitute with both context and environment variables
    combined_context = {**os.environ, **context}
    value = t.substitute(combined_context)
    return value
```

### Logging Integration
```python
from utils.logger import configure_logger

LOGGER = configure_logger(__name__)

# Usage throughout config loading
LOGGER.info(f"Using account: {masked_account} for environment: {account_name}")
```

### Account ID Masking (Security)
```python
# Log account being used without exposing full ID
account_id = merged_config.get("account", "unknown")
masked_account = f"***{account_id[-4:]}" if account_id != "unknown" else "unknown"
LOGGER.info(f"Using account: {masked_account} for environment: {account_name}")
```

## Best Practices

### 1. Environment-Specific Configurations
- Use separate CIDRs for each environment to prevent conflicts
- Scale instance sizes appropriately (micro for dev, small+ for prod)
- Adjust logging retention based on environment needs

### 2. Security Configuration
- Store sensitive values in environment variables, not YAML
- Use IAM roles instead of access keys where possible
- Enable WAF for production environments

### 3. Cost Optimization
- Use `nat_gateways: 0` with fck-nat for development
- Choose appropriate instance types per environment
- Set shorter log retention for development environments

### 4. Type Safety
- Always use dataclass models for configuration
- Provide sensible defaults in dataclass definitions
- Validate configuration before using in stacks

This configuration system provides a robust, type-safe, and environment-aware foundation for managing complex AWS CDK infrastructure.
