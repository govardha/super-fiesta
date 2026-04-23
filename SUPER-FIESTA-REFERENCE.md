# super-fiesta CDK Reference — AI-Assisted Development Guide

> Last updated: 2026-04-23
> CDK version: aws-cdk-lib==2.205.0
> Python CDK app — bootstrap qualifier: `govjuly25`

---

## 1. Repo Structure

```
super-fiesta/
├── app.py                          # CDK entry point — instantiates all stacks
├── cdk.json                        # CDK config, bootstrap qualifier, feature flags
├── configs/
│   ├── infrastructure.yaml         # ALL infrastructure parameters (YAML + env var substitution)
│   ├── models.py                   # Dataclass models for typed config
│   ├── config.py                   # AppConfigs loader — YAML parsing, env var resolution, deep merge
│   └── constants.py                # CodeStar connection ARN, GitHub repo name
├── utils/
│   ├── converters.py               # to_dict() and update() (deep merge) helpers
│   ├── logger.py                   # Color-coded custom logger with LOG_LEVEL env var support
│   └── userdata_customizer.py      # Simple string template substitution for user data
├── stages/
│   └── infrastructure_stage.py     # CDK Pipeline Stage (minimal, placeholder for pipeline pattern)
├── stacks/
│   ├── core_network/
│   │   └── simple_network_stack.py # Shared VPC — fck-nat, public+private subnets
│   ├── compute/
│   │   └── compute_stack.py        # AlmaLinux EC2 instances (spot or on-demand)
│   ├── alma_asg/
│   │   ├── alma_asg_stack.py       # Auto Scaling Group — spot-preferred with on-demand fallback
│   │   └── lambda/
│   │       ├── refresh_handler.py           # Daily scheduled refresh Lambda
│   │       └── aggressive_refresh_handler.py # Every-15-min aggressive spot pursuit Lambda
│   ├── vpc_endpoints/
│   │   └── vpc_endpoints_stack.py  # VPC Interface Endpoints demo (isolated subnets, no NAT)
│   ├── ddev_demo/
│   │   └── ddev_demo_stack.py      # DDEV QA environment — ALB, WAF, Ubuntu, traefik
│   └── super_fiesta/
│       └── super_fiesta_stack.py   # Empty placeholder stack (original CDK init)
├── scripts/
│   ├── create-site.sh              # Generates DDEV PHP sites with random color themes
│   └── verify-fck-nat.sh           # Tests NAT connectivity using IMDSv2
├── tests/unit/
│   └── test_super_fiesta_stack.py  # Placeholder test only
├── requirements.txt                # aws-cdk-lib, constructs, dacite, pre-commit, ruff
├── requirements-dev.txt            # pytest
├── README.md                       # VPC Endpoints demo guide
└── DDEV-README.md                  # QA environment management guide
```

---

## 2. Configuration System

This is the most important thing to understand. All infrastructure is config-driven.

### How it works

1. `configs/infrastructure.yaml` has a `globals:` section and an `accounts:` list
2. `AppConfigs.get_infrastructure_info(account_name)` loads the YAML, finds the matching account, and **deep-merges** account-specific values over globals
3. Environment variables are substituted using `${VAR_NAME}` syntax in YAML (via `string.Template`)
4. The merged dict is converted to typed dataclasses via `dacite.from_dict()`
5. The result is an `InfrastructureSpec` object passed to every stack

### Required environment variables (or `.env` file)

| Account     | Variables needed                              |
|-------------|-----------------------------------------------|
| sandbox     | `SANDBOX_ACCOUNT_ID`, `SANDBOX_REGION`        |
| production  | `PRODUCTION_ACCOUNT_ID`, `PRODUCTION_REGION`  |
| development | `DEV_ACCOUNT_ID`, `DEV_REGION`                |
| (optional)  | `NOTIFICATION_EMAIL`, `TAILSCALE_AUTH_KEY`    |

### Dataclass hierarchy (`configs/models.py`)

```
InfrastructureSpec
├── account: str
├── region: str
├── vpc: VpcConfig (cidr, max_azs, subnet_mask, dns settings, nat_gateways)
├── ec2: Ec2Config (instance_type, class, size, ami_id, key_name)
├── compute: ComputeConfig
│   ├── instances: list[ComputeInstanceConfig]  (name, type, EBS, spot, data volume)
│   ├── almalinux_amis: dict[region][version] → ami_id
│   └── asg: ASGConfig (enabled, instance types, capacity, refresh settings)
├── logging: LoggingConfig (flow_logs_group_name, retention_days)
├── endpoints: EndpointsConfig → list[EndpointService] (name, service)
└── waf: WafConfig (enabled, rules, geo-blocking, IP allowlist, rate limiting)
```

### Current account CIDRs

