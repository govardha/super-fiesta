# File: configs/config.py

import os
import string

import yaml
from dacite import from_dict

from configs.models import InfrastructureSpec
from utils.converters import to_dict
from utils.converters import update
from utils.logger import configure_logger

LOGGER = configure_logger(__name__)

class AppConfigs:
    def load_yaml(self, file, context):
        def string_constructor(loader, node):
            t = string.Template(node.value)
            value = t.substitute(context)

            return value

        loader = yaml.SafeLoader
        loader.add_constructor("tag:yaml.org,2002:str", string_constructor)

        token_re = string.Template.pattern
        loader.add_implicit_resolver("tag:yaml.org,2002:str", token_re, None)

        x = yaml.load(file, Loader=loader)
        return x

    # This method read the Yaml file and retun the object data
    def from_yaml(self, config_file: str, *, context: dict[str, str] = {}):
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Could not find YAML file at {config_file}")
        with open(config_file, "r") as file:
            # data = yaml.load(file, Loader=yaml.FullLoader)

            data = self.load_yaml(file, context=context)
            data = {} if data is None else data

        return data

    # This method get infrastructure specification data from the infrastructure Yaml file.
    def get_infrastructure_info(self, account_name: str) -> InfrastructureSpec:
        context = {"account": account_name}
        data_raw = self.from_yaml("configs/infrastructure.yaml", context=context)
        data: dict = to_dict(data_raw)
        globals = data.get("globals", {})
        accounts = data.get("accounts", {})
        account = next((x for x in accounts if x["name"] == account_name), {})

        # Merge two dictionaries
        merged_config = update(globals, account)
        