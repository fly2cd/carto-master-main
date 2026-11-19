"""Versioned repositories used by the Carto Agent runtime."""

from .catalog import VersionedCatalog
from .immutable_store import ImmutableArtifactStore, StoredArtifact
from .knowledge import DomainKnowledgeService, KnowledgeEvidence
from .staging_package import StagingPackageWriter
from .template_matching import MatchingPolicy, rank_segment_candidates
from .template_repository import TemplateRepository

__all__ = [
    "DomainKnowledgeService",
    "ImmutableArtifactStore",
    "KnowledgeEvidence",
    "MatchingPolicy",
    "StagingPackageWriter",
    "StoredArtifact",
    "TemplateRepository",
    "VersionedCatalog",
    "rank_segment_candidates",
]

from .template_installer import ProjectTemplateInstaller
