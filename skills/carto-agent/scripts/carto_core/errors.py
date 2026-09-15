from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CartoError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class ConfigurationError(CartoError):
    pass


class SecurityError(CartoError):
    pass


class ProtocolError(CartoError):
    pass
