"""CLI tests for language selection and mixed-input rejection."""

from __future__ import annotations
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest


def run_pyx(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run pyx CLI with given args."""
    return subprocess.run(
        [sys.executable, "-m", "pyx.cli"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
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


@pytest.fixture
def csharp_project_with_files(tmp_path: Path) -> Path:
    """Create a minimal C# project with test files."""
    project = tmp_path / "csharp-project"
    project.mkdir()

    # Create a C# test file
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

    return project


def test_explicit_language_dart(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test explicit language selection for Dart."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir), "--language", "dart"],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 0
    assert "language    : dart" in result.stdout


def test_explicit_language_csharp(csharp_project_with_files: Path, tmp_path: Path) -> None:
    """Test explicit language selection for C# (should fail with clear error)."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "Tests/SimpleTest.cs", "-o", str(output_dir), "--language", "csharp"],
        cwd=csharp_project_with_files,
    )

    # Should fail because C# extractor is not found
    assert result.returncode == 1
    assert "C# extractor not found" in result.stderr


def test_auto_detect_dart(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test auto-detection of Dart language from file extension."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir)],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 0
    assert "language    : dart" in result.stdout


def test_auto_detect_csharp(csharp_project_with_files: Path, tmp_path: Path) -> None:
    """Test auto-detection of C# language from file extension."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "Tests/SimpleTest.cs", "-o", str(output_dir)],
        cwd=csharp_project_with_files,
    )

    # Should fail because C# extractor is not found, but should detect it
    assert result.returncode == 1
    assert "C# extractor not found" in result.stderr


def test_mixed_dart_csharp_files(dart_project_with_files: Path, csharp_project_with_files: Path, tmp_path: Path) -> None:
    """Test that mixed Dart/C# files are rejected."""
    # Copy a C# file to the Dart project
    dart_project_with_files = dart_project_with_files
    (dart_project_with_files / "Tests").mkdir()
    (dart_project_with_files / "Tests" / "MixedTest.cs").write_text("using NUnit.Framework;")

    result = run_pyx(
        ["bundle", "test/simple_test.dart", "Tests/MixedTest.cs"],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 1
    assert "Mixed Dart/C# inputs are not supported" in result.stderr


def test_mixed_dart_csharp_explicit_language(dart_project_with_files: Path, csharp_project_with_files: Path, tmp_path: Path) -> None:
    """Test that mixed Dart/C# files are rejected even with explicit language."""
    # Copy a C# file to the Dart project
    dart_project_with_files = dart_project_with_files
    (dart_project_with_files / "Tests").mkdir()
    (dart_project_with_files / "Tests" / "MixedTest.cs").write_text("using NUnit.Framework;")

    # Even with explicit --language dart, mixed inputs should be rejected
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "Tests/MixedTest.cs", "--language", "dart"],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 1
    assert "Mixed Dart/C# inputs are not supported" in result.stderr


def test_unsupported_extension_dart(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test that unsupported extensions fail with clear guidance for Dart."""
    # Create a file with unsupported extension
    (dart_project_with_files / "test.txt").write_text("not a source file")

    result = run_pyx(
        ["bundle", "test.txt", "--language", "dart"],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 1
    assert "Unsupported file extension" in result.stderr
    assert ".txt" in result.stderr
    assert "Dart files should have .dart extension" in result.stderr


def test_unsupported_extension_csharp(csharp_project_with_files: Path, tmp_path: Path) -> None:
    """Test that unsupported extensions fail with clear guidance for C#."""
    # Create a file with unsupported extension
    (csharp_project_with_files / "test.txt").write_text("not a source file")

    result = run_pyx(
        ["bundle", "test.txt", "--language", "csharp"],
        cwd=csharp_project_with_files,
    )

    assert result.returncode == 1
    assert "Unsupported file extension" in result.stderr
    assert ".txt" in result.stderr
    assert "C# files should have .cs extension" in result.stderr


def test_unsupported_extension_auto(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test that unsupported extensions fail with clear guidance in auto mode."""
    # Create a file with unsupported extension
    (dart_project_with_files / "test.txt").write_text("not a source file")

    result = run_pyx(
        ["bundle", "test.txt"],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 1
    assert "could not detect language from inputs" in result.stderr
    assert "Supported extensions: .dart (Dart), .cs (C#)" in result.stderr


def test_directory_discovery_dart(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test that directory discovery works for Dart files."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "test", "-o", str(output_dir), "--language", "dart"],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 0
    assert "language    : dart" in result.stdout


def test_directory_discovery_csharp(csharp_project_with_files: Path, tmp_path: Path) -> None:
    """Test that directory discovery works for C# files."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "Tests", "-o", str(output_dir), "--language", "csharp"],
        cwd=csharp_project_with_files,
    )

    # Should fail because C# extractor is not found, but should discover the files
    assert result.returncode == 1
    assert "C# extractor not found" in result.stderr


def test_directory_discovery_auto_dart(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test that auto directory discovery works for Dart files."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "test", "-o", str(output_dir)],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 0
    assert "language    : dart" in result.stdout


def test_directory_discovery_auto_csharp(csharp_project_with_files: Path, tmp_path: Path) -> None:
    """Test that auto directory discovery works for C# files."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "Tests", "-o", str(output_dir)],
        cwd=csharp_project_with_files,
    )

    # Should fail because C# extractor is not found, but should discover and detect the files
    assert result.returncode == 1
    assert "C# extractor not found" in result.stderr


def test_mixed_directory_contents(tmp_path: Path) -> None:
    """Test that mixed directory contents (Dart and C#) are rejected."""
    project = tmp_path / "mixed-project"
    project.mkdir()

    # Create both Dart and C# files in the same directory
    (project / "test.dart").write_text("import 'package:flutter_test/flutter_test.dart';")
    (project / "test.cs").write_text("using NUnit.Framework;")

    result = run_pyx(
        ["bundle", "test.dart", "test.cs"],
        cwd=project,
    )

    assert result.returncode == 1
    assert "Mixed Dart/C# inputs are not supported" in result.stderr


def test_empty_directory_with_explicit_language(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test that bundling an empty directory fails with clear message."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    result = run_pyx(
        ["bundle", str(empty_dir), "--language", "dart"],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 1
    assert "no dart files found" in result.stderr.lower()


def test_config_language_selection(dart_project_with_files: Path, tmp_path: Path) -> None:
    """Test that config file language selection works."""
    # Create a config with explicit language
    (dart_project_with_files / ".pyx.yaml").write_text(dedent("""\
        output_dir: tmp/pyx-bundle
        language: dart

        adapters:
          dart:
            pub_cache: ~/.pub-cache
            redact_packages: []
          csharp:
            extractor: vendor/chsarp-class-context/bin/chsarp-class-context
    """))

    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir)],
        cwd=dart_project_with_files,
    )

    assert result.returncode == 0
    assert "language    : dart" in result.stdout