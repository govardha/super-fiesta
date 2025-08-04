#!/bin/bash
# Create DDEV Site Script
# Usage: ./create-site.sh qa2
# Creates a new DDEV site with dynamic content

set -e

SITE_NAME="${1:-qa2}"

if [ -z "$SITE_NAME" ]; then
    echo "Usage: $0 <site-name>"
    echo "Example: $0 qa2"
    echo "Example: $0 staging"
    exit 1
fi

echo "🚀 Creating DDEV site: $SITE_NAME.webdev.vadai.org"

# Ensure we're running as the correct user
if [ "$EUID" -eq 0 ]; then
    echo "❌ Don't run this as root. Run as ubuntu user."
    exit 1
fi

# Check if site already exists
if [ -d "/home/ubuntu/sites/$SITE_NAME" ]; then
    echo "📁 Site $SITE_NAME already exists. Regenerating with new colors..."
    cd "/home/ubuntu/sites/$SITE_NAME"
    
    # Stop the existing site
    ddev stop 2>/dev/null || true
else
    # Create site directory
    echo "📁 Creating $SITE_NAME site directory..."
    mkdir -p "/home/ubuntu/sites/$SITE_NAME"
    cd "/home/ubuntu/sites/$SITE_NAME"

    # Initialize DDEV project
    echo "⚙️  Initializing DDEV project..."
    ddev config --project-name="$SITE_NAME" --project-type=php --docroot="" --php-version=8.2

    # Create DDEV configuration
    echo "📝 Creating DDEV configuration..."
    cat > .ddev/config.yaml << EOF
name: $SITE_NAME
type: php
docroot: ""
php_version: "8.2"
webserver_type: nginx-fpm
additional_fqdns:
  - $SITE_NAME.webdev.vadai.org
omit_containers: [db]
EOF
fi

# Generate random colors for this site
COLOR1=$(printf "#%06x" $((RANDOM % 16777216)))
COLOR2=$(printf "#%06x" $((RANDOM % 16777216)))

echo "🎨 Generated color scheme: $COLOR1 → $COLOR2"

