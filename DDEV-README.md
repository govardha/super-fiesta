# QA Environment Setup and Management Guide

Complete guide for managing multiple QA sites using DDEV, AWS ELB, and CloudFlare.

## Architecture Overview

- **AWS ELB**: Handles SSL termination and routing
- **EC2 Instance**: Ubuntu 24.04 running multiple DDEV containers  
- **DDEV**: Containerized web servers for each QA site
- **CloudFlare**: DNS management for *.vadai.org domains
- **Target Groups**: Route traffic to specific ports per site

## Prerequisites

- AWS CLI configured with appropriate permissions
- CloudFlare account with vadai.org domain
- CDK stack deployed (DdevDemoStack)

## Initial Setup

### 1. Deploy Infrastructure
```bash
# Deploy the CDK stack
cdk deploy DdevDemoStack

# Get key outputs
aws cloudformation describe-stacks --stack-name DdevDemoStack --query 'Stacks[0].Outputs'
```

### 2. Connect to Instance
```bash
# Get instance details
INSTANCE_ID=$(aws cloudformation describe-stacks --stack-name DdevDemoStack --query 'Stacks[0].Outputs[?OutputKey==`DdevInstanceId`].OutputValue' --output text)
PUBLIC_IP=$(aws cloudformation describe-stacks --stack-name DdevDemoStack --query 'Stacks[0].Outputs[?OutputKey==`DdevInstancePublicIP`].OutputValue' --output text)

# Connect via SSM (recommended)
aws ssm start-session --target $INSTANCE_ID

# Or SSH (if key configured)
ssh ubuntu@$PUBLIC_IP -i govardha-ddev-demo.pem
```

## DDEV Site Creation Process

### Standard Sites (qa1, qa2)
These are pre-configured in CDK with target groups and listener rules.

```bash
# SSH into instance first
ssh ubuntu@your-instance-ip

# Create QA1 site
mkdir -p /home/ubuntu/qa1-site
cd /home/ubuntu/qa1-site

# Install DDEV (first time only)
curl -fsSL https://raw.githubusercontent.com/ddev/ddev/master/scripts/install_ddev.sh | bash

# Configure DDEV project
ddev config --project-name=qa1 --project-type=php --docroot=""

# Create site configuration
cat > .ddev/config.yaml << 'EOF'
name: qa1
type: php
docroot: ""
php_version: "8.2"
webserver_type: nginx-fpm
router_http_port: "8001"
router_https_port: "8002"
xdebug_enabled: false
additional_fqdns:
  - qa1.vadai.org
omit_containers: [db]
use_dns_when_possible: false
disable_upload_dirs_warning: true
bind_all_interfaces: true
EOF

# Configure external access
cat > .ddev/docker-compose.override.yaml << 'EOF'
version: '3.6'
services:
  web:
    ports:
      - "0.0.0.0:8001:80"
EOF

# Create site content (use the dynamic template)
# Copy the dynamic HTML template to index.html
echo "OK" > health
echo "<?php phpinfo(); ?>" > phpinfo.php

# Start DDEV
ddev start

# Test locally
curl http://localhost:8001/health
```

### Custom Sites (qa-manick1, qa-manick2)
These require manual target group and listener rule creation.

## AWS ELB Management

### View Current Configuration
```bash
# Get ELB details
ALB_ARN=$(aws cloudformation describe-stacks --stack-name DdevDemoStack --query 'Stacks[0].Outputs[?contains(OutputKey, `LoadBalancer`)].OutputValue' --output text)
ELB_DNS=$(aws cloudformation describe-stacks --stack-name DdevDemoStack --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNS`].OutputValue' --output text)

# List all target groups
aws elbv2 describe-target-groups --query 'TargetGroups[].{Name:TargetGroupName,Port:Port,Arn:TargetGroupArn}'

