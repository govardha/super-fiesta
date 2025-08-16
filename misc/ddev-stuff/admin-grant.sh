# Quick one-liner to make the user admin
docker exec -i guacamole-mysql mysql -u guacamole_user -pguacamole_password guacamole_db -e "
SET @entity_id = (SELECT entity_id FROM guacamole_entity WHERE name = 'c4e8c418-50e1-705e-7fd7-4b117a1addd6' AND type = 'USER');
INSERT IGNORE INTO guacamole_system_permission (entity_id, permission) VALUES (@entity_id, 'ADMINISTER'), (@entity_id, 'CREATE_CONNECTION'), (@entity_id, 'CREATE_CONNECTION_GROUP'), (@entity_id, 'CREATE_SHARING_PROFILE'), (@entity_id, 'CREATE_USER'), (@entity_id, 'CREATE_USER_GROUP');
SELECT CASE WHEN @entity_id IS NULL THEN 'User not found - they need to log in first' ELSE 'Admin permissions granted successfully' END as result;
"