| Account     | CIDR           |
|-------------|----------------|
| sandbox     | 10.1.0.0/16    |
| production  | 10.2.0.0/16    |
| development | 10.3.0.0/16    |
| (globals)   | 10.0.0.0/16    |

---

## 3. Stack Dependency Graph

```
app.py
 │
 ├── SimpleNetworkStack ("SimpleNetwork")
 │     ↓ vpc passed directly
 │   ├── ComputeStack ("ComputeStack")          [depends on SimpleNetwork]
 │   └── AlmaASGStack ("AlmaASGStack")           [depends on SimpleNetwork, conditional on asg.enabled]
 │
 ├── VpcInterfaceEndpointsStack ("VpcInterfaceEndpointsStack")  [standalone VPC]
 ├── DdevDemoStack ("DdevDemoStack")                             [standalone VPC]
 └── SuperFiestaStack ("SuperFiestaStack")                       [empty placeholder]
```

Key pattern: SimpleNetwork creates the shared VPC. ComputeStack and AlmaASGStack receive `vpc` as a constructor parameter. The other stacks create their own VPCs.

---

## 4. Stack-by-Stack Reference

### 4.1 SimpleNetworkStack (`stacks/core_network/simple_network_stack.py`)

**Purpose**: Shared VPC for compute workloads.

| Resource | Details |
|----------|---------|
| VPC | Config-driven CIDR, public + private subnets |
| NAT | fck-nat (t4g.nano ARM, ~$3/month vs $45 for AWS NAT GW) |
| AMI | `fck-nat-al2023-*-arm64-ebs` from owner `568608671756` |
| Exports | VpcId, VpcCidr, PublicSubnetIds, PrivateSubnetIds, AvailabilityZones |

**Cross-stack pattern**: Exposes `self.vpc` as a Python attribute. Downstream stacks receive it as a constructor arg (not Fn::ImportValue).

**fck-nat security group fix**: After VPC creation, adds ingress rule allowing all traffic from VPC CIDR — required because fck-nat needs to receive forwarded traffic.

### 4.2 ComputeStack (`stacks/compute/compute_stack.py`)

**Purpose**: AlmaLinux EC2 instances with flexible configuration.

| Feature | Details |
|---------|---------|
| OS | AlmaLinux 8 or 9 (AMI IDs from config `compute.almalinux_amis`) |
| Spot | Uses `cdk_ec2_spot_simple.SpotInstance` construct when `use_spot: true` |
| On-demand | Standard `ec2.Instance` when `use_spot: false` |
| EBS | Configurable root volume (type, size, IOPS, throughput) |
| Data volume | Optional persistent volume (delete_on_termination=False), auto-formatted XFS, fstab entry |
| Access | SSM only (AmazonSSMManagedInstanceCore), no SSH by default |
| User data | dnf update, basic tools, SSM agent verify, data volume mount, README generation |

**Instance loop**: Iterates `infra_config.compute.instances` list — each entry creates one EC2 instance.

### 4.3 AlmaASGStack (`stacks/alma_asg/alma_asg_stack.py`)

**Purpose**: Auto Scaling Group with aggressive spot optimization.

| Feature | Details |
|---------|---------|
| Strategy | Mixed instances policy — spot preferred, on-demand fallback |
| Instance types | Primary + 6 alternatives for spot availability |
| Spot allocation | `PRICE_CAPACITY_OPTIMIZED` strategy |
| On-demand % | Configurable (default 0% = 100% spot preference) |
| Capacity | min/max/desired all configurable (default: 1/1/1) |
| Notifications | SNS topic for ALL scaling events + email subscription |
| Monitoring | CloudWatch alarm when GroupInServiceInstances < 1 |
| IMDSv2 | Required on launch template |
| Spot interruption | Cron job on instance checks metadata every minute, publishes to SNS |

**Lambda: Daily Refresh** (`lambda/refresh_handler.py`)
- Runs at configurable UTC hour (default 3 AM)
- Checks if instances are on-demand via EC2 DescribeInstances → `InstanceLifecycle`
- If on-demand found AND `refresh_only_on_demand=true`: starts instance refresh
- Sends SNS notification with full details either way

**Lambda: Aggressive Spot Pursuit** (`lambda/aggressive_refresh_handler.py`)
- Runs every 15 minutes (configurable)
- If ANY on-demand instance exists: starts instance refresh (MinHealthyPercentage=0)
- Skips if refresh already in progress (checks `describe_instance_refreshes`)
- Goal: keep retrying until spot capacity becomes available

### 4.4 VpcInterfaceEndpointsStack (`stacks/vpc_endpoints/vpc_endpoints_stack.py`)

**Purpose**: Demo/learning stack for VPC Interface Endpoints.

