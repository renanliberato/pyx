"""C# adapter integration tests with fake extractor."""

from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

from pyx.adapters.csharp import CsharpAdapter
from pyx.domain import BundleRequest, DiagnosticSeverity


@pytest.fixture
def csharp_project(tmp_path: Path) -> Path:
    """Create a minimal C# project for testing."""
    project = tmp_path / "csharp-project"
    project.mkdir()

    # Create a test file
    test_file = project / "SimpleTest.cs"
    test_file.write_text(dedent("""\
        using NUnit.Framework;

        namespace Tests
        {
            public class SimpleTest
            {
                [Test]
                public void SimpleTestPasses()
                {
                    Assert.AreEqual(2, 1 + 1);
                }
            }
        }
    """))

    # Create a source file
    src_file = project / "Calculator.cs"
    src_file.write_text(dedent("""\
        namespace MyApp
        {
            public class Calculator
            {
                public int Add(int a, int b) => a + b;
            }
        }
    """))

    return project


@pytest.fixture
def fake_extractor(tmp_path: Path) -> Path:
    """Create a fake extractor CLI that returns valid JSON."""
    extractor_dir = tmp_path / "extractor"
    extractor_dir.mkdir()
    extractor_path = extractor_dir / "fake-extractor"

    # Write a Python script that acts as the fake extractor
    extractor_script = dedent("""\
        #!{python}
        import sys
        import json
        from pathlib import Path

        # Parse arguments
        args = sys.argv[1:]
        seeds = []
        root = Path.cwd()

        i = 0
        while i < len(args):
            if args[i] == "--seed" and i + 1 < len(args):
                seeds.append(Path(args[i + 1]))
                i += 2
            elif args[i] == "--root" and i + 1 < len(args):
                root = Path(args[i + 1])
                i += 2
            else:
                i += 1

        # Generate fake extraction result
        result = {{
            "files": [],
            "project": {{
                "targetFramework": "net8.0",
                "properties": {{
                    "Nullable": "enable",
                    "ImplicitUsings": "enable"
                }},
                "packageReferences": [
                    {{"name": "NUnit", "version": "3.14.0"}},
                    {{"name": "Microsoft.NET.Test.Sdk", "version": "17.8.0"}}
                ],
                "frameworkReferences": [],
                "compileIncludes": []
            }},
            "projectFiles": {{}},
            "diagnostics": [],
            "runCommands": [
                {{"command": ["dotnet", "restore"], "cwd": None, "description": "Restore NuGet packages"}},
                {{"command": ["dotnet", "test", "--no-build"], "cwd": None, "description": "Run tests"}}
            ]
        }}

        # Add seed files to the result
        for seed in seeds:
            if seed.exists():
                rel_path = seed.relative_to(root)
                result["files"].append({{
                    "sourcePath": str(seed),
                    "bundlePath": str(rel_path),
                    "reason": "seed file"
                }})
                result["project"]["compileIncludes"].append(str(rel_path))

        # Output JSON
        print(json.dumps(result, indent=2))
    """).format(python=sys.executable)

    extractor_path.write_text(extractor_script)
    extractor_path.chmod(0o755)

    return extractor_path


@pytest.fixture
def failing_extractor(tmp_path: Path) -> Path:
    """Create a fake extractor that returns error diagnostics."""
    extractor_dir = tmp_path / "extractor"
    extractor_dir.mkdir()
    extractor_path = extractor_dir / "failing-extractor"

    extractor_script = dedent("""\
        #!{python}
        import sys
        import json

        result = {{
            "files": [],
            "project": {{
                "targetFramework": "net8.0",
                "properties": {{}},
                "packageReferences": [],
                "frameworkReferences": [],
                "compileIncludes": []
            }},
            "projectFiles": {{}},
            "diagnostics": [
                {{
                    "severity": "error",
                    "message": "Cannot extract required dependency: missing source generator",
                    "code": "MissingSourceGenerator"
                }}
            ],
            "runCommands": []
        }}

        print(json.dumps(result, indent=2))
        sys.exit(0)  # Exit success but with error diagnostics
    """).format(python=sys.executable)

    extractor_path.write_text(extractor_script)
    extractor_path.chmod(0o755)

    return extractor_path


