# File: configs/models.py

from dataclasses import dataclass
from typing import List


@dataclass
class InfrastructureSpec:
    account: str
    region: str