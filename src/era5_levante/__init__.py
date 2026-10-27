"""Small, read-only interface to DKRZ's final ERA5 (E5) archive."""

from .archive import (
    DEFAULT_ROOT,
    FileSelection,
    IncompatibleGribError,
    MissingCoverageError,
    TimeCoverageError,
    open_data,
    resolve_files,
)
from .catalog import Parameter, ProductAvailability, get_parameter, search

__all__ = [
    "DEFAULT_ROOT",
    "FileSelection",
    "IncompatibleGribError",
    "MissingCoverageError",
    "TimeCoverageError",
    "Parameter",
    "ProductAvailability",
    "get_parameter",
    "open_data",
    "resolve_files",
    "search",
]
