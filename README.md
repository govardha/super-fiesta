# VPC Interface Endpoints Demonstration Guide

## Overview
This CDK stack demonstrates VPC Interface Endpoints using a configuration-driven approach. All infrastructure parameters are defined in `configs/infrastructure.yaml`, making it easy to customize for different environments.

## Configuration-Driven Architecture
- **Configuration File**: `configs/infrastructure.yaml` contains all infrastructure parameters
- **Environment-Specific**: Different settings for sandbox, production, and development
- **Flexible**: Easy to modify VPC CIDR, instance types, regions, and endpoint configurations

## Key Configuration Parameters
- **VPC Settings**: CIDR blocks, AZ count, subnet configuration
- **EC2 Settings**: Instance types, AMI preferences
- **Logging**: CloudWatch retention periods, log group names
- **Endpoints**: Which AWS services to create VPC endpoints for

## Architecture
- **VPC**: Configurable CIDR with private isolated subnets (no NAT Gateway)
- **VPC Endpoints**: Interface endpoints defined in configuration
- **EC2 Instance**: Test instance with configurable specs
- **DNS Resolution**: Private DNS enabled on endpoints for automatic routing

## Deployment Commands

### 1. Setup Configuration
```bash
# Copy the example configuration
cp configs/infrastructure.example.yaml configs/infrastructure.yaml

# Edit the configuration file with your account IDs
vim configs/infrastructure.yaml
# Update the account IDs in the accounts section
```

### 2. Deploy the Stack
```bash
# Install dependencies
pip install -r requirements.txt

# Bootstrap CDK (if first time)
cdk bootstrap

# Deploy with default account (sandbox)
cdk deploy VpcInterfaceEndpointsStack

# Or deploy with specific environment
cdk deploy VpcInterfaceEndpointsStack -c account=production

# Get the instance ID from the output
export INSTANCE_ID=$(aws cloudformation describe-stacks \
  --stack-name VpcInterfaceEndpointsStack \
  --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' \
  --output text)

echo "Instance ID: $INSTANCE_ID"
```

### 3. Environment-Specific Deployments
```bash
# Deploy to different environments by modifying app.py:
# Change account_name parameter in app.py:

# For sandbox (default):
# account_name="sandbox"

# For production:
# account_name="production"  

# For development:
# account_name="development"
```

## Configuration Customization Examples

### Modify VPC Settings
```yaml
# In configs/infrastructure.yaml
globals:
  vpc:
    cidr: "172.16.0.0/16"  # Change VPC CIDR
    max_azs: 3             # Use 3 availability zones
    subnet_mask: 20        # Larger subnets
```

### Change Instance Types
```yaml
# For production environment
- name: production
  account: "YOUR_ACCOUNT_ID"
  region: us-east-1
  ec2:
    instance_type: "m5.large"
    instance_class: "STANDARD5"
    instance_size: "LARGE"
```

### Add/Remove VPC Endpoints
```yaml
# Add more endpoints
endpoints:
  services:
    - name: "s3"
      service: "S3"
    - name: "lambda"
      service: "LAMBDA"
    - name: "dynamodb"
      service: "DYNAMODB"
```

### Multi-Region Configuration
```yaml
# Deploy to different regions
- name: west-coast
  account: "YOUR_ACCOUNT_ID"
  region: us-west-2
  vpc:
    cidr: "10.4.0.0/16"
```
## Connect to Test Instance

### Using Systems Manager Session Manager
```bash
# Connect using AWS Systems Manager Session Manager
aws ssm start-session --target $INSTANCE_ID

# Alternative: Use the AWS Console -> Systems Manager -> Session Manager
```

## Testing Commands (Run on EC2 Instance)

### DNS Resolution Tests
```bash
# Test DNS resolution for AWS services (should resolve to private IPs)
dig ssm.us-east-1.amazonaws.com
dig ec2.us-east-1.amazonaws.com  
dig sts.us-east-1.amazonaws.com
dig ssmmessages.us-east-1.amazonaws.com
dig ec2messages.us-east-1.amazonaws.com

# Compare with public DNS (should resolve to public IPs)
dig @8.8.8.8 ssm.us-east-1.amazonaws.com
```

