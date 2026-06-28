"""C# language adapter for pyx bundles."""

from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..domain import (
    BundleRequest,
    BundleResult,
    BundleManifest,
    RunCommand,
    Diagnostic,
    DiagnosticSeverity,
)


class CsharpAdapter:
    """C# bundle adapter that integrates with chsarp-class-context extractor.

    Handles:
    - Invoking the chsarp-class-context CLI with seed files and project root
    - Consuming structured JSON extraction results
    - Copying source files to their requested bundle paths
    - Writing generated project files including .csproj
    - Recording diagnostics and failing on non-runnable results
    """

    def __init__(self, extractor: Path | None = None):
        """Initialize the C# adapter.

        Args:
            extractor: Path to the C# class context extractor CLI.
                      Defaults to vendor/chsarp-class-context/bin/chsarp-class-context
        """
        self.extractor = extractor or Path("vendor/chsarp-class-context/bin/chsarp-class-context")

    @property
    def language(self) -> str:
        return "csharp"

    @property
    def file_extensions(self) -> list[str]:
        return [".cs"]

    def bundle(self, request: BundleRequest) -> BundleResult:
        """Create a C# bundle from the given request."""
        if request.output_dir.exists():
            shutil.rmtree(request.output_dir)
        request.output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve extractor path relative to project root
        extractor_path = request.project_root / self.extractor if not self.extractor.is_absolute() else self.extractor

        # Invoke the extractor
        try:
            extraction_result = self._invoke_extractor(
                extractor_path=extractor_path,
                seeds=request.seeds,
                project_root=request.project_root,
            )
        except FileNotFoundError as e:
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
                        f"C# extractor not found at {extractor_path}. "
                        f"Ensure chsarp-class-context submodule is available. "
                        f"Original error: {e}",
                        code="ExtractorNotFound",
                    )
                ],
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
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
                        f"C# extractor failed with exit code {e.returncode}. "
                        f"Stderr: {stderr}",
                        code="ExtractorFailed",
                    )
                ],
            )
        except json.JSONDecodeError as e:
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
                        f"Failed to parse extractor JSON output: {e}",
                        code="InvalidExtractorOutput",
                    )
                ],
            )

        # Parse extraction result
        files_data = extraction_result.get("files", [])
        project_data = extraction_result.get("project", {})
        extractor_diagnostics = extraction_result.get("diagnostics", [])

        # Convert extractor diagnostics to our Diagnostic type
        diagnostics: list[Diagnostic] = [
            self._parse_diagnostic(d) for d in extractor_diagnostics
        ]

        # Check for non-runnable diagnostics
        non_runnable = [d for d in diagnostics if d.severity == DiagnosticSeverity.ERROR]
        if non_runnable:
            return BundleResult(
                success=False,
                manifest=BundleManifest(
                    language=self.language,
                    seeds=[str(s.relative_to(request.project_root)) for s in request.seeds],
                    files=[],
                    project_files=[],
                    dependencies={},
                    run_commands=[],
                    diagnostics=[
                        {
                            "severity": d.severity.value,
                            "message": d.message,
                            "code": d.code,
                        }
                        for d in diagnostics
                    ],
                ),
                output_dir=request.output_dir,
                errors=non_runnable,
            )

        # Copy source files to bundle
        copied_files: list[str] = []
        for file_entry in files_data:
            source_path_str = file_entry.get("sourcePath")
            bundle_path_str = file_entry.get("bundlePath")

            if not source_path_str or not bundle_path_str:
                diagnostics.append(
                    Diagnostic(
                        DiagnosticSeverity.WARNING,
                        f"Skipping file entry with missing sourcePath or bundlePath: {file_entry}",
                        code="InvalidFileEntry",
                    )
                )
                continue

            source_path = Path(source_path_str)
            bundle_path = request.output_dir / bundle_path_str

            if not source_path.exists():
                diagnostics.append(
                    Diagnostic(
                        DiagnosticSeverity.WARNING,
                        f"Source file not found: {source_path}",
                        code="SourceFileNotFound",
                    )
                )
                continue

            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, bundle_path)
            copied_files.append(bundle_path_str)

        # Write generated project files
        project_files: list[str] = []

        # Generate .csproj from project metadata
        csproj_content = self._generate_csproj(project_data)
        csproj_path = request.output_dir / "TestProject.csproj"
        csproj_path.write_text(csproj_content)
        project_files.append("TestProject.csproj")

        # Write any additional project files returned by extractor
        additional_project_files = extraction_result.get("projectFiles", {})
        for file_path, content in additional_project_files.items():
            dst_path = request.output_dir / file_path
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.write_text(content)
            project_files.append(file_path)

        # Build dependencies summary
        dependencies = {
            "targetFramework": project_data.get("targetFramework", "unknown"),
            "packages": len(project_data.get("packageReferences", [])),
            "frameworks": len(project_data.get("frameworkReferences", [])),
        }

        # Determine run commands from extractor or use defaults
        run_commands_data = extraction_result.get("runCommands", [])
        if run_commands_data:
            run_commands = [
                RunCommand(
                    command=cmd["command"],
                    cwd=Path(cmd["cwd"]) if cmd.get("cwd") else None,
                    description=cmd.get("description"),
                )
                for cmd in run_commands_data
            ]
        else:
            run_commands = [
                RunCommand(
                    command=["dotnet", "restore"],
                    cwd=None,
                    description="Restore NuGet packages",
                ),
                RunCommand(
                    command=["dotnet", "test", "--no-build"],
                    cwd=None,
                    description="Run tests",
                ),
            ]

        # Create manifest
        manifest = BundleManifest(
            language=self.language,
            seeds=[str(s.relative_to(request.project_root)) for s in request.seeds],
            files=copied_files,
            project_files=project_files,
            dependencies=dependencies,
            run_commands=run_commands,
            diagnostics=diagnostics,
        )

        # Write manifest
        manifest_path = request.output_dir / "pyx-manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2))

        return BundleResult(
            success=True,
            manifest=manifest,
            output_dir=request.output_dir,
            errors=[d for d in diagnostics if d.severity == DiagnosticSeverity.ERROR],
        )

    def _invoke_extractor(
        self,
        extractor_path: Path,
        seeds: list[Path],
        project_root: Path,
    ) -> dict[str, Any]:
        """Invoke the C# extractor CLI and return parsed JSON output.

        Args:
            extractor_path: Path to the extractor executable
            seeds: List of seed file paths
            project_root: Project root directory

        Returns:
            Parsed JSON extraction result

        Raises:
            FileNotFoundError: If extractor doesn't exist
            subprocess.CalledProcessError: If extractor fails
            json.JSONDecodeError: If output is not valid JSON
        """
        if not extractor_path.exists():
            raise FileNotFoundError(f"Extractor not found: {extractor_path}")

        # Build command: <extractor> --seed <file1> --seed <file2> --root <project_root>
        cmd = [str(extractor_path)]
        for seed in seeds:
            cmd.extend(["--seed", str(seed)])
        cmd.extend(["--root", str(project_root)])

        result = subprocess.run(
            cmd,
            capture_output=True,
            cwd=project_root,
            check=True,
        )

        output = result.stdout.decode("utf-8", errors="replace")
        return json.loads(output)

    def _generate_csproj(self, project_data: dict[str, Any]) -> str:
        """Generate a .csproj file from project metadata.

        Args:
            project_data: Project metadata from extractor

        Returns:
            Complete .csproj file content
        """
        lines = ['<Project Sdk="Microsoft.NET.Sdk">']
        lines.append("  <PropertyGroup>")

        # Basic properties
        target_framework = project_data.get("targetFramework", "net8.0")
        lines.append(f"    <TargetFramework>{target_framework}</TargetFramework>")

        # Additional properties from extractor
        properties = project_data.get("properties", {})
        for key, value in properties.items():
            lines.append(f"    <{key}>{value}</{key}>")

        # Bundle-specific properties
        lines.append("    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>")
        lines.append("    <IsPackable>false</IsPackable>")

        lines.append("  </PropertyGroup>")

        # Package references
        package_refs = project_data.get("packageReferences", [])
        if package_refs:
            lines.append("  <ItemGroup>")
            for pkg in package_refs:
                name = pkg.get("name", pkg.get("Include", ""))
                version = pkg.get("version", pkg.get("Version", ""))
                if name and version:
                    lines.append(f'    <PackageReference Include="{name}" Version="{version}" />')
            lines.append("  </ItemGroup>")

        # Framework references
        framework_refs = project_data.get("frameworkReferences", [])
        if framework_refs:
            lines.append("  <ItemGroup>")
            for fw in framework_refs:
                name = fw.get("name", fw.get("Include", ""))
                if name:
                    lines.append(f'    <FrameworkReference Include="{name}" />')
            lines.append("  </ItemGroup>")

        # Compile items
        compile_includes = project_data.get("compileIncludes", [])
        if compile_includes:
            lines.append("  <ItemGroup>")
            for include in compile_includes:
                lines.append(f'    <Compile Include="{include}" />')
            lines.append("  </ItemGroup>")

        lines.append("</Project>")
        return "\n".join(lines)

    def _parse_diagnostic(self, diag_data: dict[str, Any]) -> Diagnostic:
        """Parse a diagnostic from extractor output.

        Args:
            diag_data: Diagnostic data from extractor

        Returns:
            Diagnostic instance
        """
        severity_str = diag_data.get("severity", "info").lower()
        severity = {
            "info": DiagnosticSeverity.INFO,
            "warning": DiagnosticSeverity.WARNING,
            "error": DiagnosticSeverity.ERROR,
        }.get(severity_str, DiagnosticSeverity.INFO)

        return Diagnostic(
            severity=severity,
            message=diag_data.get("message", ""),
            code=diag_data.get("code"),
        )