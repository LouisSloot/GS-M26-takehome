"""Prompt expansion pipeline for synthetic data generation."""

__all__ = ["LoadSeedsFromCSV", "PromptExpansionTask", "ExportExpandedStep"]

# Lazy import to allow using config/seed_utils without distilabel
def __getattr__(name: str):
    if name == "LoadSeedsFromCSV":
        from expansion_pipeline.load_seeds import LoadSeedsFromCSV
        return LoadSeedsFromCSV
    if name == "PromptExpansionTask":
        from expansion_pipeline.prompt_expansion import PromptExpansionTask
        return PromptExpansionTask
    if name == "ExportExpandedStep":
        from expansion_pipeline.export_expanded import ExportExpandedStep
        return ExportExpandedStep
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