@pytest.fixture
def invalid_json_extractor(tmp_path: Path) -> Path:
    """Create a fake extractor that returns invalid JSON."""
    extractor_dir = tmp_path / "extractor"
    extractor_dir.mkdir()
    extractor_path = extractor_dir / "invalid-json-extractor"

    extractor_path.write_text("#!/bin/sh\necho 'not valid json'")
    extractor_path.chmod(0o755)

    return extractor_path


def test_csharp_adapter_with_fake_extractor(csharp_project: Path, fake_extractor: Path, tmp_path: Path) -> None:
    """Test C# adapter with a fake extractor that returns valid data."""
    adapter = CsharpAdapter(extractor=fake_extractor)
    output_dir = tmp_path / "bundle-output"

    request = BundleRequest(
        seeds=[csharp_project / "SimpleTest.cs"],
        project_root=csharp_project,
        output_dir=output_dir,
        language="csharp",
        config={},
    )

    result = adapter.bundle(request)

    assert result.success, f"Errors: {[e.message for e in result.errors]}"
    assert result.output_dir == output_dir
    assert result.manifest.language == "csharp"
    assert "SimpleTest.cs" in result.manifest.seeds
    assert len(result.manifest.files) > 0
    assert "TestProject.csproj" in result.manifest.project_files
    assert len(result.manifest.run_commands) > 0
    assert result.manifest.dependencies["targetFramework"] == "net8.0"
    assert result.manifest.dependencies["packages"] == 2

    # Check that files were copied
    for file_path in result.manifest.files:
        assert (output_dir / file_path).exists()

    # Check that .csproj was generated
    csproj_path = output_dir / "TestProject.csproj"
    assert csproj_path.exists()
    csproj_content = csproj_path.read_text()
    assert "<TargetFramework>net8.0</TargetFramework>" in csproj_content
    assert "<Nullable>enable</Nullable>" in csproj_content
    assert "<ImplicitUsings>enable</ImplicitUsings>" in csproj_content

    # Check that manifest was written
    manifest_path = output_dir / "pyx-manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["language"] == "csharp"


def test_csharp_adapter_with_multiple_seeds(csharp_project: Path, fake_extractor: Path, tmp_path: Path) -> None:
    """Test C# adapter with multiple seed files."""
    adapter = CsharpAdapter(extractor=fake_extractor)
    output_dir = tmp_path / "bundle-output"

    request = BundleRequest(
        seeds=[
            csharp_project / "SimpleTest.cs",
            csharp_project / "Calculator.cs",
        ],
        project_root=csharp_project,
        output_dir=output_dir,
        language="csharp",
        config={},
    )

    result = adapter.bundle(request)

    assert result.success
    assert len(result.manifest.seeds) == 2
    assert len(result.manifest.files) == 2


def test_csharp_adapter_fails_on_error_diagnostics(csharp_project: Path, failing_extractor: Path, tmp_path: Path) -> None:
    """Test that C# adapter fails when extractor returns error diagnostics."""
    adapter = CsharpAdapter(extractor=failing_extractor)
    output_dir = tmp_path / "bundle-output"

    request = BundleRequest(
        seeds=[csharp_project / "SimpleTest.cs"],
        project_root=csharp_project,
        output_dir=output_dir,
        language="csharp",
        config={},
    )

    result = adapter.bundle(request)

    assert not result.success
    assert len(result.errors) > 0
    assert any("MissingSourceGenerator" in e.code for e in result.errors)
    assert any("missing source generator" in e.message.lower() for e in result.errors)


