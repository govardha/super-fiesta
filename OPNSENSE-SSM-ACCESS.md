# Accessing OPNsense Web GUI via SSM Port Forwarding

## Overview

Instead of exposing the OPNsense management interface (443/8443) to the internet, you can use AWS Systems Manager Session Manager to port-forward through the AlmaLinux EC2 instance on the private subnet. The AlmaLinux instance acts as a jump host — SSM handles the tunnel, and your browser connects to `localhost`.

## Architecture

```
Your Laptop (localhost:8443)
  │
  │  SSM Port Forwarding Session
  ▼
AlmaLinux EC2 (private subnet, SSM agent)
  │
  │  TCP → OPNsense LAN IP:443
  ▼
OPNsense LAN ENI (private subnet)
```

No internet-facing ports required on OPNsense for management access.

## Prerequisites

- AWS CLI v2 with the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) installed
- AlmaLinux instance running and SSM-connected
- OPNsense instance running with LAN interface configured
- AWS profile with access to the sandbox account

## Step 1: Get Instance IDs and IPs

```bash
# Get AlmaLinux instance ID from stack outputs
aws cloudformation describe-stacks \
  --stack-name SandboxDeploy-OpnsenseLabStack \
  --query 'Stacks[0].Outputs[?OutputKey==`AlmaInstanceId`].OutputValue' \
  --output text \
  --profile admin-sandbox \
  --region us-east-1

# Get OPNsense LAN ENI private IP
# (This is the IP assigned to the LAN ENI in the private subnet)
aws ec2 describe-network-interfaces \
  --filters "Name=description,Values=OPNsense LAN interface" \
  --query 'NetworkInterfaces[0].PrivateIpAddress' \
  --output text \
  --profile admin-sandbox \
  --region us-east-1
```

## Step 2: Start the Port Forwarding Session

```bash
aws ssm start-session \
  --target <alma-instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<opnsense-lan-private-ip>"],"portNumber":["443"],"localPortNumber":["8443"]}' \
  --profile admin-sandbox \
  --region us-east-1
```

You should see:

```
Starting session with SessionId: ...
Port 8443 opened for sessionId ...
Waiting for connections...
```

Leave this terminal open.

## Step 3: Access the Web GUI

Open your browser and navigate to:

```
https://localhost:8443
```

You'll get a certificate warning (self-signed) — accept it and proceed.

Default credentials:
- **Username:** root
- **Password:** opnsense

## One-Liner (with variable substitution)

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
  --profile admin-sandbox \
  --region us-east-1
```

## SSH Access via SSM (Alternative)

You can also forward SSH the same way:

```bash
aws ssm start-session \
  --target <alma-instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<opnsense-lan-private-ip>"],"portNumber":["22"],"localPortNumber":["2222"]}' \
  --profile admin-sandbox \
  --region us-east-1
```

Then in another terminal:

```bash
ssh root@localhost -p 2222
```

## Security Implications

With this approach you can tighten the WAN security group to remove inbound 443/8443/22 entirely. The only thing the WAN ENI needs is:

- **Outbound**: all (for OPNsense to NAT private subnet traffic to the internet)
- **Inbound**: nothing for management — SSM handles it through the private side

This keeps the OPNsense management plane completely off the internet.

## Troubleshooting

**"Session Manager plugin not found"**
```bash
# macOS
brew install --cask session-manager-plugin

# Linux
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o session-manager-plugin.deb
sudo dpkg -i session-manager-plugin.deb
```

**"Target is not connected"**
- Verify AlmaLinux SSM agent is running: check the instance in Systems Manager → Fleet Manager
- SSM VPC endpoints must be healthy (the stack creates these)

**Port forwarding connects but Web GUI doesn't load**
- OPNsense LAN interface may not be configured yet — complete the serial console setup first
- Verify the LAN IP matches what you're forwarding to: `aws ec2 describe-network-interfaces --filters "Name=description,Values=OPNsense LAN interface"`
- From the AlmaLinux instance, test connectivity: `curl -k https://<opnsense-lan-ip>:443`