# List all listener rules
LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn $ALB_ARN --query 'Listeners[?Port==`443`].ListenerArn' --output text)
aws elbv2 describe-rules --listener-arn $LISTENER_ARN
```

### Create New Target Group
```bash
# Get VPC ID
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=*DdevDemo*" --query 'Vpcs[0].VpcId' --output text)

# Create target group for new site
aws elbv2 create-target-group \
  --name qa-manick1-tg \
  --protocol HTTP \
  --port 8003 \
  --vpc-id $VPC_ID \
  --health-check-path /health \
  --health-check-port 8003 \
  --target-type instance \
  --health-check-interval-seconds 30 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 5

# Get the new target group ARN
TG_ARN=$(aws elbv2 describe-target-groups --names qa-manick1-tg --query 'TargetGroups[0].TargetGroupArn' --output text)
echo "New Target Group ARN: $TG_ARN"
```

### Add Listener Rule
```bash
# Add listener rule for new site
aws elbv2 create-rule \
  --listener-arn $LISTENER_ARN \
  --priority 130 \
  --conditions Field=host-header,Values=qa-manick1.vadai.org \
  --actions Type=forward,TargetGroupArn=$TG_ARN

# Verify rule was created
aws elbv2 describe-rules --listener-arn $LISTENER_ARN --query 'Rules[?Priority==`130`]'
```

### Register Instance with Target Group
```bash
# Get instance ID
INSTANCE_ID=$(aws ec2 describe-instances --filters "Name=private-ip-address,Values=10.1.2.207" "Name=instance-state-name,Values=running" --query 'Reservations[0].Instances[0].InstanceId' --output text)

# Register instance with target group
aws elbv2 register-targets \
  --target-group-arn $TG_ARN \
  --targets Id=$INSTANCE_ID,Port=8003

# Check target health (wait 1-2 minutes for healthy status)
aws elbv2 describe-target-health --target-group-arn $TG_ARN
```

## Target Group Management

### View Target Health
```bash
# Check all target groups health
aws elbv2 describe-target-groups --query 'TargetGroups[].[TargetGroupName,TargetGroupArn]' --output table

# Check specific target group health
aws elbv2 describe-target-health --target-group-arn "arn:aws:elasticloadbalancing:..."
```

### Register/Deregister Targets
```bash
# Register instance with target group
aws elbv2 register-targets \
  --target-group-arn "arn:aws:elasticloadbalancing:us-east-1:account:targetgroup/name/id" \
  --targets Id=i-instanceid,Port=8001

# Deregister instance from target group  
aws elbv2 deregister-targets \
  --target-group-arn "arn:aws:elasticloadbalancing:us-east-1:account:targetgroup/name/id" \
  --targets Id=i-instanceid,Port=8001

# Bulk register instance with multiple target groups
aws elbv2 register-targets --target-group-arn $QA1_TG_ARN --targets Id=$INSTANCE_ID,Port=8001
aws elbv2 register-targets --target-group-arn $QA2_TG_ARN --targets Id=$INSTANCE_ID,Port=8002
aws elbv2 register-targets --target-group-arn $MANICK1_TG_ARN --targets Id=$INSTANCE_ID,Port=8003
aws elbv2 register-targets --target-group-arn $MANICK2_TG_ARN --targets Id=$INSTANCE_ID,Port=8004
```

## DDEV Management

### Site Lifecycle
```bash
# Create new DDEV site
mkdir -p /home/ubuntu/new-site
cd /home/ubuntu/new-site
ddev config --project-name=new-site --project-type=php --docroot=""

# Start site
ddev start

# Stop site  
ddev stop

# Restart site
ddev restart

# Delete site (removes containers, keeps files)
ddev delete

# View site status
ddev status

# View all DDEV projects
ddev list
```

### Site Configuration
```bash
# Edit site configuration
cd /home/ubuntu/site-name
nano .ddev/config.yaml

# View current configuration
ddev config

