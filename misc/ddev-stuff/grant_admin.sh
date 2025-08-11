#!/bin/bash

# Script to grant admin permissions to a Guacamole user
# Usage: ./grant_admin.sh "username"

# Check if username provided
if [ -z "$1" ]; then
    echo "Usage: $0 \"username\""
    echo "Example: $0 \"c4e8c418-50e1-705e-7fd7-4b117a1addd6\""
    exit 1
fi

USERNAME="$1"
MYSQL_CONTAINER="guacamole-mysql"
MYSQL_USER="guacamole_user"
MYSQL_PASSWORD="guacamole_password"
MYSQL_DATABASE="guacamole_db"

echo "Granting admin permissions to user: $USERNAME"

# SQL script to grant permissions
SQL_SCRIPT="
-- Find the user and get their entity_id
SELECT @entity_id := entity_id FROM guacamole_entity WHERE name = '$USERNAME';

-- Check if user exists
SELECT IF(@entity_id IS NULL, 'User not found!', CONCAT('Found user with entity_id: ', @entity_id)) as status;

-- Grant ADMINISTER permission (only if user exists)
INSERT IGNORE INTO guacamole_system_permission (entity_id, permission)
SELECT @entity_id, 'ADMINISTER' WHERE @entity_id IS NOT NULL;

-- Grant CREATE_CONNECTION permission
INSERT IGNORE INTO guacamole_system_permission (entity_id, permission)
SELECT @entity_id, 'CREATE_CONNECTION' WHERE @entity_id IS NOT NULL;

-- Grant CREATE_USER permission
INSERT IGNORE INTO guacamole_system_permission (entity_id, permission)
SELECT @entity_id, 'CREATE_USER' WHERE @entity_id IS NOT NULL;

-- Grant CREATE_CONNECTION_GROUP permission
INSERT IGNORE INTO guacamole_system_permission (entity_id, permission)
SELECT @entity_id, 'CREATE_CONNECTION_GROUP' WHERE @entity_id IS NOT NULL;

-- Grant CREATE_SHARING_PROFILE permission
INSERT IGNORE INTO guacamole_system_permission (entity_id, permission)
SELECT @entity_id, 'CREATE_SHARING_PROFILE' WHERE @entity_id IS NOT NULL;

-- Show final permissions for this user
SELECT 'Permissions granted:' as result;
SELECT gsp.permission
FROM guacamole_system_permission gsp
JOIN guacamole_entity ge ON gsp.entity_id = ge.entity_id
WHERE ge.name = '$USERNAME';
"

# Execute the SQL script
docker exec -i "$MYSQL_CONTAINER" mysql -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" << EOF
$SQL_SCRIPT
EOF

if [ $? -eq 0 ]; then
    echo "✅ Successfully granted admin permissions to user: $USERNAME"
    echo ""
    echo "The user should now be able to:"
    echo "- Create connections"
    echo "- Create users"
    echo "- Administer the system"
    echo "- Create connection groups"
    echo "- Create sharing profiles"
    echo ""
    echo "Please refresh your browser and log in again."
else
    echo "❌ Failed to grant permissions. Check the error messages above."
    exit 1
fi
