# OPNsense Lab - What Actually Worked

**Date:** 2026-04-24  
**Branch:** `feature/opnsense-lab`  
**Status:** OPNsense + AlmaLinux running, SSH and Web GUI accessible

---

## Step 0: Import OPNsense nano image as an AMI

### Download and extract the image

```bash
# Download the OPNsense nano image (use /tmp if on CloudShell — home dir is only 1GB)
curl -O https://opnsense-mirror.hiho.ch/releases/26.1/OPNsense-26.1.2-nano-amd64.img.bz2

# Extract
bzip2 -d OPNsense-26.1.2-nano-amd64.img.bz2

# Rename .img to .raw
mv OPNsense-26.1.2-nano-amd64.img OPNsense-26.1.2-nano-amd64.raw
```

### Upload to S3

```bash
# Create a bucket (or use an existing one, must be same region as target AMI)
aws s3 mb s3://opnsense-imgs --region us-east-1 --profile admin-sandbox

# Upload the raw image
aws s3 cp OPNsense-26.1.2-nano-amd64.raw s3://opnsense-imgs/ \
  --region us-east-1 --profile admin-sandbox
```

### Import as a snapshot

```bash
# Create the import container spec
cat > /tmp/containers.json << 'EOF'
{
  "Description": "OPNsense 26.1.2",
  "Format": "RAW",
  "UserBucket": {
    "S3Bucket": "opnsense-imgs",
    "S3Key": "OPNsense-26.1.2-nano-amd64.raw"
  }
}
EOF

# Start the import
aws ec2 import-snapshot \
  --description "OPNsense 26.1.2" \
  --disk-container "file:///tmp/containers.json" \
  --region us-east-1 --profile admin-sandbox
```

Save the `ImportTaskId` from the output, then monitor:

```bash
aws ec2 describe-import-snapshot-tasks \
  --import-task-ids <IMPORT_TASK_ID> \
  --region us-east-1 --profile admin-sandbox
```

Wait until `Status` shows `completed`. Note the `SnapshotId`.

### Register the AMI with ENA support

**Critical:** You must include `--ena-support` so the AMI works on Nitro instances (t3/t3a) which are required for serial console access.

```bash
aws ec2 register-image \
  --architecture x86_64 \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"DeleteOnTermination":true,"SnapshotId":"<SNAPSHOT_ID>","VolumeSize":3,"VolumeType":"gp3"}}]' \
  --description "OPNsense 26.1.2 nano with ENA support for Nitro instances" \
  --ena-support \
  --name "OPNsense-26.1.2-nano-ena" \
  --root-device-name "/dev/xvda" \
  --virtualization-type hvm \
  --region us-east-1 --profile admin-sandbox
```

**Do NOT override block device mappings in CDK/CloudFormation** — let the AMI use its native 3GB volume. Custom block device mappings break the FreeBSD boot.

### Clean up S3

```bash
aws s3 rm s3://opnsense-imgs/OPNsense-26.1.2-nano-amd64.raw \
  --region us-east-1 --profile admin-sandbox
aws s3 rb s3://opnsense-imgs --region us-east-1 --profile admin-sandbox
```

---

## The Problem

The OPNsense nano AMI (`ami-02ea554632d1563a4`) kept shutting down on EC2. Multiple failed attempts:

| Attempt | What happened |
|---------|--------------|
| t2.micro, dual ENI, custom block device | Instance self-shutdown |
| t2.small, dual ENI, custom block device | Instance self-shutdown |
| t2.medium, single ENI, custom block device | Instance self-shutdown |
| Marketplace AMI on t3a.small | Worked but has hourly software charge |
| t2.medium, single ENI, **no block device override** | Booted! But no serial console on t2 |

## Root Causes

1. **Block device mapping override killed the boot** — forcing `gp3` / custom volume size changed the device name or partition layout. Letting the AMI use its native 3GB snapshot works fine.
2. **AMI was registered without ENA** — couldn't run on Nitro (t3/t3a) instances, which are needed for serial console access.
3. **OPNsense blocks all inbound on WAN by default** — no SSH, no web GUI until configured via serial console.
4. **Dual ENI at launch caused issues** — must launch with WAN only, configure via serial console, then attach LAN ENI after.

## What Finally Worked

### 1. Re-register AMI with ENA support

Same snapshot, new AMI with `--ena-support` flag:

```bash
aws ec2 register-image \
  --architecture x86_64 \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"DeleteOnTermination":true,"SnapshotId":"snap-0ec905298aa21227c","VolumeSize":3,"VolumeType":"gp3"}}]' \
  --description "OPNsense 26.1.2 nano with ENA support for Nitro instances" \
  --ena-support \
  --name "OPNsense-26.1.2-nano-ena" \
  --root-device-name "/dev/xvda" \
  --virtualization-type hvm \
  --region us-east-1 --profile admin-sandbox
```

Result: `ami-0d259cdfc1ac41fb6`

### 2. CDK stack config

```yaml
opnsense_lab:
  opnsense_ami: "ami-0d259cdfc1ac41fb6"    # ENA-enabled nano
  opnsense_instance_type: "t3a.small"       # Nitro (serial console works)
```

- **No block device mapping** on OPNsense CfnInstance — use AMI's native 3GB volume
- **WAN ENI only** at launch — LAN ENI created but attached manually after config
- Stack split: `OpnsenseLabNetwork` (VPC, subnets, endpoints) + `OpnsenseLabCompute` (instances, ENIs, EIP)

### 3. Serial console to configure WAN

```bash
# Send SSH key
aws ec2-instance-connect send-serial-console-ssh-public-key \
  --instance-id i-037d6ae2895e348fa --serial-port 0 \
  --ssh-public-key file://$HOME/.ssh/id_ed25519.pub \
  --region us-east-1 --profile admin-sandbox

# Connect (within 60 seconds)
ssh i-037d6ae2895e348fa.port0@serial-console.ec2-instance-connect.us-east-1.aws
```

In OPNsense console:
- **Option 1** → Assign interfaces → `ena0` as WAN only (skip LAN)
- **Option 8** → Shell → edit `/conf/config.xml`:
  - Add `<nohttpreferercheck>1</nohttpreferercheck>` inside `<webgui>` section
  - Run `configctl webgui restart`

### 4. Access Web GUI and enable SSH

- Web GUI: `https://100.48.143.23:443` (root / opnsense)
- In GUI: **System → Settings → Administration → Secure Shell**
  - Enable Secure Shell ✓
  - Permit root user login ✓
  - Permit password login ✓
  - Listen Interfaces: All
  - Save

### 5. Attach LAN ENI

```bash
aws ec2 attach-network-interface \
  --instance-id i-037d6ae2895e348fa \
  --network-interface-id eni-099eb1ad5ba5c26de \
  --device-index 1 \
  --region us-east-1 --profile admin-sandbox
```

### 6. Assign LAN interface via serial console

- **Option 1** → Assign interfaces → `ena0` = WAN, `ena1` = LAN
- **Option 2** → Set LAN IP:
  - DHCP? N
  - IP: `10.10.1.120`
  - Subnet: `24`
  - Gateway: (blank)
  - IPv6 tracking? N
  - DHCP server? N
  - Change HTTPS to HTTP? N
  - New self-signed cert? N
  - Restore defaults? N

### 7. Fix SSH config via serial console shell

The GUI SSH enable didn't fully work. Fixed via config.xml edits:

```bash
# From serial console Option 8 (Shell):
sed -i '' 's/<noauto>1/<noauto>0/' /conf/config.xml

# Added via ed:
# <permitrootlogin>1</permitrootlogin>
# <passwordauth>1</passwordauth>
# after <enabled>enabled</enabled> in the <ssh> section

# Disabled firewall temporarily to allow access:
pfctl -d
configctl webgui restart
```

### 8. Verify connectivity from AlmaLinux

```bash
aws ssm start-session --target i-06373994903f58663 --region us-east-1 --profile admin-sandbox
# From Alma:
ssh root@10.10.1.120   # password: opnsense
ping 10.10.1.120        # works
```

---

### 9. Expand root volume from 3GB to 10GB

The nano AMI ships with a 3GB disk that's 95% full. Expand it without rebuilding.

**Step 1: Stop the instance**
```bash
aws ec2 stop-instances --instance-ids <INSTANCE_ID> \
  --region us-east-1 --profile admin-sandbox
aws ec2 wait instance-stopped --instance-ids <INSTANCE_ID> \
  --region us-east-1 --profile admin-sandbox
```

**Step 2: Find and resize the EBS volume**
```bash
# Get the root volume ID
aws ec2 describe-instances --instance-ids <INSTANCE_ID> \
  --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' \
  --output text --region us-east-1 --profile admin-sandbox

# Resize to 10GB
aws ec2 modify-volume --volume-id <VOLUME_ID> --size 10 \
  --region us-east-1 --profile admin-sandbox
```

**Step 3: Start the instance**
```bash
aws ec2 start-instances --instance-ids <INSTANCE_ID> \
  --region us-east-1 --profile admin-sandbox
```

**Step 4: Grow the partition and filesystem (via serial console or SSH)**
```bash
# Check disk layout — disk shows 10GB, partition still 3GB
gpart show
# Output:
# => 0 20971520 nda0 BSD (10G)
#    0  6291456    1  freebsd-ufs (3.0G)
#    6291456 14680064       - free - (7.0G)

# Resize partition 1 to fill the disk
gpart resize -i 1 nda0

# Grow the UFS filesystem
growfs /dev/ufs/OPNsense_Nano

# Verify — should now show ~9.5GB
df -h
```

### 10. Create the golden AMI

Only snapshot after **all** of the following are configured and verified with a reboot:

- [x] Root volume expanded to 10GB
- [x] SSH enabled with root login + password auth
- [x] Web GUI with referrer check disabled (`<nohttpreferercheck>1</nohttpreferercheck>`)
- [x] WAN + LAN interfaces assigned (ena0 = WAN, ena1 = LAN)
- [x] WAN: DHCP, gateway `WAN_GW` → `10.10.0.1`, block private/bogon unchecked
- [x] LAN: DHCP
- [x] Outbound NAT: hybrid mode, LAN net → WAN interface address
- [x] WAN firewall rules: allow SSH (22) + HTTPS (443) from your IP
- [x] LAN firewall rules: allow DNS (53), allow HTTPS to Allowed_Sites alias, block all else
- [x] Reboot test passes (SSH, GUI, NAT all survive)

```bash
aws ec2 create-image \
  --instance-id <INSTANCE_ID> \
  --name "OPNsense-26.1.2-golden-final-$(date +%Y%m%d)" \
  --description "OPNsense 26.1.2 golden - ENA, SSH, GUI, NAT, gateway, egress filtering, fully configured" \
  --no-reboot \
  --region us-east-1 --profile admin-sandbox \
  --query 'ImageId' --output text
```

Then update `configs/infrastructure.yaml` with the new AMI ID.

**Note:** The golden AMI still requires manual steps on fresh deploy because interface MAC addresses and ENI IPs change:
1. Attach LAN ENI (`aws ec2 attach-network-interface`)
2. Reassign interfaces via serial console (Option 1 → ena0=WAN, ena1=LAN)
3. Set WAN and LAN to DHCP via serial console (Option 2)

---

## AMIs Created

| AMI | ID | Description |
|-----|----|-------------|
| nano (original) | `ami-02ea554632d1563a4` | Raw import, no ENA, doesn't boot with custom block devices |
| nano + ENA | `ami-0d259cdfc1ac41fb6` | Re-registered with ENA flag, boots on Nitro |
| configured | `ami-09b3dd0239897277b` | SSH, GUI, 10GB disk |
| golden (final) | `ami-0c7eb0df432665ef3` | Everything + NAT, gateway, egress filtering |

| Resource | Value |
|----------|-------|
| OPNsense Instance | `i-037d6ae2895e348fa` |
| OPNsense AMI (ENA) | `ami-0d259cdfc1ac41fb6` |
| OPNsense Type | `t3a.small` |
| OPNsense EIP | `100.48.143.23` |
| OPNsense WAN IP | (DHCP from public subnet) |
| OPNsense LAN IP | `10.10.1.120` |
| LAN ENI | `eni-099eb1ad5ba5c26de` |
| AlmaLinux Instance | `i-06373994903f58663` |
| AlmaLinux IP | `10.10.1.168` |
| Web GUI | `https://100.48.143.23:443` |
| Web GUI creds | `root` / `opnsense` |

## CDK Stacks

| Stack | CloudFormation Name | Status |
|-------|---------------------|--------|
| OpnsenseLabNetworkStack | `OpnsenseLabNetwork` | CREATE_COMPLETE |
| OpnsenseLabComputeStack | `OpnsenseLabCompute` | CREATE_COMPLETE |

## TODO

- [ ] Reboot OPNsense and verify SSH + Web GUI persist
- [ ] Configure NAT rules so AlmaLinux can reach internet through OPNsense
- [ ] Lock down WAN firewall rules (currently `pfctl -d` disabled the firewall)
- [ ] Re-enable pf with proper rules allowing SSH/HTTPS on WAN
- [ ] Test SSM port forwarding to OPNsense web GUI through Alma
- [ ] Update pipeline stack for the network/compute split
- [ ] Consider baking a pre-configured AMI to skip manual serial console steps