| Feature | Details |
|---------|---------|
| VPC | Standalone, PRIVATE_ISOLATED subnets only, 0 NAT gateways |
| Endpoints | Config-driven from `endpoints.services` list |
| Default endpoints | SSM, SSM_MESSAGES, EC2_MESSAGES, EC2, STS, CLOUDWATCH_LOGS |
| Private DNS | Enabled on all endpoints |
| Test instance | Amazon Linux 2, pre-loaded test scripts (test-endpoints.sh, test-network.sh) |
| Flow logs | CloudWatch Logs with configurable retention |
| Service mapping | String-to-enum mapping in `create_vpc_endpoints()` |

**Adding new endpoints**: Add to `endpoints.services` in YAML AND add the enum mapping in `service_mapping` dict in the stack.

### 4.5 DdevDemoStack (`stacks/ddev_demo/ddev_demo_stack.py`)

**Purpose**: QA environment with DDEV, ALB, WAF, and traefik routing.

| Feature | Details |
|---------|---------|
| VPC | Standalone with fck-nat (same pattern as SimpleNetwork) |
| ALB | Internet-facing, public subnets |
| Certificate | Wildcard `*.webdev.vadai.org` (DNS validation via ACM) |
| HTTPS listener | Default 404, rule at priority 10 forwards `*.webdev.vadai.org` to traefik TG |
| HTTP listener | Redirects to HTTPS (permanent) |
| Target group | Single TG on port 80 → traefik router on EC2 |
| EC2 | Ubuntu 24.04, t3.micro, 20GB GP3, private subnet, SSM access |
| User data | apt update, Docker + docker-compose, SSM agent, verify-fck-nat.sh |

**WAF (WAFv2)**: Created only when `waf.enabled: true` in config.

| WAF Rule | Priority | Details |
|----------|----------|---------|
| IP Allow List | 1 | If IPs != ["0.0.0.0/0"], creates IP set + allow rule |
| Geo Blocking | 2 | Blocks configured countries (default: RU, CN, KP, IR) |
| AWS Common Rules | 3+ | AWSManagedRulesCommonRuleSet |
| Known Bad Inputs | 4+ | AWSManagedRulesKnownBadInputsRuleSet |
| SQLi Protection | 5+ | AWSManagedRulesSQLiRuleSet |
| Rate Limiting | last | Optional, 500 req/5min default |

**Default action logic**:
- If IP allowlist is set (not 0.0.0.0/0): BLOCK everything else (whitelist mode) with custom HTML block page
- If no IP restrictions: ALLOW (managed rules handle blocking)

### 4.6 SuperFiestaStack (`stacks/super_fiesta/super_fiesta_stack.py`)

Empty placeholder from `cdk init`. No resources.

---

## 5. Key Patterns & Conventions

### Config-driven everything
Every stack loads config via `AppConfigs().get_infrastructure_info(account_name)`. To change behavior, modify `infrastructure.yaml` first, not stack code.

### fck-nat pattern (used in SimpleNetwork + DdevDemo)
```python
nat_provider = ec2.NatInstanceProviderV2(
    instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.NANO),
    machine_image=ec2.LookupMachineImage(name="fck-nat-al2023-*-arm64-ebs", owners=["568608671756"])
)
# After VPC creation:
nat_provider.security_group.add_ingress_rule(ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.all_traffic())
```

### VPC sharing pattern
SimpleNetwork exposes `self.vpc`. Downstream stacks accept `vpc: ec2.IVpc` as constructor param. Dependencies set via `stack.add_dependency(network_stack)`.

### SSM-first access
All instances use `AmazonSSMManagedInstanceCore`. No SSH keys by default. Connect via `aws ssm start-session --target <instance-id>`.

### Spot instance strategy
- ComputeStack: per-instance `use_spot` flag using `cdk_ec2_spot_simple.SpotInstance`
- AlmaASGStack: ASG mixed instances policy with `PRICE_CAPACITY_OPTIMIZED` + Lambda-driven refresh

### User data pattern
All stacks build user data inline using `ec2.UserData.for_linux()` + `add_commands()`. No external scripts loaded.

---

## 6. Environment Setup & Deploy Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (or create .env file)
export SANDBOX_ACCOUNT_ID="<account-id>"
export SANDBOX_REGION="us-east-1"
export NOTIFICATION_EMAIL="<email>"

# List stacks
cdk ls

# Deploy individual stacks
cdk deploy SimpleNetwork
cdk deploy ComputeStack
cdk deploy AlmaASGStack
cdk deploy VpcInterfaceEndpointsStack
cdk deploy DdevDemoStack

# Deploy all
cdk deploy --all

