# OPNsense Lab — Session Recap & Continuation Guide

> Date: 2026-04-23
> Branch: `feature/opnsense-lab`
> Status: Code complete, synth verified, key pair imported. Ready to deploy.

---

## What Was Built This Session

A standalone CDK Pipeline that deploys an OPNsense firewall lab into the sandbox account. This is a POC to learn CDK Pipelines and test OPNsense as a NAT/firewall appliance.

### Architecture

```
Deployment Account (766789219588)
  └── OpnsenseLabPipeline (CodePipeline)
        ├── Source: govardha/super-fiesta @ feature/opnsense-lab
        ├── Synth: pip install + cdk synth
        └── SandboxDeploy stage → Sandbox Account (621648307412)

Sandbox Account (621648307412)
  └── OpnsenseLabStack
        ├── VPC (10.10.0.0/16, single AZ)
        │     ├── Public Subnet  → OPNsense WAN ENI + EIP
        │     └── Private Isolated Subnet → OPNsense LAN ENI + AlmaLinux EC2
        ├── OPNsense EC2 (t3.large, ami-02ea554632d1563a4)
        │     ├── WAN ENI (device 0, public subnet, source/dest check OFF)
        │     ├── LAN ENI (device 1, private subnet, source/dest check OFF)
        │     └── EIP attached to instance
        ├── AlmaLinux 9 EC2 (m5.large, private subnet, SSM only)
        ├── SSM VPC Endpoints (SSM, SSM_MESSAGES, EC2_MESSAGES)
        ├── Private route table: 0.0.0.0/0 → OPNsense LAN ENI
        └── Key pair: opnsense-lab-key (already imported)
```

### Cross-Account Bootstrap (Verified)

| Account | ID | Bootstrap | Trust |
|---|---|---|---|
| Deployment | 766789219588 | `CDKToolkit-govjuly25` | TrustedAccountsForLookup: sandbox, dev, prod |
| Sandbox | 621648307412 | `CDKToolkit-govjuly25` | TrustedAccounts: 766789219588 (deployment) |

Both use qualifier `govjuly25`. Sandbox trusts deployment for cross-account pipeline deploys.

---

## Files Created/Modified

### New files
| File | Purpose |
|---|---|
| `stacks/opnsense_lab/opnsense_lab_stack.py` | VPC + OPNsense EC2 (dual ENI) + AlmaLinux EC2 + SSM endpoints |
| `stacks/pipeline/pipeline_stack.py` | CDK Pipeline in deployment account, deploys to sandbox |
| `stages/opnsense_lab_stage.py` | Pipeline stage wrapper for OpnsenseLabStack |
| `OPNSENSE-SSM-ACCESS.md` | Guide for accessing OPNsense Web GUI via SSM port forwarding |
| `SUPER-FIESTA-REFERENCE.md` | Full repo reference doc for AI-assisted development |
| `.env` | Local env vars for synth (gitignored) |

### Modified files
| File | Change |
|---|---|
| `configs/infrastructure.yaml` | Added `opnsense_lab:` section (VPC, AMI, instance types, key pair) |
| `configs/models.py` | Added `OpnsenseLabVpcConfig`, `OpnsenseLabConfig` dataclasses + field on `InfrastructureSpec` |
| `configs/config.py` | Added parsing for `opnsense_lab` section. Fixed CRLF line endings. |
| `app.py` | Added `OpnsenseLabPipelineStack` using deployment/sandbox accounts from cdk.json context |
| `requirements.txt` | Added `python-dotenv` and `cdk-ec2-spot-simple` (were missing, would break pipeline synth) |

---

## Current Config Values (`configs/infrastructure.yaml` → `opnsense_lab:`)

```yaml
opnsense_lab:
  vpc:
    cidr: "10.10.0.0/16"
    max_azs: 2
    subnet_mask: 24
  instance_type: "m5.large"          # AlmaLinux
  os_version: "9"                     # AlmaLinux 9
  ebs_volume_size: 20                 # AlmaLinux root volume
  opnsense_ami: "ami-02ea554632d1563a4"
  opnsense_instance_type: "t3.large"  # Nitro required for serial console
  key_pair_name: "opnsense-lab-key"
```

---

## What's Done

- [x] Branch `feature/opnsense-lab` created
- [x] Config system extended (YAML + dataclass + parser)
- [x] OpnsenseLabStack with full OPNsense networking (dual ENI, EIP, route table, source/dest check)
- [x] CDK Pipeline (deployment account → sandbox account)
- [x] Pipeline stage wrapper
- [x] `cdk ls` and `cdk synth` verified — all stacks pass
- [x] Key pair imported to sandbox: `opnsense-lab-key` (key-0e276a2e88ca8bcc8, ed25519)
- [x] SSM port forwarding access doc written

