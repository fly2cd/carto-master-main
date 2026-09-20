"""Workflow state, intent, approvals, and bounded agent runtime."""

from .models import ExecutionBudget, ExecutionContext, JobState, StepReceipt
from .template_validation import TemplatePackageValidator
from .template_workflow import TemplateCreationWorkflow

__all__ = [
    "ExecutionBudget",
    "ExecutionContext",
    "JobState",
    "MapGenerationWorkflow",
    "StepReceipt",
    "TemplateCreationWorkflow",
    "TemplatePackageValidator",
]


def __getattr__(name: str):
    if name == "MapGenerationWorkflow":
        from .map_generation import MapGenerationWorkflow
        return MapGenerationWorkflow
    raise AttributeError(name)
