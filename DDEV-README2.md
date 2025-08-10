# DDEV Multi-Site Setup README

This guide provides complete instructions for setting up DDEV test sites on Ubuntu 24 with database-less containers and custom domain routing through an AWS ALB.

## Prerequisites

- Ubuntu 24 EC2 instance
- User: `ubuntu` with sudo access
- ALB configured to forward traffic to EC2 port 80

## Step 1: Install Docker

```bash
# Update package index
sudo apt-get update

# Install prerequisites
sudo apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Add Docker's official GPG key
sudo mkdir -m 0755 -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Set up the repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add ubuntu user to docker group
sudo usermod -aG docker ubuntu

# Apply group changes (or logout/login)
newgrp docker

# Verify Docker installation
docker --version
docker compose version
```

## Step 2: Install Required Tools

```bash
# Install curl and ss (netstat)
sudo apt-get install -y curl iproute2 net-tools

# Verify installations
curl --version
ss --version
```

## Step 3: Install DDEV

```bash
# Download DDEV installer script
curl -fsSL https://ddev.github.io/ddev/install.sh -o install_ddev.sh

# Make it executable
chmod +x install_ddev.sh

# Install DDEV
./install_ddev.sh

# Clean up
rm install_ddev.sh

# Verify DDEV installation
ddev --version
```

## Step 4: Install DDEV Utilities

```bash
# Detect architecture and install ddev-hostname
ARCH=$(uname -m)
if [[ "$ARCH" == "x86_64" ]]; then
    ARCH_SUFFIX="amd64"
elif [[ "$ARCH" == "aarch64" ]]; then
    ARCH_SUFFIX="arm64"
fi

# Install ddev-hostname
sudo wget -O /usr/local/bin/ddev-hostname \
    "https://github.com/ddev/ddev/releases/latest/download/ddev-hostname_linux-${ARCH_SUFFIX}"
sudo chmod +x /usr/local/bin/ddev-hostname

# Install mkcert
sudo wget -O /usr/local/bin/mkcert \
    "https://github.com/FiloSottile/mkcert/releases/latest/download/mkcert-v*-linux-${ARCH_SUFFIX}"
sudo chmod +x /usr/local/bin/mkcert

# Initialize mkcert
mkcert -install

# Verify installations
ddev-hostname --version
mkcert -help | head -1
```

## Step 5: Configure DDEV Global Settings

```bash
# Create DDEV directory
mkdir -p ~/.ddev

# Create global configuration
cat > ~/.ddev/global_config.yaml << 'EOF'
fail_on_hook_fail: false
instrumentation_opt_in: false
internet_detection_timeout_ms: 3000
letsencrypt_email: ""
mkcert_caroot: /home/ubuntu/.local/share/mkcert
no_bind_mounts: false
omit_containers: []
performance_mode: none
project_tld: ddev.site
router_bind_all_interfaces: true
router_http_port: "80"
router_https_port: "443"
simple_formatting: false
table_style: default
traefik_monitor_port: "9999"
use_hardened_images: false
use_letsencrypt: false
web_environment: []
xdebug_ide_location: ""
EOF

# Disable telemetry
ddev config global --instrumentation-opt-in=false
```

## Step 6: Create Site Structure

```bash
# Create sites directory
mkdir -p ~/sites/{qa1,qa2,user1}

# Create sample content for each site
echo '<?php echo "<h1>QA1 Site</h1><p>Running on " . $_SERVER["HTTP_HOST"] . "</p>"; ?>' > ~/sites/qa1/index.php
echo '<?php echo "<h1>QA2 Site</h1><p>Running on " . $_SERVER["HTTP_HOST"] . "</p>"; ?>' > ~/sites/qa2/index.php
echo '<?php echo "<h1>User1 Site</h1><p>Running on " . $_SERVER["HTTP_HOST"] . "</p>"; ?>' > ~/sites/user1/index.php
```

## Step 7: Configure Each DDEV Site

### Configure QA1 Site

```bash
cd ~/sites/qa1

# Create DDEV configuration
mkdir -p .ddev
cat > .ddev/config.yaml << 'EOF'
name: qa1
type: php
docroot: ""
php_version: "8.2"
webserver_type: nginx-fpm
additional_fqdns:
  - qa1.webdev.vadai.org
omit_containers: [db]
EOF

# Create docker-compose override to remove DB dependencies
cat > .ddev/docker-compose.override.yaml << 'EOF'
services:
  web:
    depends_on: []
    links: []
    environment:
      - IS_DDEV_PROJECT=true
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost"]
      interval: 30s
      timeout: 10s
      retries: 3
EOF
```

### Configure QA2 Site

```bash
cd ~/sites/qa2

# Create DDEV configuration
mkdir -p .ddev
cat > .ddev/config.yaml << 'EOF'
name: qa2
type: php
docroot: ""
php_version: "8.2"
webserver_type: nginx-fpm
additional_fqdns:
  - qa2.webdev.vadai.org
omit_containers: [db]
EOF

# Copy docker-compose override from qa1
cp ~/sites/qa1/.ddev/docker-compose.override.yaml .ddev/
```

### Configure User1 Site

```bash
cd ~/sites/user1

# Create DDEV configuration
mkdir -p .ddev
cat > .ddev/config.yaml << 'EOF'
name: user1
type: php
docroot: ""
php_version: "8.2"
webserver_type: nginx-fpm
additional_fqdns:
  - user1.webdev.vadai.org
omit_containers: [db]
EOF

# Copy docker-compose override from qa1
cp ~/sites/qa1/.ddev/docker-compose.override.yaml .ddev/
```

## Step 8: Start All Sites

```bash
# Start each site (this also starts the DDEV router)
cd ~/sites/qa1 && ddev start
cd ~/sites/qa2 && ddev start
cd ~/sites/user1 && ddev start

# Verify all sites are running
ddev list
```

## Step 9: Verify Setup

```bash
# Check that DDEV router is listening on port 80
sudo netstat -tlnp | grep :80

# Test each site locally using host headers
curl -H "Host: qa1.webdev.vadai.org" http://localhost
curl -H "Host: qa2.webdev.vadai.org" http://localhost
curl -H "Host: user1.webdev.vadai.org" http://localhost

# Check Docker containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

## Management Commands

### Stop all sites
```bash
ddev poweroff
```

### Start individual site
```bash
cd ~/sites/qa1 && ddev start
```

### Restart a site
```bash
cd ~/sites/qa1 && ddev restart
```

### View logs
```bash
cd ~/sites/qa1 && ddev logs
```

### Check router configuration
```bash
docker exec ddev-router cat /etc/traefik/conf.d/*
```

## Troubleshooting

### Port 80 already in use
```bash
# Find what's using port 80
sudo lsof -i :80

# Stop the service or change DDEV router port
```

### Permission issues
```bash
# Ensure ubuntu user is in docker group
groups ubuntu

# Re-add if needed
sudo usermod -aG docker ubuntu
newgrp docker
```

### DDEV router not accessible
```bash
# Check if router is running
docker ps | grep ddev-router

# Check router logs
docker logs ddev-router

# Restart everything
ddev poweroff
cd ~/sites/qa1 && ddev start
```

## Notes

- The database container may still be created but is not used
- TLS termination is handled by the ALB
- Each site runs on the DDEV router (Traefik) listening on port 80
- Domains (qa1.webdev.vadai.org, etc.) are resolved by ALB, not locally