### Network Connectivity Tests
```bash
# Test HTTPS connectivity to endpoints
nc -zv ssm.us-east-1.amazonaws.com 443
nc -zv ec2.us-east-1.amazonaws.com 443
nc -zv sts.us-east-1.amazonaws.com 443

# Check routing
ip route show
netstat -rn
```

### AWS CLI Tests
```bash
# Test STS (should work through VPC endpoint)
aws sts get-caller-identity --region us-east-1

# Test EC2 API calls
aws ec2 describe-instances --region us-east-1 --max-items 1

# Test SSM
aws ssm describe-instance-information --region us-east-1

# Test with debug output to see endpoint usage
aws sts get-caller-identity --region us-east-1 --debug 2>&1 | grep -i endpoint
```

### Network Traffic Analysis
```bash
# Monitor network traffic (run in separate terminal)
sudo tcpdump -i any -n host 10.0.0.0/16 and port 443

# Test API call while monitoring traffic
aws sts get-caller-identity --region us-east-1
```

## Pre-built Test Scripts

The EC2 instance comes with two test scripts:

### 1. DNS and API Testing
```bash
# Run comprehensive endpoint tests
./test-endpoints.sh
```

### 2. Network Connectivity Testing  
```bash
# Test network connectivity
./test-network.sh
```

## Verification Points

### What to Look For:

1. **DNS Resolution**: 
   - VPC endpoint services resolve to private IPs (10.x.x.x)
   - Public DNS resolves to public IPs

2. **Network Traffic**:
   - All HTTPS traffic stays within VPC CIDR
   - No traffic to public AWS IPs

3. **API Functionality**:
   - All AWS CLI commands work normally
   - Responses are identical to public endpoint calls

## Regional Endpoint Testing

To test different regions as mentioned in your use case:

```bash
# Test us-east-1 (should work through endpoints)
aws sts get-caller-identity --region us-east-1

# Test us-east-2 (would need endpoints in that region)
aws sts get-caller-identity --region us-east-2

# Test us-west-2 (would need endpoints in that region) 
aws sts get-caller-identity --region us-west-2
```

## Monitoring and Logging

### VPC Flow Logs
```bash
# View VPC Flow Logs to see traffic patterns
aws logs describe-log-streams --log-group-name /aws/vpc/flowlogs

# Get recent flow log entries
aws logs get-log-events \
  --log-group-name /aws/vpc/flowlogs \
  --log-stream-name <stream-name> \
  --start-time $(date -d '1 hour ago' +%s)000
```

### CloudWatch Metrics
```bash
# View VPC endpoint metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/VPC \
  --metric-name PacketDropCount \
  --dimensions Name=VpceId,Value=<vpc-endpoint-id> \
  --start-time $(date -d '1 hour ago' --iso-8601) \
  --end-time $(date --iso-8601) \
  --period 300 \
  --statistics Sum
```

## Advanced Testing

### Cross-Region Endpoint Testing
```bash
# Show how traffic fails without regional endpoints
aws ec2 describe-instances --region us-west-2 --max-items 1

# This should timeout or fail since we only have us-east-1 endpoints
```

### Policy Testing
```bash
# Test endpoint policies (modify stack to add restrictive policies)
# Example: Restrict to specific IAM roles or IP ranges

# Test with different IAM permissions
aws sts assume-role --role-arn arn:aws:iam::ACCOUNT:role/TestRole --role-session-name test
```

## Cleanup
```bash
# Destroy the stack
cdk destroy VpcInterfaceEndpointsStack
```

## Key Observations

When testing, you should observe:

1. **Private DNS Resolution**: Service FQDNs resolve to private IPs within your VPC
2. **No Internet Traffic**: All AWS API calls stay within your VPC 
3. **Transparent Operation**: Applications work normally without code changes
4. **Regional Limitation**: Only services in the same region as endpoints are accessible
5. **Cost Efficiency**: Reduced data transfer costs and improved security

This demonstrates how your Transit VPC with interface endpoints would work in a corporate Direct Connect environment.