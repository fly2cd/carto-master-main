"""Deterministic protocol compiler building blocks."""

from .dependencies import DependencyResolver
from .expression_validator import ExpressionValidator
from .ownership import OwnershipResolver
from .protocol import CompileRequest, ProtocolCompiler

__all__ = [
    "CompileRequest",
    "DependencyResolver",
    "ExpressionValidator",
    "MapCandidateCompiler",
    "MapSpecLockCompiler",
    "OwnershipResolver",
    "ProtocolCompiler",
]


def __getattr__(name: str):
    if name == "MapCandidateCompiler":
        from .map_candidate import MapCandidateCompiler
        return MapCandidateCompiler
    if name == "MapSpecLockCompiler":
        from .map_lock import MapSpecLockCompiler
        return MapSpecLockCompiler
    raise AttributeError(name)
