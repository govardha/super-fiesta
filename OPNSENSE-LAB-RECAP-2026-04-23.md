# OPNsense Lab Deployment Recap

**Date:** 2026-04-23 ~21:13 EDT (updated 2026-04-24 ~06:06 EDT)  
**Branch:** `feature/opnsense-lab`  
**Status:** Stack split into Network + Compute — ready to deploy, not yet successfully deployed

---

## Accounts

| Account | ID | Profile | Purpose |
|---------|----|---------|---------|
| Sandbox | 621648307412 | admin-sandbox | Where OpnsenseLab stacks deploy |
| Deployment | 766789219588 | admin-deployment | Where the CDK Pipeline lives |

## AMIs

| AMI | ID | ENA | Description |
|-----|----|-----|-------------|
| OPNsense 26.1.2-nano (original) | ami-02ea554632d1563a4 | No | Raw import, doesn't boot with custom block devices |
| OPNsense 26.1.2-nano-ena | ami-0d259cdfc1ac41fb6 | Yes | Re-registered with ENA flag, boots on Nitro |
| OPNsense 26.1.2-golden | ami-0f897fd3666bef06c | Yes | Fully configured: SSH, GUI, NAT, gateway, 10GB disk |
| AlmaLinux 9.6 | ami-085a9166f08849956 | Yes | 50GB min volume |

- OPNsense has no ENA → must use pre-Nitro instances (t2 family)
- AlmaLinux has ENA → can use Nitro/AMD instances (t3a family)

## Instance Types

| Instance | Type | Reason |
|----------|------|--------|
| OPNsense firewall | t2.micro | No ENA support, cheapest non-Nitro |
| AlmaLinux private EC2 | t3a.micro | AMD, cheapest Nitro option |

## What was fixed (2026-04-23)

1. **`app.py`** — stripped to only `OpnsenseLabStack` (direct) + `OpnsenseLabPipelineStack`
2. **`configs/config.py`** — changed `t.substitute()` → `t.safe_substitute()` so missing env vars for other accounts don't crash YAML parsing
3. **`stacks/pipeline/pipeline_stack.py`** — switched `ShellStep` → `CodeBuildStep` with `env` vars + `role_policy_statements` for cross-account `sts:AssumeRole`
4. **`stacks/opnsense_lab/opnsense_lab_stack.py`** — rewrote OPNsense instance to use explicit `CfnInstance` with both WAN+LAN ENIs attached at launch (avoids multi-ENI EIP association errors). EIP targets WAN ENI directly by ID.
5. **`configs/infrastructure.yaml`** — `opnsense_instance_type: t2.micro`, `instance_type: t3a.micro`, `ebs_volume_size: 50`
6. **Sandbox CDK bootstrap** — re-bootstrapped with `--trust 766789219588`, qualifier `govjuly25`, stack name `CDKBootstrap-govjuly25`

## What changed (2026-04-24)

Split monolithic `OpnsenseLabStack` into two stacks for faster EC2 debugging iteration:

| Stack | File | CloudFormation Name | Contains |
|-------|------|---------------------|----------|
| `OpnsenseLabNetworkStack` | `stacks/opnsense_lab/network_stack.py` | `OpnsenseLabNetwork` | VPC, public+private subnets, IGW, SSM VPC endpoints |
| `OpnsenseLabComputeStack` | `stacks/opnsense_lab/compute_stack.py` | `OpnsenseLabCompute` | Security groups, WAN/LAN ENIs, OPNsense CfnInstance, EIP, private route, AlmaLinux EC2 |

- `ComputeStack` takes `network: OpnsenseLabNetworkStack` as constructor arg — CDK auto-creates cross-stack dependency via CloudFormation exports
- Deploy network once, iterate on compute independently
- Original `opnsense_lab_stack.py` kept for reference (no longer imported)

## Resume — Deploy the stacks

```bash
cd ~/src/super-fiesta
aps admin-sandbox

# Ensure key pair exists
aws ec2 describe-key-pairs --key-names opnsense-lab-key --region us-east-1
# If missing:
# aws ec2 import-key-pair --key-name opnsense-lab-key --public-key-material fileb://$HOME/.ssh/id_ed25519.pub --region us-east-1

# Clean up any old monolithic stack first
aws cloudformation delete-stack --stack-name OpnsenseLabStack --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name OpnsenseLabStack --region us-east-1

# Deploy network first (VPC, subnets, endpoints — stable, deploy once)
cdk deploy OpnsenseLabNetwork

# Deploy compute (EC2s, ENIs, EIP — iterate on this one)
cdk deploy OpnsenseLabCompute

# Or deploy both at once
cdk deploy OpnsenseLabNetwork OpnsenseLabCompute
```

### Iterating on compute only

```bash
# Tear down and redeploy just compute (network stays up)
cdk destroy OpnsenseLabCompute
cdk deploy OpnsenseLabCompute
```

## After deploy — test OPNsense

```bash
# Get stack outputs (now from Compute stack)
aws cloudformation describe-stacks --stack-name OpnsenseLabCompute --query 'Stacks[0].Outputs' --output table --region us-east-1

# Web GUI (default creds: root / opnsense)
# https://<EIP>:443
# Note: no serial console on t2 (non-Nitro)

# SSH to OPNsense
ssh root@<EIP>

# SSM to AlmaLinux
aws ssm start-session --target <AlmaInstanceId>
```

## Later — fix the pipeline

```bash
git add -A
git commit -m "fix: explicit ENIs, correct instance types and volumes"
git push origin feature/opnsense-lab

aps admin-deployment
cdk deploy OpnsenseLabPipeline \
  -c sandbox_account_id=621648307412 \
  -c deployment_account_id=766789219588 \
  -c deployment_account_region=us-east-1
```

## Architecture

```
Internet → IGW → [Public Subnet: OPNsense WAN ENI + EIP]
                  [Private Subnet: OPNsense LAN ENI ← AlmaLinux EC2]
Private route table: 0.0.0.0/0 → OPNsense LAN ENI
SSM VPC Endpoints: ssm, ssm-messages, ec2-messages (for AlmaLinux access before OPNsense NAT is configured)
```

## Known issues / TODO

- OPNsense AMI has no ENA — consider rebuilding with ENA enabled to use cheaper t3a instances
- Pipeline works but takes a long time — direct `cdk deploy` is faster for iteration
- No serial console access on t2 — must configure OPNsense via web GUI or SSH only
- OPNsense needs manual configuration after launch (assign WAN/LAN interfaces, NAT rules)
- Pipeline still references old monolithic `OpnsenseLabStack` — needs updating for split stacks
