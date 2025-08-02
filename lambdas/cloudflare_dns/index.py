# File: lambdas/cloudflare_dns/index.py

import json
import urllib3
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    """
    CloudFlare DNS management Lambda function
    Handles Create, Update, and Delete operations for DNS records
    """
    logger.info(f"Event: {json.dumps(event)}")
    
    request_type = event['RequestType']
    props = event['ResourceProperties']
    
    # Get CloudFlare credentials from SSM
    ssm = boto3.client('ssm')
    
    try:
        cf_token = ssm.get_parameter(
            Name='/ddev-demo/cloudflare/api-token', 
            WithDecryption=True
        )['Parameter']['Value']
        
        cf_zone_id = ssm.get_parameter(
            Name='/ddev-demo/cloudflare/zone-id'
        )['Parameter']['Value']
        
        if cf_token == 'PLACEHOLDER-SET-MANUALLY':
            logger.warning("CloudFlare credentials not set, skipping DNS update")
            return {'PhysicalResourceId': f"cf-dns-{props['DomainName']}-placeholder"}
            
    except Exception as e:
        logger.error(f"Error getting credentials: {e}")
        return {'PhysicalResourceId': f"cf-dns-{props['DomainName']}-error"}
    
    domain_name = props['DomainName']
    target_value = props['TargetValue']
    record_type = props.get('RecordType', 'CNAME')
    
    http = urllib3.PoolManager()
    
    headers = {
        'Authorization': f'Bearer {cf_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        if request_type in ['Create', 'Update']:
            # Check if record exists
            list_url = f'https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records'
            list_params = {'name': domain_name, 'type': record_type}
            
            response = http.request('GET', list_url, fields=list_params, headers=headers)
            existing_records = json.loads(response.data.decode('utf-8'))
            
            record_data = {
                'type': record_type,
                'name': domain_name,
                'content': target_value,
                'ttl': 300
            }
            
            if existing_records['result']:
                # Update existing record
                record_id = existing_records['result'][0]['id']
                update_url = f'https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records/{record_id}'
                response = http.request('PUT', update_url, 
                                      body=json.dumps(record_data), 
                                      headers=headers)
                logger.info(f"Updated DNS record for {domain_name}")
            else:
                # Create new record
                create_url = f'https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records'
                response = http.request('POST', create_url, 
                                      body=json.dumps(record_data), 
                                      headers=headers)
                logger.info(f"Created DNS record for {domain_name}")
            
            result = json.loads(response.data.decode('utf-8'))
            if not result['success']:
                logger.error(f"CloudFlare API error: {result['errors']}")
                return {'PhysicalResourceId': f"cf-dns-{domain_name}-error"}
                
            return {
                'PhysicalResourceId': f"cf-dns-{domain_name}",
                'Data': {'RecordId': result['result']['id']}
            }
                
        elif request_type == 'Delete':
            # Delete the DNS record
            list_url = f'https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records'
            list_params = {'name': domain_name, 'type': record_type}
            
            response = http.request('GET', list_url, fields=list_params, headers=headers)
            existing_records = json.loads(response.data.decode('utf-8'))
            
            if existing_records['result']:
                record_id = existing_records['result'][0]['id']
                delete_url = f'https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records/{record_id}'
                response = http.request('DELETE', delete_url, headers=headers)
                logger.info(f"Deleted DNS record for {domain_name}")
                
    except Exception as e:
        logger.error(f"Error managing DNS: {e}")
        return {'PhysicalResourceId': f"cf-dns-{domain_name}-error"}
    
    return {'PhysicalResourceId': f"cf-dns-{domain_name}"}