def test_csharp_adapter_fails_on_missing_extractor(csharp_project: Path, tmp_path: Path) -> None:
    """Test that C# adapter fails gracefully when extractor is not found."""
    non_existent_extractor = tmp_path / "non-existent-extractor"
    adapter = CsharpAdapter(extractor=non_existent_extractor)
    output_dir = tmp_path / "bundle-output"

    request = BundleRequest(
        seeds=[csharp_project / "SimpleTest.cs"],
        project_root=csharp_project,
        output_dir=output_dir,
        language="csharp",
        config={},
    )

    result = adapter.bundle(request)

    assert not result.success
    assert len(result.errors) > 0
    assert any("ExtractorNotFound" in e.code for e in result.errors)


def test_csharp_adapter_fails_on_invalid_json(csharp_project: Path, invalid_json_extractor: Path, tmp_path: Path) -> None:
    """Test that C# adapter fails gracefully when extractor returns invalid JSON."""
    adapter = CsharpAdapter(extractor=invalid_json_extractor)
    output_dir = tmp_path / "bundle-output"

    request = BundleRequest(
        seeds=[csharp_project / "SimpleTest.cs"],
        project_root=csharp_project,
        output_dir=output_dir,
        language="csharp",
        config={},
    )

    result = adapter.bundle(request)

    assert not result.success
    assert len(result.errors) > 0
    assert any("InvalidExtractorOutput" in e.code for e in result.errors)


def test_csharp_adapter_default_extractor_path(csharp_project: Path, tmp_path: Path) -> None:
    """Test that C# adapter uses default extractor path when none provided."""
    adapter = CsharpAdapter()  # No extractor path provided
    output_dir = tmp_path / "bundle-output"

    request = BundleRequest(
        seeds=[csharp_project / "SimpleTest.cs"],
        project_root=csharp_project,
        output_dir=output_dir,
        language="csharp",
        config={},
    )

    result = adapter.bundle(request)

    # Should fail because default extractor path doesn't exist
    assert not result.success
    assert any("ExtractorNotFound" in e.code for e in result.errors)


def test_csharp_adapter_with_additional_project_files(csharp_project: Path, tmp_path: Path) -> None:
    """Test C# adapter when extractor returns additional project files."""
    # Create a fake extractor that returns additional project files
    extractor_dir = tmp_path / "extractor"
    extractor_dir.mkdir()
    extractor_path = extractor_dir / "fake-extractor-with-files"

    extractor_script = dedent("""\
        #!{python}
        import sys
        import json
        from pathlib import Path

        args = sys.argv[1:]
        root = Path.cwd()

        result = {{
            "files": [
                {{
                    "sourcePath": str(root / "SimpleTest.cs"),
                    "bundlePath": "SimpleTest.cs",
                    "reason": "seed file"
                }}
            ],
            "project": {{
                "targetFramework": "net8.0",
                "properties": {{}},
                "packageReferences": [],
                "frameworkReferences": [],
                "compileIncludes": ["SimpleTest.cs"]
            }},
            "projectFiles": {{
                "Directory.Build.props": "<Project><PropertyGroup><TreatWarningsAsErrors>true</TreatWarningsAsErrors></PropertyGroup></Project>",
                "global.json": '{{"sdk": {{"version": "8.0.0"}}}}'
            }},
            "diagnostics": [],
            "runCommands": []
        }}

        print(json.dumps(result, indent=2))
    """).format(python=sys.executable)

    extractor_path.write_text(extractor_script)
    extractor_path.chmod(0o755)

    adapter = CsharpAdapter(extractor=extractor_path)
    output_dir = tmp_path / "bundle-output"

    request = BundleRequest(
        seeds=[csharp_project / "SimpleTest.cs"],
        project_root=csharp_project,
        output_dir=output_dir,
        language="csharp",
        config={},
    )

    result = adapter.bundle(request)

    assert result.success
    assert "Directory.Build.props" in result.manifest.project_files
    assert "global.json" in result.manifest.project_files

    # Check that additional files were written
    assert (output_dir / "Directory.Build.props").exists()
    assert (output_dir / "global.json").exists()


