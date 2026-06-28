"""Tests for bundle verification functionality."""

from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch, MagicMock

import pytest


def run_pyx(args: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run pyx CLI with given args."""
    return subprocess.run(
        [sys.executable, "-m", "pyx.cli"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def dart_project_with_files(tmp_path: Path) -> Path:
    """Create a minimal Dart project with test files."""
    project = tmp_path / "dart-project"
    project.mkdir()

    # Create pubspec.yaml
    (project / "pubspec.yaml").write_text(dedent("""\
        name: test_project
        version: 1.0.0
        publish_to: none

        environment:
          sdk: '>=3.0.0 <4.0.0'

        dependencies:
          flutter:
            sdk: flutter
    """))

    # Create test directory with a test file
    test_dir = project / "test"
    test_dir.mkdir()
    (test_dir / "simple_test.dart").write_text(dedent("""\
        import 'package:flutter_test/flutter_test.dart';

        void main() {
          test('simple test', () {
            expect(1 + 1, equals(2));
          });
        }
    """))

    return project


def test_verify_flag_without_verify_does_not_run_commands(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test that without --verify, bundle creation does not run restore/test commands."""
    output_dir = tmp_path / "bundle-output"
    
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir)],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "✓ Bundled to" in result.stdout
    assert "Verifying bundle..." not in result.stdout


def test_verify_flag_with_verify_runs_commands_and_passes_on_success(dart_project_with_files: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that with --verify, the restore/test command sequence is executed."""
    output_dir = tmp_path / "bundle-output"
    
    # Create fake flutter and echo commands that succeed
    fake_flutter = tmp_path / "flutter"
    fake_flutter.write_text(dedent("""\
        #!/bin/sh
        echo "Fake flutter $*" >&2
        exit 0
    """))
    fake_flutter.chmod(0o755)
    
    # Add the fake flutter to PATH
    env = dict(subprocess.os.environ)
    env["PATH"] = str(tmp_path) + ":" + env.get("PATH", "")
    
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir), "--verify"],
        cwd=dart_project_with_files,
        env=env,
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "✓ Bundled to" in result.stdout
    assert "Verifying bundle..." in result.stdout
    assert "Fake flutter" in result.stderr  # Verify the fake flutter was called


def test_verify_flag_with_verify_fails_on_command_failure(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test that verification failures produce clear errors and a non-zero exit code."""
    output_dir = tmp_path / "bundle-output"
    
    # Create fake flutter command that fails
    fake_flutter = tmp_path / "flutter"
    fake_flutter.write_text(dedent("""\
        #!/bin/sh
        echo "Fake flutter error" >&2
        exit 1
    """))
    fake_flutter.chmod(0o755)
    
    # Add the fake flutter to PATH
    env = dict(subprocess.os.environ)
    env["PATH"] = str(tmp_path) + ":" + env.get("PATH", "")
    
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir), "--verify"],
        cwd=dart_project_with_files,
        env=env,
    )

    assert result.returncode == 1, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "✓ Bundled to" in result.stdout
    assert "Verifying bundle..." in result.stdout
    assert "verification failed" in result.stderr.lower()


def test_verify_flag_with_verify_fails_on_command_not_found(dart_project_with_files: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that verification failures due to missing command produce clear errors and a non-zero exit code."""
    output_dir = tmp_path / "bundle-output"
    
    # Remove flutter from PATH to simulate missing command
    env = dict(subprocess.os.environ)
    env["PATH"] = str(tmp_path)  # Only tmp_path, which has no flutter
    
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir), "--verify"],
        cwd=dart_project_with_files,
        env=env,
    )

    assert result.returncode == 1, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "✓ Bundled to" in result.stdout
    assert "Verifying bundle..." in result.stdout
    assert "verification command not found" in result.stderr.lower()


def test_verify_flag_with_verify_runs_in_correct_working_directory(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test that verification commands run in the correct working directory (bundle output)."""
    output_dir = tmp_path / "bundle-output"
    
    # Create fake flutter that prints the current working directory
    fake_flutter = tmp_path / "flutter"
    fake_flutter.write_text(dedent(f"""\
        #!/bin/sh
        echo "CWD: $(pwd)" >&2
        exit 0
    """))
    fake_flutter.chmod(0o755)
    
    # Add the fake flutter to PATH
    env = dict(subprocess.os.environ)
    env["PATH"] = str(tmp_path) + ":" + env.get("PATH", "")
    
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir), "--verify"],
        cwd=dart_project_with_files,
        env=env,
    )

    assert result.returncode == 0
    
    # Check that the working directory was the output directory
    assert str(output_dir) in result.stderr, f"Expected {output_dir} in stderr: {result.stderr}"


