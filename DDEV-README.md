# Adding More QA Sites: qa-manick1 & qa-manick2

## Option 1: Quick Manual Setup (Fastest)

Since you already have the ELB and instance running, you can add more sites manually:

### Step 1: Create Target Groups Manually
```bash
# Create target group for qa-manick1
aws elbv2 create-target-group \
  --name qa-manick1-tg \
  --protocol HTTP \
  --port 8003 \
  --vpc-id $(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=*DdevDemo*" --query 'Vpcs[0].VpcId' --output text) \
  --health-check-path /health \
  --health-check-port 8003 \
  --target-type instance

# Create target group for qa-manick2  
aws elbv2 create-target-group \
  --name qa-manick2-tg \
  --protocol HTTP \
  --port 8004 \
  --vpc-id $(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=*DdevDemo*" --query 'Vpcs[0].VpcId' --output text) \
  --health-check-path /health \
  --health-check-port 8004 \
  --target-type instance
```

### Step 2: Add Listener Rules to Existing ALB
```bash
# Get your ALB ARN
ALB_ARN=$(aws cloudformation describe-stacks \
  --stack-name DdevDemoStack \
  --query 'Stacks[0].Outputs[?contains(OutputKey, `LoadBalancer`)].OutputValue' \
  --output text)

# Get HTTPS listener ARN
LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn $ALB_ARN \
  --query 'Listeners[?Port==`443`].ListenerArn' --output text)

# Add listener rule for qa-manick1 (priority 130)
aws elbv2 create-rule \
  --listener-arn $LISTENER_ARN \
  --priority 130 \
  --conditions Field=host-header,Values=qa-manick1.vadai.org \
  --actions Type=forward,TargetGroupArn=$(aws elbv2 describe-target-groups --names qa-manick1-tg --query 'TargetGroups[0].TargetGroupArn' --output text)

# Add listener rule for qa-manick2 (priority 140)
aws elbv2 create-rule \
  --listener-arn $LISTENER_ARN \
  --priority 140 \
  --conditions Field=host-header,Values=qa-manick2.vadai.org \
  --actions Type=forward,TargetGroupArn=$(aws elbv2 describe-target-groups --names qa-manick2-tg --query 'TargetGroups[0].TargetGroupArn' --output text)
```

### Step 3: Create DDEV Sites
```bash
# SSH into your instance
ssh ubuntu@your-instance-ip

# Create qa-manick1
mkdir -p /home/ubuntu/qa-manick1-site
cd /home/ubuntu/qa-manick1-site

echo "<h1>🚀 QA-Manick1 Environment</h1><p>Manick's first test site</p>" > index.html
echo "OK" > health

ddev config --project-name=qa-manick1 --project-type=php --docroot=""

cat > .ddev/config.yaml << 'EOF'
name: qa-manick1
type: php
docroot: ""
php_version: "8.2"
webserver_type: nginx-fpm
router_http_port: "8003"
router_https_port: "8004"
xdebug_enabled: false
omit_containers: [db]
use_dns_when_possible: false
disable_upload_dirs_warning: true
bind_all_interfaces: true
EOF

cat > .ddev/docker-compose.override.yaml << 'EOF'
version: '3.6'
services:
  web:
    ports:
      - "0.0.0.0:8003:80"
EOF

ddev start

# Create qa-manick2
mkdir -p /home/ubuntu/qa-manick2-site
cd /home/ubuntu/qa-manick2-site

echo "<h1>🚀 QA-Manick2 Environment</h1><p>Manick's second test site</p>" > index.html
echo "OK" > health

ddev config --project-name=qa-manick2 --project-type=php --docroot=""

cat > .ddev/config.yaml << 'EOF'
name: qa-manick2
type: php
docroot: ""
php_version: "8.2"
webserver_type: nginx-fpm
router_http_port: "8005"
router_https_port: "8006"
xdebug_enabled: false
omit_containers: [db]
use_dns_when_possible: false
disable_upload_dirs_warning: true
bind_all_interfaces: true
EOF

cat > .ddev/docker-compose.override.yaml << 'EOF'
version: '3.6'
services:
  web:
    ports:
      - "0.0.0.0:8004:80"
EOF

ddev start
```

### Step 4: Register Instances with Target Groups
```bash
# From your local machine, register both
aws elbv2 register-targets \
  --target-group-arn $(aws elbv2 describe-target-groups --names qa-manick1-tg --query 'TargetGroups[0].TargetGroupArn' --output text) \
  --targets Id=i-0fc2162fe216dd21f,Port=8003

aws elbv2 register-targets \
  --target-group-arn $(aws elbv2 describe-target-groups --names qa-manick2-tg --query 'TargetGroups[0].TargetGroupArn' --output text) \
  --targets Id=i-0fc2162fe216dd21f,Port=8004
```

## Option 2: Update CDK (Better Long-term)

Add to your `ddev_demo_stack.py`:

```python
# Add to create_target_groups method:
def create_target_groups(self):
    # ... existing qa1/qa2 code ...
    
    # Add qa-manick1 target group
    self.qa_manick1_tg = elbv2.ApplicationTargetGroup(
        self,
        "QAManick1TargetGroup",
        vpc=self.vpc,
        port=8003,
        protocol=elbv2.ApplicationProtocol.HTTP,
        target_type=elbv2.TargetType.INSTANCE,
        health_check=elbv2.HealthCheck(
            enabled=True,
            healthy_http_codes="200,404",
            path="/health",
            port="8003",
            protocol=elbv2.Protocol.HTTP,
        ),
    )
    
    # Add qa-manick2 target group
    self.qa_manick2_tg = elbv2.ApplicationTargetGroup(
        self,
        "QAManick2TargetGroup",
        vpc=self.vpc,
        port=8004,
        protocol=elbv2.ApplicationProtocol.HTTP,
        target_type=elbv2.TargetType.INSTANCE,
        health_check=elbv2.HealthCheck(
            enabled=True,
            healthy_http_codes="200,404",
            path="/health",
            port="8004",
            protocol=elbv2.Protocol.HTTP,
        ),
    )
    
    # Add listener rules
    self.https_listener.add_action(
        "QAManick1ListenerRule",
        priority=130,
        conditions=[
            elbv2.ListenerCondition.host_headers(["qa-manick1.vadai.org"])
        ],
        action=elbv2.ListenerAction.forward([self.qa_manick1_tg])
    )
    
    self.https_listener.add_action(
        "QAManick2ListenerRule", 
        priority=140,
        conditions=[
            elbv2.ListenerCondition.host_headers(["qa-manick2.vadai.org"])
        ],
        action=elbv2.ListenerAction.forward([self.qa_manick2_tg])
    )
```

Then redeploy:
```bash
cdk deploy DdevDemoStack
```

## Recommendation

**Use Option 1** for now since it's much faster. You can always update the CDK later for proper infrastructure as code.

The manual approach gets you up and running in 5 minutes vs having to redeploy the CDK stack.