#!/bin/bash
# DDEV Multi-Site Setup Script for Amazon Linux 2
# Copy this script to your EC2 instance and run with: sudo bash ddev-setup.sh

set -e

echo "🚀 Starting DDEV Multi-Site Setup..."
echo "This will install Docker, DDEV, and create initial sites qa1 and qa2"
echo ""

# Update system
echo "📦 Updating system packages..."
yum update -y
yum install -y docker git at curl

# Start and enable Docker
echo "🐳 Setting up Docker..."
systemctl start docker
systemctl enable docker
usermod -a -G docker ec2-user

# Install Docker Compose
echo "📋 Installing Docker Compose..."
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose

# Install DDEV
echo "⚡ Installing DDEV..."
curl -fsSL https://raw.githubusercontent.com/ddev/ddev/master/scripts/install_ddev.sh | bash

# Create DDEV scripts directory
mkdir -p /opt/ddev-scripts

# Create site creation script
echo "📝 Creating site management scripts..."
cat > /opt/ddev-scripts/create-site.sh << 'EOF'
#!/bin/bash
SITE_NAME=$1
SITE_PORT=$2

if [ -z "$SITE_NAME" ] || [ -z "$SITE_PORT" ]; then
    echo "Usage: create-site.sh <site-name> <port>"
    echo "Example: create-site.sh qa3 8003"
    exit 1
fi

echo "🏗️  Creating DDEV site: $SITE_NAME on port $SITE_PORT"

# Create site directory
mkdir -p /home/ec2-user/sites/$SITE_NAME/web
chown -R ec2-user:ec2-user /home/ec2-user/sites/$SITE_NAME

# Create DDEV config
sudo -u ec2-user bash -c "cd /home/ec2-user/sites/$SITE_NAME && ddev config --project-type=php --php-version=8.1 --docroot=web --project-name=$SITE_NAME"

# Update config for ALB
cat > /home/ec2-user/sites/$SITE_NAME/.ddev/config.yaml << EOL
name: $SITE_NAME
type: php
docroot: web
php_version: "8.1"
webserver_type: nginx-fpm
router_http_port: "$SITE_PORT"
router_https_port: "$((SITE_PORT + 1000))"
additional_hostnames:
  - $SITE_NAME.vadai.org
additional_fqdns:
  - $SITE_NAME.vadai.org
bind_all_interfaces: true
host_webserver_port: "$SITE_PORT"
EOL