def test_verify_flag_manifest_contains_run_commands(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test that the manifest contains the expected run commands."""
    output_dir = tmp_path / "bundle-output"
    
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir)],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 0
    
    # Read and check the manifest
    manifest_path = output_dir / "pyx-manifest.json"
    assert manifest_path.exists()
    
    manifest = json.loads(manifest_path.read_text())
    assert "run_commands" in manifest
    assert len(manifest["run_commands"]) > 0
    
    # Check that run commands have the expected structure
    for cmd in manifest["run_commands"]:
        assert "command" in cmd
        assert isinstance(cmd["command"], list)
        assert "cwd" in cmd
        assert "description" in cmd


def test_verify_flag_csharp_with_fake_extractor(tmp_path: Path) -> None:
    """Test that C# verification uses the generated runnable project command from the extractor result."""
    project = tmp_path / "csharp-project"
    project.mkdir()
    
    # Create a fake extractor that returns structured output with run commands
    extractor_dir = project / "vendor" / "chsarp-class-context" / "bin"
    extractor_dir.mkdir(parents=True)
    extractor_path = extractor_dir / "chsarp-class-context"
    
    # Create a fake extractor script that outputs JSON
    extractor_output = json.dumps({
        "files": [
            {
                "sourcePath": str(project / "Tests" / "SimpleTest.cs"),
                "bundlePath": "Tests/SimpleTest.cs"
            }
        ],
        "project": {
            "targetFramework": "net8.0",
            "packageReferences": [],
            "frameworkReferences": []
        },
        "diagnostics": [],
        "runCommands": [
            {
                "command": ["dotnet", "restore"],
                "cwd": "",
                "description": "Restore NuGet packages"
            },
            {
                "command": ["dotnet", "test", "--no-build"],
                "cwd": "",
                "description": "Run tests"
            }
        ]
    })
    
    extractor_path.write_text(dedent(f"""\
        #!/usr/bin/env python3
        import json
        print({json.dumps(extractor_output)})
    """))
    extractor_path.chmod(0o755)
    
    # Create fake dotnet command that succeeds
    fake_dotnet = tmp_path / "dotnet"
    fake_dotnet.write_text(dedent("""\
        #!/bin/sh
        echo "Fake dotnet $*" >&2
        exit 0
    """))
    fake_dotnet.chmod(0o755)
    
    # Create a test file
    test_dir = project / "Tests"
    test_dir.mkdir()
    (test_dir / "SimpleTest.cs").write_text(dedent("""\
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
    
    output_dir = tmp_path / "bundle-output"
    
    # Test with --verify
    env = dict(subprocess.os.environ)
    env["PATH"] = str(tmp_path) + ":" + env.get("PATH", "")
    
    result = run_pyx(
        ["bundle", "Tests/SimpleTest.cs", "-o", str(output_dir), "--language", "csharp", "--verify"],
        cwd=project,
        env=env,
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Verifying bundle..." in result.stdout
    assert "Fake dotnet" in result.stderr


def test_verify_flag_csharp_default_commands_when_not_provided(tmp_path: Path) -> None:
    """Test that C# verification uses default commands when extractor doesn't provide them."""
    project = tmp_path / "csharp-project"
    project.mkdir()
    
    # Create a fake extractor that returns structured output WITHOUT run commands
    extractor_dir = project / "vendor" / "chsarp-class-context" / "bin"
    extractor_dir.mkdir(parents=True)
    extractor_path = extractor_dir / "chsarp-class-context"
    
    extractor_output = json.dumps({
        "files": [
            {
                "sourcePath": str(project / "Tests" / "SimpleTest.cs"),
                "bundlePath": "Tests/SimpleTest.cs"
            }
        ],
        "project": {
            "targetFramework": "net8.0",
            "packageReferences": [],
            "frameworkReferences": []
        },
        "diagnostics": []
        # No runCommands field
    })
    
    extractor_path.write_text(dedent(f"""\
        #!/usr/bin/env python3
        import json
        print({json.dumps(extractor_output)})
    """))
    extractor_path.chmod(0o755)
    
    # Create fake dotnet command that succeeds
    fake_dotnet = tmp_path / "dotnet"
    fake_dotnet.write_text(dedent("""\
        #!/bin/sh
        echo "Fake dotnet $*" >&2
        exit 0
    """))
    fake_dotnet.chmod(0o755)
    
    # Create a test file
    test_dir = project / "Tests"
    test_dir.mkdir()
    (test_dir / "SimpleTest.cs").write_text(dedent("""\
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
    
    output_dir = tmp_path / "bundle-output"
    
    # Test with --verify
    env = dict(subprocess.os.environ)
    env["PATH"] = str(tmp_path) + ":" + env.get("PATH", "")
    
    result = run_pyx(
        ["bundle", "Tests/SimpleTest.cs", "-o", str(output_dir), "--language", "csharp", "--verify"],
        cwd=project,
        env=env,
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Verifying bundle..." in result.stdout
    assert "Fake dotnet" in result.stderr