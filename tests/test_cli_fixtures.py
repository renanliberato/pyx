"""CLI fixture tests for pyx bundle command."""

from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture
def dart_fixture_project(tmp_path: Path) -> Path:
    """Create a minimal Dart fixture project."""
    fixture_dir = Path(__file__).parent / "fixtures" / "dart-project"
    project = tmp_path / "dart-project"
    project.mkdir()

    # Copy pubspec.yaml
    (project / "pubspec.yaml").write_text((fixture_dir / "pubspec.yaml").read_text())

    # Create test directory
    test_dir = project / "test"
    test_dir.mkdir()
    (test_dir / "simple_test.dart").write_text((fixture_dir / "test" / "simple_test.dart").read_text())
    (test_dir / "utils_test.dart").write_text((fixture_dir / "test" / "utils_test.dart").read_text())

    # Create lib directory
    lib_dir = project / "lib"
    lib_dir.mkdir()
    (lib_dir / "utils.dart").write_text((fixture_dir / "lib" / "utils.dart").read_text())

    return project


def run_pyx(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run pyx CLI with given args."""
    return subprocess.run(
        [sys.executable, "-m", "pyx.cli"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_bundle_dart_single_file(dart_fixture_project: Path, tmp_path: Path) -> None:
    """Test bundling a single Dart test file."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir)],
        cwd=dart_fixture_project,
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "✓ Bundled to" in result.stdout
    assert output_dir.exists()

    # Check manifest
    manifest_path = output_dir / "pyx-manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text())
    assert manifest["language"] == "dart"
    assert "test/simple_test.dart" in manifest["seeds"]
    assert len(manifest["files"]) > 0
    assert len(manifest["project_files"]) > 0
    assert "pubspec.yaml" in manifest["project_files"]
    assert len(manifest["run_commands"]) > 0


def test_bundle_dart_auto_detect_language(dart_fixture_project: Path, tmp_path: Path) -> None:
    """Test auto-detection of Dart language from file extension."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir)],
        cwd=dart_fixture_project,
    )

    assert result.returncode == 0
    assert "language    : dart" in result.stdout


def test_bundle_dart_explicit_language(dart_fixture_project: Path, tmp_path: Path) -> None:
    """Test explicit language selection for Dart."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir), "--language", "dart"],
        cwd=dart_fixture_project,
    )

    assert result.returncode == 0
    assert "language    : dart" in result.stdout


def test_bundle_dart_with_transitive_deps(dart_fixture_project: Path, tmp_path: Path) -> None:
    """Test that transitive imports are bundled."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "test/utils_test.dart", "-o", str(output_dir)],
        cwd=dart_fixture_project,
    )

    assert result.returncode == 0

    manifest = json.loads((output_dir / "pyx-manifest.json").read_text())
    # Should include the test file and the lib/utils.dart it imports
    file_paths = manifest["files"]
    assert any("utils_test.dart" in p for p in file_paths), f"Files: {file_paths}"
    assert any("utils.dart" in p for p in file_paths), f"Files: {file_paths}"


def test_bundle_dart_creates_clean_pubspec(dart_fixture_project: Path, tmp_path: Path) -> None:
    """Test that a clean pubspec.yaml is generated."""
    output_dir = tmp_path / "bundle-output"
    result = run_pyx(
        ["bundle", "test/simple_test.dart", "-o", str(output_dir)],
        cwd=dart_fixture_project,
    )

    assert result.returncode == 0

    pubspec = (output_dir / "pubspec.yaml").read_text()
    assert "name:" in pubspec
    assert "publish_to: none" in pubspec
    assert "flutter:" in pubspec
    # Should not contain private git URLs or local paths


def test_bundle_dart_nonexistent_file(dart_fixture_project: Path) -> None:
    """Test that bundling a non-existent file fails gracefully."""
    result = run_pyx(
        ["bundle", "test/nonexistent.dart"],
        cwd=dart_fixture_project,
    )

    assert result.returncode == 1
    assert "not found" in result.stderr.lower()


def test_bundle_dart_empty_directory(dart_fixture_project: Path, tmp_path: Path) -> None:
    """Test that bundling an empty directory fails gracefully."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    result = run_pyx(
        ["bundle", str(empty_dir)],
        cwd=dart_fixture_project,
    )

    assert result.returncode == 1
    assert ("no dart files found" in result.stderr.lower() or
            "could not detect language" in result.stderr.lower())


def test_init_creates_config(tmp_path: Path) -> None:
    """Test that pyx init creates a valid config file."""
    result = run_pyx(["init"], cwd=tmp_path)

    assert result.returncode == 0
    assert "Created" in result.stdout

    config_path = tmp_path / ".pyx.yaml"
    assert config_path.exists()

    config = config_path.read_text()
    assert "output_dir:" in config
    assert "language:" in config
    assert "adapters:" in config
    assert "dart:" in config
    assert "csharp:" in config


def test_init_with_force(tmp_path: Path) -> None:
    """Test that pyx init --force overwrites existing config."""
    config_path = tmp_path / ".pyx.yaml"
    config_path.write_text("# old config")

    result = run_pyx(["init", "--force"], cwd=tmp_path)

    assert result.returncode == 0

    config = config_path.read_text()
    assert "# old config" not in config
    assert "adapters:" in config