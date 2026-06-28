"""Language-agnostic domain model for pyx bundles."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable


class DiagnosticSeverity(Enum):
    """Severity level for diagnostics."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Diagnostic:
    """A diagnostic message from an adapter or extractor."""
    severity: DiagnosticSeverity
    message: str
    code: str | None = None  # Optional machine-readable code


@dataclass
class RunCommand:
    """A command that can be run to verify or use the bundle."""
    command: list[str]  # Executable and args, e.g., ["flutter", "test"]
    cwd: Path | None = None  # Working directory relative to bundle root
    description: str | None = None  # Human-readable description


@dataclass
class BundleRequest:
    """Request to create a bundle from seed inputs."""
    seeds: list[Path]  # Seed files/directories
    project_root: Path  # Root of the project
    output_dir: Path  # Where to write the bundle
    language: str  # Language identifier (e.g., "dart", "csharp")
    config: dict  # Adapter-specific config


@dataclass
class BundleManifest:
    """Manifest that describes a bundle's contents and how to use it."""
    language: str  # Selected adapter, e.g., "dart" or "csharp"
    seeds: list[str]  # Original seed inputs (relative to project root)
    files: list[str]  # Source/content files copied into the bundle (relative to bundle root)
    project_files: list[str]  # Generated or copied project metadata files (relative to bundle root)
    dependencies: dict  # Adapter-provided dependency summary
    run_commands: list[dict]  # RunCommand data serialized for JSON
    diagnostics: list[dict]  # Diagnostic data serialized for JSON

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "language": self.language,
            "seeds": self.seeds,
            "files": self.files,
            "project_files": self.project_files,
            "dependencies": self.dependencies,
            "run_commands": [
                {
                    "command": cmd.command,
                    "cwd": str(cmd.cwd) if cmd.cwd else None,
                    "description": cmd.description,
                }
                for cmd in self.run_commands
            ],
            "diagnostics": [
                {
                    "severity": diag.severity.value,
                    "message": diag.message,
                    "code": diag.code,
                }
                for diag in self.diagnostics
            ],
        }


@dataclass
class BundleResult:
    """Result of a bundle operation."""
    success: bool
    manifest: BundleManifest
    output_dir: Path
    errors: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "success": self.success,
            "manifest": self.manifest.to_dict(),
            "output_dir": str(self.output_dir),
            "errors": [
                {
                    "severity": e.severity.value,
                    "message": e.message,
                    "code": e.code,
                }
                for e in self.errors
            ],
        }


@runtime_checkable
class LanguageAdapter(Protocol):
    """Protocol for language-specific bundle adapters.

    Each adapter owns seed discovery, bundling, manifest data, diagnostics,
    and verification commands for its language.
    """

    @property
    def language(self) -> str:
        """Language identifier (e.g., "dart", "csharp")."""
        ...

    @property
    def file_extensions(self) -> list[str]:
        """File extensions this adapter handles (e.g., [".dart", ".dart_test"])."""
        ...

    def bundle(self, request: BundleRequest) -> BundleResult:
        """Create a bundle from the given request.

        Args:
            request: Bundle request with seeds, project root, output dir, and config.

        Returns:
            BundleResult with success status, manifest, and any errors.
        """
        ...