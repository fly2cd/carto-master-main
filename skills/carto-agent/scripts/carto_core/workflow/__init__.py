"""Workflow state, intent, approvals, and bounded agent runtime."""

from .budget_store import BudgetStore
from .data_adoption import DataAdoptionService
from .material_extraction import MaterialExtractionService
from ..contracts.execution import ExecutionBudget, ExecutionContext, JobState, StepReceipt
from .template_validation import TemplatePackageValidator
from .template_workflow import TemplateCreationWorkflow

__all__ = [
    "BudgetStore",
    "DataAdoptionService",
    "ExecutionBudget",
    "ExecutionContext",
    "JobState",
    "MapGenerationWorkflow",
    "MaterialExtractionService",
    "StepReceipt",
    "TemplateCreationWorkflow",
    "TemplatePackageValidator",
]


def __getattr__(name: str):
    if name == "MapGenerationWorkflow":
        from .map_generation import MapGenerationWorkflow
        return MapGenerationWorkflow
    raise AttributeError(name)