def test_csharp_adapter_with_warning_diagnostics(csharp_project: Path, tmp_path: Path) -> None:
    """Test that C# adapter succeeds with warning diagnostics."""
    # Create a fake extractor that returns warning diagnostics
    extractor_dir = tmp_path / "extractor"
    extractor_dir.mkdir()
    extractor_path = extractor_dir / "fake-extractor-with-warnings"

    extractor_script = dedent("""\
        #!{python}
        import sys
        import json
        from pathlib import Path

        args = sys.argv[1:]
        root = Path.cwd()

        result = {{
            "files": [
                {{
                    "sourcePath": str(root / "SimpleTest.cs"),
                    "bundlePath": "SimpleTest.cs",
                    "reason": "seed file"
                }}
            ],
            "project": {{
                "targetFramework": "net8.0",
                "properties": {{}},
                "packageReferences": [],
                "frameworkReferences": [],
                "compileIncludes": ["SimpleTest.cs"]
            }},
            "projectFiles": {{}},
            "diagnostics": [
                {{
                    "severity": "warning",
                    "message": "Some optional dependency could not be resolved",
                    "code": "OptionalDependencyMissing"
                }}
            ],
            "runCommands": []
        }}

        print(json.dumps(result, indent=2))
    """).format(python=sys.executable)

    extractor_path.write_text(extractor_script)
    extractor_path.chmod(0o755)

    adapter = CsharpAdapter(extractor=extractor_path)
    output_dir = tmp_path / "bundle-output"

    request = BundleRequest(
        seeds=[csharp_project / "SimpleTest.cs"],
        project_root=csharp_project,
        output_dir=output_dir,
        language="csharp",
        config={},
    )

    result = adapter.bundle(request)

    # Should succeed despite warnings
    assert result.success
    assert len(result.manifest.diagnostics) > 0
    # Check that warning is in manifest but not in errors
    warning_diags = [d for d in result.manifest.diagnostics if d.severity == DiagnosticSeverity.WARNING]
    assert len(warning_diags) > 0
    assert len(result.errors) == 0  # No error-level diagnostics


def test_csharp_adapter_with_invalid_file_entries(csharp_project: Path, tmp_path: Path) -> None:
    """Test that C# adapter handles invalid file entries gracefully."""
    # Create a fake extractor that returns invalid file entries
    extractor_dir = tmp_path / "extractor"
    extractor_dir.mkdir()
    extractor_path = extractor_dir / "fake-extractor-invalid-files"

    extractor_script = dedent("""\
        #!{python}
        import sys
        import json
        from pathlib import Path

        args = sys.argv[1:]
        root = Path.cwd()

        result = {{
            "files": [
                {{
                    "sourcePath": str(root / "SimpleTest.cs"),
                    "bundlePath": "SimpleTest.cs",
                    "reason": "seed file"
                }},
                {{
                    "sourcePath": "",  # Missing source path
                    "bundlePath": "Missing.cs",
                    "reason": "invalid entry"
                }},
                {{
                    "sourcePath": str(root / "NonExistent.cs"),
                    "bundlePath": "NonExistent.cs",
                    "reason": "file does not exist"
                }}
            ],
            "project": {{
                "targetFramework": "net8.0",
                "properties": {{}},
                "packageReferences": [],
                "frameworkReferences": [],
                "compileIncludes": ["SimpleTest.cs"]
            }},
            "projectFiles": {{}},
            "diagnostics": [],
            "runCommands": []
        }}

        print(json.dumps(result, indent=2))
    """).format(python=sys.executable)

    extractor_path.write_text(extractor_script)
    extractor_path.chmod(0o755)

    adapter = CsharpAdapter(extractor=extractor_path)
    output_dir = tmp_path / "bundle-output"

    request = BundleRequest(
        seeds=[csharp_project / "SimpleTest.cs"],
        project_root=csharp_project,
        output_dir=output_dir,
        language="csharp",
        config={},
    )

    result = adapter.bundle(request)

    # Should succeed but with warnings
    assert result.success
    assert len(result.manifest.diagnostics) > 0
    # Only the valid file should be in the manifest
    assert len(result.manifest.files) == 1
    assert "SimpleTest.cs" in result.manifest.files


