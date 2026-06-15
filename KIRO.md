# KIRO.md — AI-Assisted Development Guide

Context file for AI assistants working on this codebase.

## Project Summary

AWS CDK Python monorepo deploying multi-account infrastructure. Configuration-driven via YAML with typed dataclass models. Primary active work is the OPNsense Lab (firewall + private EC2).

## Tech Stack

- **CDK**: `aws-cdk-lib==2.205.0`, Python, bootstrap qualifier `govjuly25`
- **Config**: YAML → deep merge → `dacite` → typed dataclasses
- **Env vars**: `python-dotenv`, `${VAR}` substitution in YAML
- **Spot**: `cdk-ec2-spot-simple` construct
- **Lint/Format**: `ruff` (Black-compatible), `pre-commit`
- **Tests**: `pytest` (placeholder only currently)

## Key Patterns

### Configuration Flow

```
configs/infrastructure.yaml
  → AppConfigs.get_infrastructure_info(account_name)
    → deep-merge globals + account overrides
    → env var substitution (${SANDBOX_ACCOUNT_ID})
    → dacite.from_dict → InfrastructureSpec dataclass
```

All stacks receive an `InfrastructureSpec` instance. Never hardcode account IDs, regions, or CIDRs.

### Stack Dependencies

```
OpnsenseLabNetworkStack → OpnsenseLabComputeStack (network passed as constructor arg)
SimpleNetworkStack → ComputeStack, AlmaASGStack, X86BuildStack, ArmBuildStack (vpc passed as constructor arg)
VpcInterfaceEndpointsStack (standalone VPC)
DdevDemoStack (standalone VPC)
```

Cross-stack references use Python object attributes (not CloudFormation exports/Fn::ImportValue).

### Adding a New Stack

1. Create `stacks/<name>/<name>_stack.py`
2. Add config section to `configs/infrastructure.yaml` under `globals:`
3. Add dataclass to `configs/models.py` if needed
4. Wire into `AppConfigs.get_infrastructure_info()` in `configs/config.py`
5. Instantiate in `app.py`

### Adding Config Fields

1. Add field to `configs/infrastructure.yaml` (globals + account overrides)
2. Add corresponding field to dataclass in `configs/models.py`
3. Parse in `configs/config.py` `get_infrastructure_info()`

## File Map

| Path | Purpose |
|------|---------|
| `app.py` | CDK entry point, instantiates all stacks |
| `configs/infrastructure.yaml` | All infra parameters |
| `configs/config.py` | YAML loader, env var substitution, deep merge |
| `configs/models.py` | Typed dataclasses (`InfrastructureSpec`, `VpcConfig`, etc.) |
| `configs/constants.py` | CodeStar connection ARN, GitHub repo |
| `stacks/opnsense_lab/network_stack.py` | VPC, subnets, SSM endpoints |
| `stacks/opnsense_lab/compute_stack.py` | OPNsense (CfnInstance), AlmaLinux (ec2.Instance) |
| `stacks/build_compute/build_stack.py` | BuildStack class (parameterized by cpu_arch) |
| `stacks/build_compute/userdata/build_setup.sh` | Shared userdata for both build stacks |
| `stacks/core_network/simple_network_stack.py` | Shared VPC with fck-nat |
| `stacks/pipeline/pipeline_stack.py` | CDK Pipelines for CI/CD |
| `stages/opnsense_lab_stage.py` | Pipeline stage grouping network+compute |
| `utils/converters.py` | `to_dict()`, `update()` (deep merge) |
| `utils/logger.py` | Color-coded logger with `LOG_LEVEL` support |

## Conventions

- **Formatting**: ruff (Black defaults), 88 char lines, double quotes, trailing commas
- **Imports**: sorted (stdlib, third-party, local) separated by blank lines
- **IAM**: No wildcards — explicit actions and resources
- **Removal policy**: `RETAIN` on stateful resources in prod
- **No hardcoded accounts**: Use `${ENV_VARS}` in YAML, CDK_DEFAULT_ACCOUNT/REGION in code
- **Stack names**: PascalCase matching CloudFormation convention
- **Scripts**: `set -euo pipefail`, 2-space indent, `[[` conditionals

## Environment Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # Set SANDBOX_ACCOUNT_ID, SANDBOX_REGION
cdk synth             # Validates everything compiles
```

## Current State (as of 2026-06)

- **Active**: OPNsense Lab (network + compute split, pipeline) + Build Compute stacks
- **Working**: Golden AMI `ami-0c7eb0df432665ef3` with NAT, SSH, GUI preconfigured
- **Build Compute**: X86BuildStack (c7a.8xlarge) + ArmBuildStack (c7g.8xlarge) — ephemeral, deploy/destroy per session
- **Manual steps remain**: LAN ENI attach + interface reassignment via serial console after fresh deploy
- **Inactive**: ComputeStack/AlmaASGStack/DdevDemo (functional but not deployed)

## Build Compute Stacks

Ephemeral high-performance instances for Python compilation via Docker.

- **Lego-block pattern**: `SimpleNetworkStack` provides VPC/fck-nat, build stacks plug in
- **Deploy**: `cdk deploy SimpleNetwork X86BuildStack ArmBuildStack --profile admin-sandbox`
- **Destroy**: `cdk destroy X86BuildStack ArmBuildStack SimpleNetwork --profile admin-sandbox`
- **UserData**: `stacks/build_compute/userdata/build_setup.sh` — edit once, both stacks get it
- **Config**: `build_compute` section in `infrastructure.yaml` (instance types, EBS size, S3 bucket)
- **IAM**: SSM + S3 scoped to `arn:aws:s3:::govstuff-304232106942/python/*`
- **SG**: Egress-only (443/80 out, no inbound)

## Gotchas

1. OPNsense CfnInstance must NOT have custom block device mappings — breaks FreeBSD boot
2. OPNsense launches with WAN ENI only; LAN ENI attached manually after serial console config
3. `cdk.json` has context values with deployment account IDs — these are non-secret (pipeline account)
4. The `.env` file is gitignored; env vars are required for synth
5. `cdk-ec2-spot-simple` is a third-party construct — check compatibility on CDK upgrades
6. fck-nat uses ARM AMI (`t4g.nano`) — don't switch to x86 instance types
7. AL2023 does not have `nvim` or `neovim` in base repos — use `vim` or install from EPEL
8. SG descriptions must be ASCII only — no em dashes or unicode
9. Sandbox account vCPU quota was increased to support c7a.8xlarge (32 vCPU)
