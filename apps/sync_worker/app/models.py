from dataclasses import dataclass
from typing import Any


@dataclass (slots=True)
class ApiResult:
    method: str
    endpoint: str
    params: dict [str, Any]
    status_code: int
    elapsed_ms: int
    payload: Any
    response_text: str