# Create dynamic web content
echo "🌐 Creating dynamic web content..."
cat > index.html << EOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>$SITE_NAME - DDEV Site</title>
    <style>
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            max-width: 1000px; 
            margin: 0 auto; 
            padding: 20px;
            background: linear-gradient(135deg, $COLOR1 0%, $COLOR2 100%);
            color: white;
            min-height: 100vh;
        }
        .container {
            background: rgba(255,255,255,0.1);
            padding: 40px;
            border-radius: 20px;
            backdrop-filter: blur(15px);
            border: 1px solid rgba(255,255,255,0.2);
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
        }
        h1 { 
            color: #fff; 
            margin-bottom: 30px; 
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            text-align: center;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }
        .card { 
            background: rgba(255,255,255,0.15); 
            padding: 20px; 
            border-radius: 15px; 
            border-left: 4px solid #00ff88;
            backdrop-filter: blur(10px);
        }
        .card h3 {
            margin-top: 0;
            color: #00ff88;
            font-size: 1.2em;
        }
        .status { 
            color: #00ff88; 
            font-weight: bold; 
            font-size: 1.1em;
        }
        .links { 
            text-align: center;
            margin-top: 40px; 
        }
        .link { 
            display: inline-block; 
            margin: 10px; 
            padding: 12px 24px; 
            background: rgba(255,255,255,0.2); 
            border-radius: 25px; 
            text-decoration: none; 
            color: white; 
            transition: all 0.3s ease;
            border: 1px solid rgba(255,255,255,0.3);
        }
        .link:hover { 
            background: rgba(255,255,255,0.3); 
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        .timestamp {
            text-align: center;
            margin-top: 30px;
            font-size: 0.9em;
            opacity: 0.8;
        }
        #dynamic-info {
            min-height: 60px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 ${SITE_NAME^^}</h1>
        
        <div class="grid">
            <div class="card">
                <h3>🌐 Site Information</h3>
                <p><strong>Hostname:</strong> $SITE_NAME.webdev.vadai.org</p>
                <p><strong>Environment:</strong> Development</p>
                <p><strong>Status:</strong> <span class="status">🟢 Active</span></p>
                <div class="card">
                <h3>📅 Deployment Info</h3>
                <p><strong>Created:</strong> <span id="timestamp"></span></p>
                <p><strong>Site:</strong> $SITE_NAME</p>
                <p><strong>Type:</strong> PHP/DDEV</p>
            </div>
        </div>
            
            <div class="card">
                <h3>📡 Infrastructure</h3>
                <p><strong>Router:</strong> DDEV Traefik</p>
                <p><strong>TLS:</strong> ALB Termination</p>
                <p><strong>Pattern:</strong> *.webdev.vadai.org</p>
            </div>
            
            <div class="card" id="dynamic-info">
                <h3>🖥️ Server Details</h3>
                <p><strong>Server:</strong> <span id="hostname">Loading...</span></p>
                <p><strong>Instance:</strong> <span id="instance-id">Loading...</span></p>
                <p><strong>PHP Version:</strong> <span id="php-version">Loading...</span></p>
            </div>
            
            <div class="card">
                <h3>🎨 Site Theme</h3>
                <p><strong>Color 1:</strong> $COLOR1</p>
                <p><strong>Color 2:</strong> $COLOR2</p>
                <p><strong>Theme:</strong> Randomly Generated</p>
            </div>
        </div>
        
        <div class="links">
            <a href="/info.php" class="link">📊 PHP Info</a>
            <a href="/health.php" class="link">❤️ Health Check</a>
            <a href="/server.php" class="link">🖥️ Server Info</a>
            <a href="/headers.php" class="link">📋 Headers</a>
        </div>
        
        <div class="timestamp">
            This page was generated dynamically for $SITE_NAME.webdev.vadai.org
        </div>
    </div>
    
    <script>
        // Set timestamp
        document.getElementById('timestamp').textContent = new Date().toLocaleString();
        
        // Load dynamic server information
        async function loadServerInfo() {
            try {
                const response = await fetch('/server.php');
                const data = await response.json();
                
                document.getElementById('hostname').textContent = data.hostname || 'Unknown';
                document.getElementById('instance-id').textContent = data.instance_id || 'Unknown';
                document.getElementById('php-version').textContent = data.php_version || 'Unknown';
            } catch (error) {
                console.error('Error loading server info:', error);
                document.getElementById('hostname').textContent = 'Error loading';
                document.getElementById('instance-id').textContent = 'Error loading';
                document.getElementById('php-version').textContent = 'Error loading';
            }
        }
        
        // Load server info when page loads
        loadServerInfo();
    </script>
</body>
</html>
EOF

# Create health check endpoint
echo "❤️ Creating health check..."
cat > health.php << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Health Check</title>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f0f8ff; }
        .health { color: #28a745; font-size: 2em; }
    </style>
</head>
<body>
    <div class="health">✅ OK</div>
    <h2>Site Health Check</h2>
    <p>Site is healthy and responding</p>
    <p><strong>Timestamp:</strong> <?php date_default_timezone_set('America/New_York'); echo date('Y-m-d H:i:s T'); ?></p>
    <p><strong>Site:</strong> <?php echo $_SERVER['HTTP_HOST'] ?? 'localhost'; ?></p>
</body>
</html>
EOF

# Create PHP info page
echo "📊 Creating PHP info page..."
cat > info.php << EOF
<?php
echo "<div style='font-family: Arial; max-width: 900px; margin: 20px auto; padding: 30px; background: #f8f9fa; border-radius: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);'>";
echo "<h1 style='color: #333; text-align: center; margin-bottom: 30px;'>🐘 PHP Info for ${SITE_NAME^^}</h1>";

echo "<div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0;'>";

echo "<div style='background: white; padding: 20px; border-radius: 10px; border-left: 4px solid #007bff;'>";
echo "<h3 style='color: #007bff; margin-top: 0;'>Site Information</h3>";
echo "<p><strong>Site:</strong> $SITE_NAME.webdev.vadai.org</p>";
echo "<p><strong>Server:</strong> " . gethostname() . "</p>";
echo "<p><strong>Instance ID:</strong> " . (file_get_contents('http://169.254.169.254/latest/meta-data/instance-id') ?: 'Unknown') . "</p>";
date_default_timezone_set('America/New_York');
echo "</div>";

echo "<div style='background: white; padding: 20px; border-radius: 10px; border-left: 4px solid #28a745;'>";
echo "<h3 style='color: #28a745; margin-top: 0;'>Runtime Info</h3>";
echo "<p><strong>PHP Version:</strong> " . phpversion() . "</p>";
echo "<p><strong>Current Time:</strong> " . date('Y-m-d H:i:s T') . "</p>";
echo "<p><strong>Timezone:</strong> America/New_York (Eastern)</p>";
echo "</div>";

echo "<div style='background: white; padding: 20px; border-radius: 10px; border-left: 4px solid #ffc107;'>";
echo "<h3 style='color: #e67e22; margin-top: 0;'>Request Info</h3>";
echo "<p><strong>HTTP Host:</strong> " . (\$_SERVER['HTTP_HOST'] ?? 'N/A') . "</p>";
echo "<p><strong>Request URI:</strong> " . (\$_SERVER['REQUEST_URI'] ?? 'N/A') . "</p>";
echo "<p><strong>Request Method:</strong> " . (\$_SERVER['REQUEST_METHOD'] ?? 'N/A') . "</p>";
echo "</div>";

echo "<div style='background: white; padding: 20px; border-radius: 10px; border-left: 4px solid #dc3545;'>";
echo "<h3 style='color: #dc3545; margin-top: 0;'>Network Info</h3>";
echo "<p><strong>Server IP:</strong> " . (\$_SERVER['SERVER_ADDR'] ?? 'N/A') . "</p>";
echo "<p><strong>Client IP:</strong> " . (\$_SERVER['REMOTE_ADDR'] ?? 'N/A') . "</p>";
echo "<p><strong>X-Forwarded-For:</strong> " . (\$_SERVER['HTTP_X_FORWARDED_FOR'] ?? 'N/A') . "</p>";
echo "</div>";

echo "</div>";

echo "<div style='text-align: center; margin: 30px 0;'>";
echo "<a href='/' style='display: inline-block; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; margin: 0 10px;'>← Back to Home</a>";
echo "<a href='/headers.php' style='display: inline-block; padding: 10px 20px; background: #28a745; color: white; text-decoration: none; border-radius: 5px; margin: 0 10px;'>View Headers</a>";
echo "</div>";

echo "</div>";
echo "<hr style='margin: 40px 0;'>";
phpinfo();
?>
EOF

# Create server info API endpoint
echo "🖥️  Creating server info API..."
cat > server.php << EOF
<?php
header('Content-Type: application/json');
date_default_timezone_set('America/New_York');

\$server_info = [
    'hostname' => gethostname(),
    'instance_id' => @file_get_contents('http://169.254.169.254/latest/meta-data/instance-id') ?: 'Unknown',
    'php_version' => phpversion(),
    'server_ip' => \$_SERVER['SERVER_ADDR'] ?? 'N/A',
    'timestamp' => date('c'),
    'site_name' => '$SITE_NAME',
    'domain' => '$SITE_NAME.webdev.vadai.org'
];

echo json_encode(\$server_info);
?>
EOF

# Create headers info page
echo "📋 Creating headers page..."
cat > headers.php << EOF
<?php
echo "<div style='font-family: Arial; max-width: 900px; margin: 20px auto; padding: 30px; background: #f8f9fa; border-radius: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);'>";
echo "<h1 style='color: #333; text-align: center;'>📋 Request Headers for ${SITE_NAME^^}</h1>";

echo "<div style='background: white; padding: 25px; border-radius: 10px; margin: 20px 0; border-left: 4px solid #17a2b8;'>";
echo "<h2 style='color: #17a2b8; margin-top: 0;'>HTTP Headers</h2>";
echo "<table style='width: 100%; border-collapse: collapse;'>";
echo "<tr style='background: #f8f9fa;'><th style='padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;'>Header</th><th style='padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;'>Value</th></tr>";

foreach (getallheaders() as \$name => \$value) {
    echo "<tr><td style='padding: 8px; border-bottom: 1px solid #dee2e6; font-weight: bold;'>\$name</td><td style='padding: 8px; border-bottom: 1px solid #dee2e6; word-break: break-all;'>\$value</td></tr>";
}

echo "</table>";
echo "</div>";

echo "<div style='background: white; padding: 25px; border-radius: 10px; margin: 20px 0; border-left: 4px solid #6f42c1;'>";
echo "<h2 style='color: #6f42c1; margin-top: 0;'>Server Variables</h2>";
echo "<table style='width: 100%; border-collapse: collapse;'>";
echo "<tr style='background: #f8f9fa;'><th style='padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;'>Variable</th><th style='padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;'>Value</th></tr>";

\$interesting_vars = ['HTTP_HOST', 'REQUEST_URI', 'REQUEST_METHOD', 'SERVER_NAME', 'SERVER_ADDR', 'REMOTE_ADDR', 'HTTP_X_FORWARDED_FOR', 'HTTP_X_FORWARDED_PROTO', 'HTTP_USER_AGENT'];

foreach (\$interesting_vars as \$var) {
    \$value = \$_SERVER[\$var] ?? 'Not Set';
    echo "<tr><td style='padding: 8px; border-bottom: 1px solid #dee2e6; font-weight: bold;'>\$var</td><td style='padding: 8px; border-bottom: 1px solid #dee2e6; word-break: break-all;'>\$value</td></tr>";
}

echo "</table>";
echo "</div>";

echo "<div style='text-align: center; margin: 30px 0;'>";
echo "<a href='/' style='display: inline-block; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; margin: 0 10px;'>← Back to Home</a>";
echo "<a href='/info.php' style='display: inline-block; padding: 10px 20px; background: #28a745; color: white; text-decoration: none; border-radius: 5px; margin: 0 10px;'>PHP Info</a>";
echo "</div>";

echo "</div>";
?>
EOF

# Start DDEV
echo "▶️  Starting DDEV site..."
ddev start

# Wait a moment for the site to be ready
sleep 3

# Test the site
echo ""
echo "🧪 Testing site..."
curl_test() {
    local url="$1"
    local expected="$2"
    echo -n "Testing $url: "
    if curl -s -H "Host: $SITE_NAME.webdev.vadai.org" "$url" | grep -q "$expected"; then
        echo "✅ OK"
    else
        echo "❌ Failed"
    fi
}

curl_test "http://localhost/" "$SITE_NAME"
curl_test "http://localhost/health.php" "OK"
curl_test "http://localhost/info.php" "PHP Info"
curl_test "http://localhost/server.php" "hostname"

echo ""
echo "✅ $SITE_NAME Site Created Successfully!"
echo ""
echo "🔗 Access URLs:"
echo "   • Local: http://$SITE_NAME.ddev.site"
echo "   • External: https://$SITE_NAME.webdev.vadai.org"
echo ""
echo "📄 Available Pages:"
echo "   • Home: https://$SITE_NAME.webdev.vadai.org/"
echo "   • Health: https://$SITE_NAME.webdev.vadai.org/health.php"
echo "   • PHP Info: https://$SITE_NAME.webdev.vadai.org/info.php"
echo "   • Server Info: https://$SITE_NAME.webdev.vadai.org/server.php"
echo "   • Headers: https://$SITE_NAME.webdev.vadai.org/headers.php"
echo ""
echo "🧪 Test Commands:"
echo "   curl -H 'Host: $SITE_NAME.webdev.vadai.org' http://localhost/"
echo "   curl https://$SITE_NAME.webdev.vadai.org/"