# Restart after config changes
ddev restart
```

### Container Management
```bash
# View running DDEV containers
docker ps

# View DDEV logs
ddev logs

# SSH into DDEV container
ddev ssh

# Execute commands in container
ddev exec "php -v"
ddev exec "nginx -t"

# Access container shell
ddev ssh
```

## Port Management

### Current Port Allocation
- **qa1**: 8001 → qa1.vadai.org
- **qa2**: 8002 → qa2.vadai.org  
- **qa-manick1**: 8003 → qa-manick1.vadai.org
- **qa-manick2**: 8004 → qa-manick2.vadai.org

### Check Port Usage
```bash
# See what's listening on ports
ss -tulpn | grep :800

# Check specific port
sudo lsof -i :8001

# View all Docker port mappings
docker ps --format "table {{.Names}}\t{{.Ports}}"
```

## CloudFlare DNS Setup

### Add New QA Site
1. Go to CloudFlare dashboard for vadai.org
2. Add DNS record:
   - **Type**: CNAME
   - **Name**: qa-sitename (e.g., qa-manick1)
   - **Target**: your-elb-dns-name.us-east-1.elb.amazonaws.com
   - **Proxy status**: DNS only (gray cloud)
   - **TTL**: Auto

### Verify DNS
```bash
# Check DNS resolution
dig qa1.vadai.org
nslookup qa-manick1.vadai.org

# Test DNS propagation
curl -I https://qa-manick1.vadai.org
```

## Instance Management

### Stop/Start Instance
```bash
# Stop instance (saves costs, preserves data)
aws ec2 stop-instances --instance-ids $INSTANCE_ID

# Start instance  
aws ec2 start-instances --instance-ids $INSTANCE_ID

# Check instance status
aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].State.Name'

# Get new public IP after restart
aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
```

### After Instance Restart
```bash
# Instance gets new public IP but same private IP (10.1.2.207)
# Target groups remain registered
# DDEV sites should auto-start, but verify:

ssh ubuntu@new-public-ip
cd /home/ubuntu/qa1-site && ddev start
cd /home/ubuntu/qa2-site && ddev start
cd /home/ubuntu/qa-manick1-site && ddev start  
cd /home/ubuntu/qa-manick2-site && ddev start

# Check all sites are healthy
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
```

## Troubleshooting

### DDEV Issues
```bash
# DDEV won't start
ddev restart
docker system prune -f

# Port conflicts
ss -tulpn | grep :8001
sudo lsof -i :8001

# Container issues
docker ps -a
docker logs container-name

# Reset DDEV completely
ddev delete
ddev start
```

### ELB Issues
```bash
# Check target health
aws elbv2 describe-target-health --target-group-arn $TG_ARN

# Check listener rules
aws elbv2 describe-rules --listener-arn $LISTENER_ARN

# Test ELB directly
curl -H "Host: qa1.vadai.org" http://your-elb-dns-name/health
```

### DNS Issues
```bash
# Clear DNS cache locally
sudo systemctl flush-dns

# Test direct ELB access
curl https://your-elb-dns-name -H "Host: qa1.vadai.org"

# Check CloudFlare DNS settings
dig @1.1.1.1 qa1.vadai.org
```

## Quick Reference Commands

### Get All Key Information
```bash
# Instance details
aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].{InstanceId:InstanceId,PublicIP:PublicIpAddress,PrivateIP:PrivateIpAddress,State:State.Name}'

# All target group ARNs
aws cloudformation describe-stacks --stack-name DdevDemoStack --query 'Stacks[0].Outputs[?contains(OutputKey, `TargetGroup`)].{Site:OutputKey,ARN:OutputValue}' --output table

# ELB DNS name
aws cloudformation describe-stacks --stack-name DdevDemoStack --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNS`].OutputValue' --output text
```

