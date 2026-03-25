from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    """Deterministic application error that can be serialized for automation."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": False, "error_code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload
