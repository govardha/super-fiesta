# super-fiesta

AWS CDK Python infrastructure monorepo. Configuration-driven, multi-account, multi-stack architecture for lab and demo environments.

## Stacks

| Stack | Purpose |
|-------|---------|
| `OpnsenseLabNetwork` | VPC with public/private subnets, SSM VPC endpoints (OPNsense is the NAT) |
| `OpnsenseLabCompute` | OPNsense firewall (dual ENI) + private AlmaLinux EC2 |
| `OpnsenseLabPipeline` | CDK Pipeline deploying the lab into sandbox via CodePipeline |
| `SimpleNetwork` | Shared VPC with fck-nat (~$3/month) for compute workloads |
| `ComputeStack` | AlmaLinux EC2 instances (spot or on-demand, configurable EBS) |
| `AlmaASGStack` | Auto Scaling Group with aggressive spot optimization + Lambda refreshers |
| `X86BuildStack` | Ephemeral x86 build instance (c7a.8xlarge, AL2023, Docker) |
| `ArmBuildStack` | Ephemeral ARM build instance (c7g.8xlarge, AL2023, Docker) |
| `VpcInterfaceEndpointsStack` | VPC Interface Endpoints demo (isolated subnets, no NAT) |
| `DdevDemoStack` | DDEV QA environment — ALB, WAF, Ubuntu, Traefik |

## Architecture

```
app.py
 ├── OpnsenseLabNetworkStack → OpnsenseLabComputeStack
 ├── OpnsenseLabPipelineStack (deploys network+compute via CodePipeline)
 ├── SimpleNetworkStack → ComputeStack, AlmaASGStack, X86BuildStack, ArmBuildStack
 ├── VpcInterfaceEndpointsStack (standalone)
 └── DdevDemoStack (standalone)
```

## Configuration System

All infrastructure parameters live in `configs/infrastructure.yaml`. The loader (`configs/config.py`) deep-merges account-specific overrides onto `globals`, substitutes `${ENV_VARS}` from environment or `.env` file, and returns typed dataclasses (`configs/models.py`).

### Required Environment Variables

```bash
# .env or exported
SANDBOX_ACCOUNT_ID=123456789012
SANDBOX_REGION=us-east-1
# Optional for other environments:
PRODUCTION_ACCOUNT_ID=...
PRODUCTION_REGION=...
DEV_ACCOUNT_ID=...
DEV_REGION=...
```

### Account CIDRs

| Account | CIDR |
|---------|------|
| sandbox | 10.1.0.0/16 |
| production | 10.2.0.0/16 |
| development | 10.3.0.0/16 |
| opnsense_lab | 10.10.0.0/16 |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env  # Edit with your account IDs

# Synthesize
cdk synth

# Deploy OPNsense lab (current active development)
cdk deploy OpnsenseLabNetwork OpnsenseLabCompute

# Deploy build compute (ephemeral, tear down when done)
cdk deploy SimpleNetwork X86BuildStack ArmBuildStack

# Tear down build compute
cdk destroy X86BuildStack ArmBuildStack SimpleNetwork

# Deploy pipeline (deploys to sandbox via CodePipeline)
cdk deploy OpnsenseLabPipeline
```

## OPNsense Lab

The primary active project. Deploys an OPNsense firewall with dual ENIs acting as NAT gateway for a private AlmaLinux instance.

**Post-deploy manual steps** (OPNsense AMI requires serial console config on first boot):
1. Attach LAN ENI: `aws ec2 attach-network-interface ...` (see stack outputs)
2. Serial console: Assign interfaces (ena0=WAN, ena1=LAN), set IPs
3. Access AlmaLinux via SSM: `aws ssm start-session --target <instance-id>`

See `OPNSENSE-LAB-WHAT-WORKED.md` for the full runbook.

## Project Structure

```
├── app.py                       # CDK entry point
├── cdk.json                     # CDK config, bootstrap qualifier: govjuly25
├── configs/
│   ├── infrastructure.yaml      # All infra parameters
│   ├── config.py                # YAML loader + env var substitution
│   ├── models.py                # Typed dataclasses
│   └── constants.py             # CodeStar connection, GitHub repo
├── stages/
│   └── opnsense_lab_stage.py    # Pipeline stage for OPNsense lab
├── stacks/                      # One directory per stack
├── utils/                       # Logger, converters, helpers
├── scripts/                     # Shell utilities
└── tests/unit/                  # Placeholder tests
```

## Key Dependencies

- `aws-cdk-lib==2.205.0`
- `dacite` — dataclass deserialization
- `python-dotenv` — .env file loading
- `cdk-ec2-spot-simple` — spot instance construct
- `ruff` — linter/formatter
- `pre-commit` — git hooks

## Deployment Accounts

| Purpose | Account | Region |
|---------|---------|--------|
| Deployment (pipeline) | 766789219588 | us-east-1 |
| Sandbox (workloads) | via `$SANDBOX_ACCOUNT_ID` | via `$SANDBOX_REGION` |

## Cleanup

```bash
cdk destroy OpnsenseLabCompute OpnsenseLabNetwork
```