# Create sample content
cat > /home/ec2-user/sites/$SITE_NAME/web/index.html << EOL
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>$SITE_NAME - DDEV Demo</title>
    <style>
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            max-width: 900px; 
            margin: 0 auto; 
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: rgba(255,255,255,0.1);
            padding: 40px;
            border-radius: 20px;
            backdrop-filter: blur(15px);
            border: 1px solid rgba(255,255,255,0.2);
            text-align: center;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
        }
        h1 { 
            color: #fff; 
            margin-bottom: 30px; 
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .info { 
            background: rgba(255,255,255,0.15); 
            padding: 15px; 
            border-radius: 10px; 
            margin: 15px 0; 
            border-left: 4px solid #00ff88;
        }
        .status { color: #00ff88; font-weight: bold; }
        .links { margin-top: 30px; }
        .link { 
            display: inline-block; 
            margin: 10px; 
            padding: 12px 24px; 
            background: rgba(255,255,255,0.2); 
            border-radius: 25px; 
            text-decoration: none; 
            color: white; 
            transition: all 0.3s ease;
        }
        .link:hover { 
            background: rgba(255,255,255,0.3); 
            transform: translateY(-2px);
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 $SITE_NAME</h1>
        <div class="info">
            <strong>🌐 Site:</strong> $SITE_NAME.vadai.org
        </div>
        <div class="info">
            <strong>📅 Created:</strong> $(date)
        </div>
        <div class="info">
            <strong>🖥️  Server:</strong> $(hostname)
        </div>
        <div class="info">
            <strong>🔌 Port:</strong> $SITE_PORT
        </div>
        <div class="info">
            <strong class="status">Status:</strong> <span class="status">🟢 Active</span>
        </div>
        <p style="margin: 30px 0; font-size: 1.1em;">
            This is a dynamically created DDEV site running on AWS with fck-nat! 🎉
        </p>
        <div class="links">
            <a href="/info.php" class="link">📊 PHP Info</a>
            <a href="/health" class="link">❤️ Health Check</a>
        </div>
    </div>
</body>
</html>
EOL

# Create health check endpoint
echo "OK" > /home/ec2-user/sites/$SITE_NAME/web/health

# Create PHP info page
cat > /home/ec2-user/sites/$SITE_NAME/web/info.php << EOL
<?php
echo "<div style='font-family: Arial; max-width: 800px; margin: 20px auto; padding: 20px; background: #f5f5f5; border-radius: 10px;'>";
echo "<h1 style='color: #333; text-align: center;'>🐘 PHP Info for $SITE_NAME</h1>";
echo "<div style='background: white; padding: 20px; border-radius: 8px; margin: 20px 0;'>";
echo "<h3>Server Information</h3>";
echo "<p><strong>Site:</strong> $SITE_NAME.vadai.org</p>";
echo "<p><strong>Server:</strong> " . gethostname() . "</p>";
echo "<p><strong>PHP Version:</strong> " . phpversion() . "</p>";
echo "<p><strong>Current Time:</strong> " . date('Y-m-d H:i:s T') . "</p>";
echo "<p><strong>Server IP:</strong> " . \$_SERVER['SERVER_ADDR'] . "</p>";
echo "<p><strong>Client IP:</strong> " . \$_SERVER['REMOTE_ADDR'] . "</p>";
echo "</div>";
echo "</div>";
echo "<hr style='margin: 30px 0;'>";
phpinfo();
?>
EOL

# Fix permissions
chown -R ec2-user:ec2-user /home/ec2-user/sites/$SITE_NAME

# Start the site
echo "🔄 Starting DDEV site..."
sudo -u ec2-user bash -c "cd /home/ec2-user/sites/$SITE_NAME && ddev start"

if [ $? -eq 0 ]; then
    echo "✅ Site $SITE_NAME created and started successfully on port $SITE_PORT"
    echo "🌐 Will be available at: https://$SITE_NAME.vadai.org"
    echo "📊 PHP Info: https://$SITE_NAME.vadai.org/info.php"
    echo "❤️  Health: https://$SITE_NAME.vadai.org/health"
else
    echo "❌ Failed to start site $SITE_NAME"
    exit 1
fi
EOF

chmod +x /opt/ddev-scripts/create-site.sh

# Create bulk site creation script
cat > /opt/ddev-scripts/create-qa-sites.sh << 'EOF'
#!/bin/bash
# Create QA sites qa3 through qa6

echo "🏗️  Creating QA sites qa3-qa6..."

for i in {3..6}; do
    echo ""
    echo "Creating qa$i..."
    /opt/ddev-scripts/create-site.sh qa$i 800$i
    if [ $? -ne 0 ]; then
        echo "❌ Failed to create qa$i, stopping..."
        exit 1
    fi
    sleep 5  # Brief pause between site creations
done

echo ""
echo "✅ All QA sites created successfully!"
echo "🌐 Your sites:"
for i in {3..6}; do
    echo "   • https://qa$i.vadai.org"
done
EOF

chmod +x /opt/ddev-scripts/create-qa-sites.sh

# Create site management helper script
cat > /opt/ddev-scripts/manage-sites.sh << 'EOF'
#!/bin/bash
# DDEV Site Management Helper

case "$1" in
    "list")
        echo "📋 DDEV Sites Status:"
        sudo -u ec2-user ddev list
        ;;
    "stop-all")
        echo "🛑 Stopping all DDEV sites..."
        sudo -u ec2-user bash -c "cd /home/ec2-user/sites && for site in */; do cd \$site && ddev stop; cd ..; done"
        ;;
    "start-all")
        echo "▶️  Starting all DDEV sites..."
        sudo -u ec2-user bash -c "cd /home/ec2-user/sites && for site in */; do cd \$site && ddev start; cd ..; done"
        ;;
    "restart-all")
        echo "🔄 Restarting all DDEV sites..."
        sudo -u ec2-user bash -c "cd /home/ec2-user/sites && for site in */; do cd \$site && ddev restart; cd ..; done"
        ;;
    "logs")
        if [ -z "$2" ]; then
            echo "Usage: manage-sites.sh logs <site-name>"
            echo "Example: manage-sites.sh logs qa1"
        else
            sudo -u ec2-user bash -c "cd /home/ec2-user/sites/$2 && ddev logs"
        fi
        ;;
    "delete")
        if [ -z "$2" ]; then
            echo "Usage: manage-sites.sh delete <site-name>"
            echo "Example: manage-sites.sh delete qa3"
        else
            echo "🗑️  Deleting site $2..."
            sudo -u ec2-user bash -c "cd /home/ec2-user/sites/$2 && ddev delete -y"
            rm -rf /home/ec2-user/sites/$2
            echo "✅ Site $2 deleted"
        fi
        ;;
    *)
        echo "🔧 DDEV Site Management"
        echo ""
        echo "Usage: manage-sites.sh <command> [options]"
        echo ""
        echo "Commands:"
        echo "  list                List all DDEV sites"
        echo "  start-all          Start all sites"
        echo "  stop-all           Stop all sites"
        echo "  restart-all        Restart all sites"
        echo "  logs <site>        Show logs for specific site"
        echo "  delete <site>      Delete a site completely"
        echo ""
        echo "Examples:"
        echo "  manage-sites.sh list"
        echo "  manage-sites.sh logs qa1"
        echo "  manage-sites.sh delete qa6"
        ;;
esac
EOF

chmod +x /opt/ddev-scripts/manage-sites.sh

# Start atd service for delayed execution
systemctl start atd
systemctl enable atd

# Create initial sites setup
echo "⏳ Waiting for Docker to fully initialize..."
sleep 30

echo "📦 Creating sites directory..."
mkdir -p /home/ec2-user/sites
chown ec2-user:ec2-user /home/ec2-user/sites

echo "🏗️  Creating initial sites qa1 and qa2..."
/opt/ddev-scripts/create-site.sh qa1 8001
sleep 10
/opt/ddev-scripts/create-site.sh qa2 8002

echo ""
echo "🎉 DDEV Setup Complete!"
echo ""
echo "✅ Initial sites created:"
echo "   • https://qa1.vadai.org"
echo "   • https://qa2.vadai.org"
echo ""
echo "🔧 Management commands:"
echo "   • Create qa3-qa6: sudo /opt/ddev-scripts/create-qa-sites.sh"
echo "   • Create custom:   sudo /opt/ddev-scripts/create-site.sh qa7 8007"
echo "   • Manage sites:    sudo /opt/ddev-scripts/manage-sites.sh list"
echo ""
echo "📊 Check status:"
echo "   sudo -u ec2-user ddev list"
echo ""
echo "🔗 Connect to sites locally:"
echo "   curl -H 'Host: qa1.vadai.org' http://localhost:8001"
echo "   curl -H 'Host: qa2.vadai.org' http://localhost:8002"
echo ""
echo "Note: Sites will be accessible via ALB once DNS and target groups are configured!"