### Health Check All Sites
```bash
# From local machine
curl -s https://qa1.vadai.org/health
curl -s https://qa2.vadai.org/health  
curl -s https://qa-manick1.vadai.org/health
curl -s https://qa-manick2.vadai.org/health

# From instance  
curl -s http://localhost:8001/health
curl -s http://localhost:8002/health
curl -s http://localhost:8003/health
curl -s http://localhost:8004/health
```

### Start All DDEV Sites
```bash
# SSH into instance, then:
cd /home/ubuntu/qa1-site && ddev start
cd /home/ubuntu/qa2-site && ddev start
cd /home/ubuntu/qa-manick1-site && ddev start
cd /home/ubuntu/qa-manick2-site && ddev start

# Check all are running
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

## Cost Management

### While Running
- **EC2 t3.micro**: ~$8/month
- **ELB**: ~$18/month  
- **EBS 20GB**: ~$2/month
- **Total**: ~$28/month

### While Stopped
- **EC2**: $0 (stopped)
- **ELB**: ~$18/month (keeps endpoints active)
- **EBS**: ~$2/month (preserves data)
- **Total**: ~$20/month

### Stop Everything
```bash
# Stop instance to save costs
aws ec2 stop-instances --instance-ids $INSTANCE_ID

# Optional: Delete stack entirely (loses all data)
cdk destroy DdevDemoStack
```

## Adding New QA Sites

### Step 1: Create Target Group
```bash
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=*DdevDemo*" --query 'Vpcs[0].VpcId' --output text)

aws elbv2 create-target-group \
  --name qa-newsite-tg \
  --protocol HTTP \
  --port 8005 \
  --vpc-id $VPC_ID \
  --health-check-path /health \
  --health-check-port 8005 \
  --target-type instance
```

### Step 2: Add Listener Rule
```bash
TG_ARN=$(aws elbv2 describe-target-groups --names qa-newsite-tg --query 'TargetGroups[0].TargetGroupArn' --output text)

aws elbv2 create-rule \
  --listener-arn $LISTENER_ARN \
  --priority 150 \
  --conditions Field=host-header,Values=qa-newsite.vadai.org \
  --actions Type=forward,TargetGroupArn=$TG_ARN
```

### Step 3: Create DDEV Site
```bash
mkdir -p /home/ubuntu/qa-newsite
cd /home/ubuntu/qa-newsite
ddev config --project-name=qa-newsite --project-type=php --docroot=""

# Configure for port 8005
# (Update config.yaml and docker-compose.override.yaml accordingly)
```

### Step 4: Register and Test
```bash
aws elbv2 register-targets --target-group-arn $TG_ARN --targets Id=$INSTANCE_ID,Port=8005
```

## Backup and Recovery

### Backup DDEV Sites
```bash
# Backup all site files
tar -czf qa-sites-backup.tar.gz /home/ubuntu/*-site/

# Backup DDEV configurations
tar -czf ddev-configs-backup.tar.gz /home/ubuntu/*-site/.ddev/
```

### Restore Sites
```bash
# Extract backup
tar -xzf qa-sites-backup.tar.gz

# Restart all DDEV projects
for site in qa1-site qa2-site qa-manick1-site qa-manick2-site; do
  cd /home/ubuntu/$site && ddev start
done
```

## Environment Variables

Set these for easier management:
```bash
export INSTANCE_ID="i-0fc2162fe216dd21f"
export ELB_DNS="your-elb-dns-name.us-east-1.elb.amazonaws.com"
export QA1_TG_ARN="arn:aws:elasticloadbalancing:us-east-1:621648307412:targetgroup/DdevDe-QA1Ta-REURPZDEBUKI/4f0c8b1155197427"
export QA2_TG_ARN="arn:aws:elasticloadbalancing:us-east-1:621648307412:targetgroup/DdevDe-QA2Ta-BCSVC4L5YB6E/72d7b318fe75417b"
```

Save these in `~/.bashrc` for persistence across sessions.