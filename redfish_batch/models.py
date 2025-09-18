from dataclasses import dataclass
from typing import Optional

@dataclass
class Host:
    base_url: str
    username: str
    password: str | None = None
    verify: bool = False
    name: Optional[str] = None