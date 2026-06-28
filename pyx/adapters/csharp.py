"""C# language adapter for pyx bundles."""

from __future__ import annotations
from pathlib import Path

from ..domain import (
    BundleRequest,
    BundleResult,
    BundleManifest,
    Diagnostic,
    DiagnosticSeverity,
    LanguageAdapter,
)


class CsharpAdapter:
    """C# bundle adapter.

    Placeholder adapter that provides a clear not-yet-implemented error.
    """

    def __init__(self, extractor: Path | None = None):
        """Initialize the C# adapter.

        Args:
            extractor: Path to the C# class context extractor (not yet used).
        """
        self.extractor = extractor

    @property
    def language(self) -> str:
        return "csharp"

    @property
    def file_extensions(self) -> list[str]:
        return [".cs"]

    def bundle(self, request: BundleRequest) -> BundleResult:
        """Create a C# bundle from the given request.

        Currently not implemented - provides a clear error message.
        """
        return BundleResult(
            success=False,
            manifest=BundleManifest(
                language=self.language,
                seeds=[str(s.relative_to(request.project_root)) for s in request.seeds],
                files=[],
                project_files=[],
                dependencies={},
                run_commands=[],
                diagnostics=[],
            ),
            output_dir=request.output_dir,
            errors=[
                Diagnostic(
                    DiagnosticSeverity.ERROR,
                    "C# bundling is not yet implemented. See https://github.com/renanliberato/pyx/issues/4",
                    code="CSharpNotImplemented",
                )
            ],
        )