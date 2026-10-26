"""SteelMind's deterministic deliverable generator; no LLM key required."""

__version__ = "1.0.0"

from .models import DesignBundle
from .results import BundleValidationError, GenerationOptions, GenerationResult
from .validation import validate_bundle
from .pipeline import generate_calculation_book, generate_design_files, generate_package

__all__ = [
    "DesignBundle", "GenerationOptions", "GenerationResult", "BundleValidationError",
    "validate_bundle", "generate_calculation_book", "generate_design_files", "generate_package",
]
