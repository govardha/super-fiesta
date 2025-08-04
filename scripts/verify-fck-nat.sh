#!/bin/bash

# Function to get IMDSv2 token
get_imds_token() {
    TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null)
    echo "$TOKEN"
}

# Function to get metadata using IMDSv2
get_imds_metadata() {
    local PATH="$1"
    local TOKEN=$(get_imds_token)
    if [ -z "$TOKEN" ]; then
        echo "Failed to get IMDSv2 token. Is IMDSv2 enabled?"
        return 1
    fi
    curl -s -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/$PATH"
}

echo '=== fck-nat Network Verification ==='
echo

echo '1. Current IP and routing:'
# Use the function to get the private IP
PRIVATE_IP=$(get_imds_metadata "local-ipv4")
if [ -z "$PRIVATE_IP" ]; then
    echo 'Private IP: Failed to retrieve (IMDSv2 likely required and failed)'
else
    echo "Private IP: $PRIVATE_IP"
fi

echo 'Public IP (through NAT):' $(curl -s http://checkip.amazonaws.com/ || echo 'Failed to get public IP')
echo

echo '2. Route table:'
ip route show
echo

echo '3. DNS resolution:'
nslookup google.com
echo

echo '4. Internet connectivity test:'
curl -s -o /dev/null -w 'HTTP Status: %{http_code}\n' http://google.com
echo

echo '5. Package manager test (apt):'
apt list --upgradable 2>/dev/null | head -5
echo

echo '6. Docker registry test:'
# Ensure docker is installed and service is running for this test to be meaningful
if command -v docker &> /dev/null; then
    timeout 10 docker pull hello-world:latest >/dev/null 2>&1 && echo 'Docker registry: OK' || echo 'Docker registry: Failed'
else
    echo 'Docker registry: Docker command not found. Skipping test.'
fi
echo

echo 'If all tests pass, fck-nat routing is working correctly!'