# Destroy
cdk destroy <StackName>
```

### Bootstrap (first time per account/region)
```bash
cdk bootstrap --qualifier govjuly25
```

---

## 7. Adding New Features — Guidance for AI Agents

### Adding a new stack
1. Create `stacks/new_stack/new_stack.py` with a class extending `Stack`
2. Accept `account_name: str` param, load config via `AppConfigs().get_infrastructure_info(account_name)`
3. If it needs the shared VPC: accept `vpc: ec2.IVpc` param, add dependency in `app.py`
4. If standalone: create its own VPC (follow DdevDemo or VpcEndpoints pattern)
5. Add to `app.py` with proper `env=cdk.Environment(...)` 
6. Add any new config fields to `infrastructure.yaml` globals + account sections
7. Add corresponding dataclass fields to `configs/models.py`
8. Update `configs/config.py` to parse the new config section

### Adding a new config section
1. Add to `globals:` in `infrastructure.yaml`
2. Create a `@dataclass` in `models.py`
3. Add the field to `InfrastructureSpec`
4. Add parsing logic in `config.py` → `get_infrastructure_info()`

### Adding a new VPC endpoint
1. Add to `endpoints.services` in `infrastructure.yaml`
2. Add the enum mapping in `vpc_endpoints_stack.py` → `service_mapping` dict

### Adding a new compute instance
Add an entry to `compute.instances` in `infrastructure.yaml`:
```yaml
- name: "new-instance"
  instance_type: "t3.medium"
  ebs_volume_size: 30
  os: "almalinux"
  os_version: "9"
  use_spot: true
  subnet_type: "PRIVATE_WITH_EGRESS"
```

### Adding a new account/environment
Add to `accounts:` in `infrastructure.yaml`:
```yaml
- name: staging
  account: "${STAGING_ACCOUNT_ID}"
  region: "${STAGING_REGION}"
  vpc:
    cidr: "10.5.0.0/16"
```
Then add env var validation in `config.py` → `validate_required_env_vars()`.

### Modifying WAF rules
All WAF config is in `infrastructure.yaml` under `waf:`. Toggle managed rules with booleans. Add IPs to `allowed_ips`. Add country codes to `blocked_countries`.

---

## 8. External Dependencies

| Package | Purpose |
|---------|---------|
| `aws-cdk-lib` (2.205.0) | Core CDK library |
| `constructs` | CDK constructs base |
| `dacite` | Dict-to-dataclass conversion |
| `python-dotenv` | `.env` file loading (imported in config.py) |
| `cdk_ec2_spot_simple` | Third-party construct for spot instances (used in ComputeStack) |
| `pre-commit` + `ruff` | Code quality (not runtime) |

---

## 9. Current Limitations & Known State

- **Tests**: Only a placeholder test exists. No real test coverage.
- **SuperFiestaStack**: Empty — can be repurposed or removed.
- **Stage file**: `infrastructure_stage.py` is minimal/incomplete — pipeline pattern not fully implemented.
- **Single region**: All stacks currently deploy to sandbox (us-east-1). Multi-account deployment requires changing `account_name` in `app.py`.
- **AlmaLinux AMI**: Only us-east-1 AMIs configured. Other regions need AMI IDs added to `compute.almalinux_amis`.
- **DdevDemo routing**: Uses single traefik target group on port 80. Individual DDEV sites are managed manually on the instance (see DDEV-README.md).
- **python-dotenv**: Imported in `config.py` but not in `requirements.txt` — may need to be added.

---

## 10. Cost Profile (sandbox)

| Resource | Monthly Cost |
|----------|-------------|
| fck-nat (t4g.nano) | ~$3 |
| ComputeStack spot (m5.large) | ~$21-30 |
| AlmaASG spot (m5.large) | ~$21-30 |
| DdevDemo (t3.micro) | ~$8 |
| VPC Endpoints (6 endpoints) | ~$45 (6 × $7.50) |
| ALB | ~$18 |
| EBS volumes | ~$5-15 |

fck-nat saves ~$42/month per VPC vs AWS NAT Gateway.

---

## 11. Quick Command Reference

```bash
# Connect to any instance
aws ssm start-session --target <instance-id>

# Get ASG instance details
aws autoscaling describe-auto-scaling-groups \
  --auto-scaling-group-names AlmaASG-sandbox \
  --query 'AutoScalingGroups[0].Instances[0].[InstanceId,InstanceType,LifecycleState]'

# Check stack outputs
aws cloudformation describe-stacks --stack-name <StackName> --query 'Stacks[0].Outputs'

# Synth without deploying (validate)
cdk synth <StackName>

# Diff before deploy
cdk diff <StackName>

# Create DDEV site on DdevDemo instance
./scripts/create-site.sh qa3

# Verify fck-nat connectivity (run on instance)
./scripts/verify-fck-nat.sh
```
