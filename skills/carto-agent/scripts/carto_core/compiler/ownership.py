from __future__ import annotations

from typing import Any

from ..errors import ProtocolError


class OwnershipResolver:
    OWNERS = {"platform", "map-brand", "map-style", "map-layout", "map-scenario", "project"}

    def merge(self, segments: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        owners: dict[str, str] = {}
        for owner, values in segments:
            if owner not in self.OWNERS:
                raise ProtocolError("OWNERSHIP_OWNER_UNKNOWN", owner)
            for key, value in values.items():
                if key in result and result[key] != value:
                    raise ProtocolError("OWNERSHIP_CONFLICT", f"{key}: {owners[key]} vs {owner}")
                result[key] = value
                owners[key] = owner
        return {"values": result, "ownership": owners}
