# OPNsense ENA/NVMe AMI Build Runbook

**Date:** 2026-04-24  
**Goal:** Build a Nitro-compatible OPNsense AMI from the nano image (ENA + NVMe + serial console)  
**Source AMI:** `ami-02ea554632d1563a4` (OPNsense 26.1.2-nano, no ENA)  
**Profile:** `admin-sandbox`  
**Region:** `us-east-1`

---

## Infrastructure (from OpnsenseLabNetwork stack)

| Resource | ID |
|----------|----|
| VPC | `vpc-0aed82d4a854afc3b` |
| Public Subnet | `subnet-011c4fc6aa071c980` |
| WAN Security Group | `sg-022adeb63ef2cbb98` |
| Key Pair | `opnsense-lab-key` |

---

## Step 1: Launch builder instance on t2.medium

```bash
aws ec2 run-instances \
  --image-id ami-02ea554632d1563a4 \
  --instance-type t2.medium \
  --key-name opnsense-lab-key \
  --security-group-ids sg-022adeb63ef2cbb98 \
  --subnet-id subnet-011c4fc6aa071c980 \
  --associate-public-ip-address \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":10,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=opnsense-ami-builder}]' \
  --region us-east-1 \
  --profile admin-sandbox \
  --query 'Instances[0].InstanceId' \
  --output text
```

Save the instance ID:
```bash
export BUILDER_ID=<instance-id-from-above>
```

## Step 2: Wait for it to be running and get the public IP

```bash
aws ec2 wait instance-running \
  --instance-ids $BUILDER_ID \
  --region us-east-1 \
  --profile admin-sandbox

aws ec2 describe-instances \
  --instance-ids $BUILDER_ID \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text \
  --region us-east-1 \
  --profile admin-sandbox
```

Save the IP:
```bash
export BUILDER_IP=<public-ip-from-above>
```

## Step 3: Verify instance is not self-shutting (wait ~60 seconds)

```bash
sleep 60

aws ec2 describe-instances \
  --instance-ids $BUILDER_ID \
  --query 'Reservations[0].Instances[0].State.Name' \
  --output text \
  --region us-east-1 \
  --profile admin-sandbox
```

If it says `stopped` — the nano image won't work on t2.medium either and this approach is dead.  
If it says `running` — proceed to Step 4.

## Step 4: SSH into OPNsense

```bash
ssh root@$BUILDER_IP
```

Password: `opnsense`

If SSH hangs, the WAN SG allows port 22 so it's likely OPNsense hasn't finished booting. Wait another 30 seconds and retry.

## Step 5: Check and load ENA driver (GO/NO-GO gate)

```bash
# Check if ENA module exists
kldload if_ena 2>/dev/null && echo "SUCCESS: ENA loaded" || echo "FAIL: ENA not available"
```

**If FAIL** — this OPNsense version doesn't ship with ENA. Stop here, use the marketplace AMI instead.  
**If SUCCESS** — continue.

## Step 6: Load NVMe drivers

```bash
kldload nvme 2>/dev/null && echo "NVMe loaded" || echo "NVMe not available"
kldload nvd 2>/dev/null && echo "NVD loaded" || echo "NVD not available"
```

## Step 7: Make all drivers persistent in loader.conf

```bash
cat >> /boot/loader.conf << 'EOF'
if_ena_load="YES"
nvme_load="YES"
nvd_load="YES"
console="comconsole,vidconsole"
comconsole_speed="115200"
EOF
```

Verify:
```bash
cat /boot/loader.conf
```

## Step 8: Fix fstab for NVMe compatibility

Check current mounts and fstab:
```bash
mount | grep " / "
cat /etc/fstab
glabel status
gpart show
```

### Option A: Create a UFS label (most reliable)

```bash
# Find root device from mount output (likely /dev/ada0s1a or /dev/ada0p2)
ROOT_DEV=$(mount | grep " / " | awk '{print $1}')
echo "Root device: $ROOT_DEV"

# Set a UFS label
tunefs -L rootfs $ROOT_DEV

# Verify label was created
glabel status
```

### Option B: Check for existing GPT labels

```bash
gpart show -l
```

### Update fstab

```bash
# Backup first
cp /etc/fstab /etc/fstab.bak

# Edit fstab — replace device path with label
vi /etc/fstab
```

Change from:
```
/dev/ada0s1a   /   ufs   rw   1   1
```

To (if you used UFS label):
```
/dev/ufs/rootfs   /   ufs   rw   1   1
```

Or (if GPT label exists):
```
/dev/gpt/rootfs   /   ufs   rw   1   1
```

Verify:
```bash
cat /etc/fstab
```

## Step 9: Clean shutdown

```bash
shutdown -p now
```

## Step 10: Wait for instance to stop

```bash
aws ec2 wait instance-stopped \
  --instance-ids $BUILDER_ID \
  --region us-east-1 \
  --profile admin-sandbox

echo "Instance stopped"
```

## Step 11: Enable ENA attribute on the instance

```bash
aws ec2 modify-instance-attribute \
  --instance-id $BUILDER_ID \
  --ena-support \
  --region us-east-1 \
  --profile admin-sandbox

echo "ENA flag set"
```

## Step 12: Create the AMI

```bash
aws ec2 create-image \
  --instance-id $BUILDER_ID \
  --name "OPNsense-26.1.2-ena-nvme-$(date +%Y%m%d)" \
  --description "OPNsense 26.1.2 with ENA+NVMe+serial for Nitro instances" \
  --region us-east-1 \
  --profile admin-sandbox \
  --query 'ImageId' \
  --output text
```

Save the AMI ID:
```bash
export NEW_AMI=<ami-id-from-above>
```

## Step 13: Wait for AMI to be available

```bash
aws ec2 wait image-available \
  --image-ids $NEW_AMI \
  --region us-east-1 \
  --profile admin-sandbox

echo "AMI ready"
```

## Step 14: Verify AMI has ENA

```bash
aws ec2 describe-images \
  --image-ids $NEW_AMI \
  --query 'Images[0].{Name:Name,ENA:EnaSupport,Arch:Architecture}' \
  --output table \
  --region us-east-1 \
  --profile admin-sandbox
```

ENA should show `True`.

## Step 15: Terminate the builder

```bash
aws ec2 terminate-instances \
  --instance-ids $BUILDER_ID \
  --region us-east-1 \
  --profile admin-sandbox
```

## Step 16: Update CDK config and deploy

Edit `configs/infrastructure.yaml`:
```yaml
opnsense_lab:
  opnsense_ami: "<NEW_AMI>"
  opnsense_instance_type: "t3a.small"
```

Deploy:
```bash
cdk deploy OpnsenseLabCompute --profile admin-sandbox
```

---

## Rollback

If the new AMI doesn't work on Nitro, fall back to the marketplace AMI:
```yaml
opnsense_ami: "ami-08d4b55a42468ecfa"
opnsense_instance_type: "t3a.small"
```