---

## What's Next — Deploy Steps

### 1. Push the branch to GitHub
```bash
cd ~/src/super-fiesta
git add -A

git commit -m "feat: OPNsense lab pipeline and stack"
git push -u origin feature/opnsense-lab
```

### 2. Deploy the pipeline stack to the deployment account
```bash
cdk deploy OpnsenseLabPipeline --profile admin-deployment --region us-east-1
```
This creates the CodePipeline in the deployment account. The pipeline will then self-mutate and deploy the OpnsenseLabStack into sandbox.

### 3. Monitor the pipeline
Check CodePipeline in the deployment account (766789219588) console, or:
```bash
aws codepipeline get-pipeline-state --name OpnsenseLab --profile admin-deployment --region us-east-1
```

### 4. After deployment — configure OPNsense
See the Autoize guide steps (serial console setup):
1. Connect to OPNsense EC2 serial console (AWS Console → EC2 → Connect → EC2 Serial Console)
2. Login: `root` / `opnsense`
3. Assign interfaces: `ena0` = WAN, `ena1` = LAN
4. Set LAN to static IP (the private IP assigned to the LAN ENI)
5. Disable referrer check in `/conf/config.xml`
6. Access Web GUI via SSM port forwarding (see `OPNSENSE-SSM-ACCESS.md`)

### 5. Access OPNsense Web GUI via SSM (no public exposure)
```bash
ALMA_ID=$(aws cloudformation describe-stacks \
  --stack-name SandboxDeploy-OpnsenseLabStack \
  --query 'Stacks[0].Outputs[?OutputKey==`AlmaInstanceId`].OutputValue' \
  --output text --profile admin-sandbox --region us-east-1)

OPNSENSE_LAN_IP=$(aws ec2 describe-network-interfaces \
  --filters "Name=description,Values=OPNsense LAN interface" \
  --query 'NetworkInterfaces[0].PrivateIpAddress' \
  --output text --profile admin-sandbox --region us-east-1)

aws ssm start-session \
  --target $ALMA_ID \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$OPNSENSE_LAN_IP\"],\"portNumber\":[\"443\"],\"localPortNumber\":[\"8443\"]}" \
  --profile admin-sandbox --region us-east-1
```
Then open `https://localhost:8443` in your browser.

---

## AWS Profiles Reference

| Profile | Account | ID |
|---|---|---|
| `admin-deployment` | Deployment | 766789219588 |
| `admin-sandbox` | Sandbox | 621648307412 |

SSO session: `rinku` (`aws sso login --sso-session rinku`)

---

## Key Repo Patterns (for AI context)

- **Config-driven**: all infra params in `configs/infrastructure.yaml`, parsed via `AppConfigs().get_infrastructure_info(account_name)`, typed via dataclasses in `models.py`
- **Deep merge**: globals + account-specific config merged via `utils/converters.py` → `update()`
- **Env var substitution**: `${VAR_NAME}` in YAML resolved from `.env` or system env
- **Cross-stack VPC sharing**: `SimpleNetworkStack` exposes `self.vpc`, downstream stacks accept `vpc: ec2.IVpc` as constructor param
- **OPNsense lab is standalone**: its own VPC, its own pipeline, doesn't touch any existing stacks
- **Pipeline pattern**: PipelineStack (deployment account) → Stage → Stack (sandbox account)

---

## Potential Issues to Watch For

1. **Pipeline synth needs env vars**: The `.env` file is gitignored. The pipeline's CodeBuild synth step won't have these env vars. You may need to set them as CodeBuild environment variables or use Secrets Manager. The existing stacks (SimpleNetwork, Compute, etc.) all call `get_infrastructure_info("sandbox")` which requires `SANDBOX_ACCOUNT_ID` and `SANDBOX_REGION`.

2. **OPNsense serial console**: Requires Nitro instance type (t3.large is Nitro ✓). First boot may take a few minutes.

3. **OPNsense LAN IP**: After deploy, the LAN ENI gets a DHCP-assigned IP from the private subnet. You need this IP for both the OPNsense static LAN config and the SSM port forwarding. Get it from: `aws ec2 describe-network-interfaces --filters "Name=description,Values=OPNsense LAN interface"`

4. **WAN SG is currently open**: Ports 22/443/8443 are open to 0.0.0.0/0. Once SSM port forwarding is confirmed working, consider removing these inbound rules.
