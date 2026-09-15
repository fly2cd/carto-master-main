from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Iterable, TypeVar

from ..errors import ProtocolError

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CatalogEntry(Generic[T]):
    item_id: str
    version: str
    value: T


class VersionedCatalog(Generic[T]):
    def __init__(self, entries: Iterable[CatalogEntry[T]] = ()) -> None:
        self._entries: dict[tuple[str, str], T] = {}
        for entry in entries:
            self.register(entry.item_id, entry.version, entry.value)

    def register(self, item_id: str, version: str, value: T) -> None:
        key = (item_id, version)
        if key in self._entries:
            raise ProtocolError("CATALOG_ENTRY_DUPLICATE", f"{item_id}@{version}")
        self._entries[key] = value

    def get(self, item_id: str, version: str) -> T:
        try:
            return self._entries[(item_id, version)]
        except KeyError as exc:
            raise ProtocolError("CATALOG_ENTRY_NOT_FOUND", f"{item_id}@{version}") from exc

    def versions(self, item_id: str) -> tuple[str, ...]:
        return tuple(sorted(version for name, version in self._entries if name == item_id))