def test_csharp_adapter_language_property(csharp_project: Path, fake_extractor: Path) -> None:
    """Test that C# adapter reports correct language property."""
    adapter = CsharpAdapter(extractor=fake_extractor)

    assert adapter.language == "csharp"
    assert adapter.file_extensions == [".cs"]


def test_csharp_adapter_csproj_generation(csharp_project: Path, tmp_path: Path) -> None:
    """Test that .csproj generation handles various project metadata."""
    # Create a fake extractor with rich project metadata
    extractor_dir = tmp_path / "extractor"
    extractor_dir.mkdir()
    extractor_path = extractor_dir / "fake-extractor-rich-metadata"

    extractor_script = dedent("""\
        #!{python}
        import sys
        import json
        from pathlib import Path

        args = sys.argv[1:]
        root = Path.cwd()

        result = {{
            "files": [
                {{
                    "sourcePath": str(root / "SimpleTest.cs"),
                    "bundlePath": "SimpleTest.cs",
                    "reason": "seed file"
                }}
            ],
            "project": {{
                "targetFramework": "net9.0",
                "properties": {{
                    "Nullable": "disable",
                    "ImplicitUsings": "disable",
                    "LangVersion": "latest",
                    "AllowUnsafeBlocks": "true"
                }},
                "packageReferences": [
                    {{"name": "NUnit", "version": "3.14.0"}},
                    {{"name": "Microsoft.NET.Test.Sdk", "version": "17.8.0"}},
                    {{"name": "Moq", "version": "4.20.0"}}
                ],
                "frameworkReferences": [
                    {{"name": "Microsoft.AspNetCore.App"}}
                ],
                "compileIncludes": ["SimpleTest.cs"]
            }},
            "projectFiles": {{}},
            "diagnostics": [],
            "runCommands": []
        }}

        print(json.dumps(result, indent=2))
    """).format(python=sys.executable)

    extractor_path.write_text(extractor_script)
    extractor_path.chmod(0o755)

    adapter = CsharpAdapter(extractor=extractor_path)
    output_dir = tmp_path / "bundle-output"

    request = BundleRequest(
        seeds=[csharp_project / "SimpleTest.cs"],
        project_root=csharp_project,
        output_dir=output_dir,
        language="csharp",
        config={},
    )

    result = adapter.bundle(request)

    assert result.success
    csproj_path = output_dir / "TestProject.csproj"
    csproj_content = csproj_path.read_text()

    # Check target framework
    assert "<TargetFramework>net9.0</TargetFramework>" in csproj_content

    # Check properties
    assert "<Nullable>disable</Nullable>" in csproj_content
    assert "<ImplicitUsings>disable</ImplicitUsings>" in csproj_content
    assert "<LangVersion>latest</LangVersion>" in csproj_content
    assert "<AllowUnsafeBlocks>true</AllowUnsafeBlocks>" in csproj_content

    # Check package references
    assert 'Include="NUnit" Version="3.14.0"' in csproj_content
    assert 'Include="Microsoft.NET.Test.Sdk" Version="17.8.0"' in csproj_content
    assert 'Include="Moq" Version="4.20.0"' in csproj_content

    # Check framework references
    assert 'Include="Microsoft.AspNetCore.App"' in csproj_content

    # Check compile items
    assert '<Compile Include="SimpleTest.cs" />' in csproj_content

    # Check bundle-specific properties
    assert "<EnableDefaultCompileItems>false</EnableDefaultCompileItems>" in csproj_content
    assert "<IsPackable>false</IsPackable>" in csproj_content

    # Verify dependencies in manifest
    assert result.manifest.dependencies["targetFramework"] == "net9.0"
    assert result.manifest.dependencies["packages"] == 3
    assert result.manifest.dependencies["frameworks"] == 1