# File: configs/config.py

import os
import string
from pathlib import Path
from dotenv import load_dotenv

import yaml
from dacite import from_dict

from configs.models import InfrastructureSpec, VpcConfig, Ec2Config, LoggingConfig, EndpointsConfig, EndpointService, WafConfig
from utils.converters import to_dict
from utils.converters import update
from utils.logger import configure_logger

LOGGER = configure_logger(__name__)

class AppConfigs:
    
    def __init__(self):
        # Load environment variables from .env file if it exists
        env_file = Path(".env")
        if env_file.exists():
            load_dotenv(env_file)
            LOGGER.info("Loaded environment variables from .env file")
        else:
            LOGGER.info("No .env file found, using system environment variables")

    def load_yaml(self, file, context):
        def string_constructor(loader, node):
            t = string.Template(node.value)
            # Substitute with both context and environment variables
            combined_context = {**os.environ, **context}
            value = t.substitute(combined_context)
            return value

        loader = yaml.SafeLoader
        loader.add_constructor("tag:yaml.org,2002:str", string_constructor)

        token_re = string.Template.pattern
        loader.add_implicit_resolver("tag:yaml.org,2002:str", token_re, None)

        x = yaml.load(file, Loader=loader)
        return x

    # This method read the Yaml file and return the object data
    def from_yaml(self, config_file: str, *, context: dict[str, str] = {}):
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Could not find YAML file at {config_file}")
        with open(config_file, "r") as file:
            data = self.load_yaml(file, context=context)
            data = {} if data is None else data

        return data

    def validate_required_env_vars(self, account_name: str):
        """Validate that required environment variables are set"""
        required_vars = []
        
        if account_name == "sandbox":
            required_vars = ["SANDBOX_ACCOUNT_ID", "SANDBOX_REGION"]
        elif account_name == "production":
            required_vars = ["PRODUCTION_ACCOUNT_ID", "PRODUCTION_REGION"]
        elif account_name == "development":
            required_vars = ["DEV_ACCOUNT_ID", "DEV_REGION"]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            raise ValueError(
                f"Missing required environment variables for '{account_name}' environment: {missing_vars}\n"
                f"Please set these variables or create a .env file. See .env.example for reference."
            )

    # This method get infrastructure specification data from the infrastructure Yaml file.
    def get_infrastructure_info(self, account_name: str) -> InfrastructureSpec:
        # Validate environment variables before proceeding
        self.validate_required_env_vars(account_name)
        
        context = {"account": account_name}
        data_raw = self.from_yaml("configs/infrastructure.yaml", context=context)
        data: dict = to_dict(data_raw)
        globals_config = data.get("globals", {})
        accounts = data.get("accounts", [])
        account = next((x for x in accounts if x["name"] == account_name), {})

        if not account:
            raise ValueError(f"Account '{account_name}' not found in infrastructure.yaml")

        # Merge global and account-specific configurations
        merged_config = update(globals_config.copy(), account)
        
        # Log the account being used (without exposing the full account ID)
        account_id = merged_config.get("account", "unknown")
        masked_account = f"***{account_id[-4:]}" if account_id != "unknown" else "unknown"
        LOGGER.info(f"Using account: {masked_account} for environment: {account_name}")
        
        # Create configuration objects
        vpc_config = None
        if "vpc" in merged_config:
            vpc_config = from_dict(data_class=VpcConfig, data=merged_config["vpc"])
            
        ec2_config = None
        if "ec2" in merged_config:
            ec2_config = from_dict(data_class=Ec2Config, data=merged_config["ec2"])
            
        logging_config = None
        if "logging" in merged_config:
            logging_config = from_dict(data_class=LoggingConfig, data=merged_config["logging"])
            
        endpoints_config = None
        if "endpoints" in merged_config:
            services_data = merged_config["endpoints"].get("services", [])
            endpoint_services = [
                from_dict(data_class=EndpointService, data=service)
                for service in services_data
            ]
            endpoints_config = EndpointsConfig(services=endpoint_services)

        waf_config = None
        if "waf" in merged_config:
            waf_data = merged_config["waf"]
            waf_config = from_dict(data_class=WafConfig, data=waf_data)

        return InfrastructureSpec(
            account=merged_config["account"],
            region=merged_config["region"],
            vpc=vpc_config,
            ec2=ec2_config,
            logging=logging_config,
            endpoints=endpoints_config,
            waf=waf_config
        )