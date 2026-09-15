from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry, load_document


@dataclass(frozen=True, slots=True)
class KnowledgeEvidence:
    schema_version: int
    evidence_id: str
    claim: str
    publisher: str
    source: dict[str, Any]
    applicability: dict[str, str]
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DomainKnowledgeService:
    """Queries only explicitly registered, local, versioned knowledge records."""

    def __init__(self, policy_path: Path, records: Iterable[dict[str, Any]] = ()) -> None:
        policy = load_document(policy_path)
        self.policy_version = str(policy["version"])
        self._sources = {item["source_id"]: item for item in policy["sources"]}
        self._external_search_enabled = bool(policy.get("external_search", {}).get("enabled"))
        self._records = tuple(dict(record) for record in records)

    def lookup_or_search(self, query: str, applicability: str, access_context: Any) -> list[KnowledgeEvidence]:
        if not query.strip():
            raise ProtocolError("KNOWLEDGE_QUERY_EMPTY", "Knowledge query must not be empty")
        classification = getattr(access_context, "classification", "internal")
        terms = {term.casefold() for term in query.split() if term}
        results: list[KnowledgeEvidence] = []
        for record in self._records:
            source_id = str(record.get("source_id", ""))
            source = self._sources.get(source_id)
            if source is None:
                raise SecurityError("KNOWLEDGE_SOURCE_UNREGISTERED", source_id)
            if source.get("access") != "local-read-only":
                raise SecurityError("KNOWLEDGE_ACCESS_DENIED", source_id)
            if classification == "public" and source.get("classification") != "public":
                continue
            haystack = " ".join(str(record.get(key, "")) for key in ("term", "title", "content", "entity_id")).casefold()
            if terms and not all(term in haystack for term in terms):
                continue
            applies = dict(record.get("applicability", {"jurisdiction": "general", "valid_from": "1970-01-01"}))
            jurisdiction = str(applies.get("jurisdiction", "general"))
            if applicability not in {"general", jurisdiction} and jurisdiction != "general":
                continue
            body = {
                "schema_version": 1,
                "evidence_id": f"evidence-{len(results) + 1}",
                "claim": str(record.get("content", ""))[:2000],
                "publisher": str(record["publisher"]),
                "source": {
                    "source_type": str(record.get("source_type", "internal")),
                    "source_ref": str(record["source_ref"]),
                    "version": str(record["version"]),
                    "classification": str(source["classification"]),
                },
                "applicability": applies,
            }
            evidence = KnowledgeEvidence(digest=sha256_digest(body), **body)
            SchemaRegistry().validate("knowledge-evidence", evidence.to_dict())
            results.append(evidence)
        return results

    def external_search_allowed(self) -> bool:
        return self._external_search_enabled
