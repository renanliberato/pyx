"""pyx CLI entry point."""

from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path
from typing import Protocol, runtime_checkable

from .domain import BundleRequest, LanguageAdapter, RunCommand, Diagnostic, DiagnosticSeverity
from .config import PyxConfig
from .adapters import DartAdapter, CsharpAdapter


@runtime_checkable
class HasLanguageAdapter(Protocol):
    """Protocol for modules that have a language adapter."""
    def get_adapter(self, language: str) -> LanguageAdapter | None: ...


def _detect_project_root(start: Path) -> Path:
    """Detect project root by looking for pubspec.yaml."""
    for p in [start, *start.parents]:
        if (p / "pubspec.yaml").exists():
            return p
    return start


def _detect_language(files: list[Path]) -> str | None:
    """Detect language from file extensions.

    Returns:
        The detected language ('dart' or 'csharp'), or None if no recognized extension found.

    Raises:
        ValueError: If mixed Dart/C# inputs are detected.
    """
    # Collect extensions from files and directory contents
    extensions: set[str] = set()

    for f in files:
        if f.is_file() and f.suffix:
            extensions.add(f.suffix.lower())
        elif f.is_dir():
            # Check directory contents for recognized extensions
            for ext in [".dart", ".cs"]:
                if list(f.rglob(f"*{ext}")):
                    extensions.add(ext)

    # Check for mixed languages
    has_dart = ".dart" in extensions
    has_csharp = ".cs" in extensions

    if has_dart and has_csharp:
        raise ValueError(
            "Mixed Dart/C# inputs are not supported in a single bundle. "
            "Please bundle Dart and C# files separately."
        )

    if has_dart:
        return "dart"
    if has_csharp:
        return "csharp"

    return None


def _check_unsupported_extensions(files: list[Path], language: str) -> None:
    """Check for unsupported file extensions.

    Raises:
        ValueError: If unsupported extensions are found.
    """
    supported_exts = {".dart"} if language == "dart" else {".cs"}
    unsupported: set[str] = set()

    for f in files:
        if f.is_file() and f.suffix:
            ext = f.suffix.lower()
            if ext not in supported_exts:
                unsupported.add(ext)

    if unsupported:
        ext_list = ", ".join(sorted(unsupported))
        guidance = (
            "Dart files should have .dart extension. "
            if language == "dart"
            else "C# files should have .cs extension. "
        )
        raise ValueError(
            f"Unsupported file extension(s) for {language} bundle: {ext_list}. "
            f"{guidance}"
        )


def _get_adapter(language: str, cfg: PyxConfig) -> LanguageAdapter:
    """Get the adapter for a given language."""
    if language == "dart":
        return DartAdapter(
            pub_cache=cfg.adapters.dart.pub_cache,
            redact_packages=cfg.adapters.dart.redact_packages,
        )
    elif language == "csharp":
        return CsharpAdapter(
            extractor=cfg.adapters.csharp.extractor,
        )
    raise ValueError(f"Unsupported language: {language}")


def _discover_seeds(files: list[Path], language: str) -> list[Path]:
    """Discover seed files from input paths.

    For directories, discover all files of the matching language.
    """
    seeds: list[Path] = []
    for f in files:
        p = f.resolve()
        if p.is_dir():
            if language == "dart":
                seeds.extend(p.rglob("*.dart"))
            elif language == "csharp":
                seeds.extend(p.rglob("*.cs"))
        elif p.exists():
            seeds.append(p)
    return seeds


def _format_diagnostics(diagnostics: list[Diagnostic]) -> str:
    """Format diagnostics for display."""
    if not diagnostics:
        return ""
    lines = []
    for diag in diagnostics:
        prefix = {
            DiagnosticSeverity.INFO: "ℹ",
            DiagnosticSeverity.WARNING: "⚠",
            DiagnosticSeverity.ERROR: "✗",
        }[diag.severity]
        lines.append(f"{prefix} {diag.message}")
    return "\n".join(lines)


def _format_run_commands(commands: list[RunCommand]) -> str:
    """Format run commands for display."""
    if not commands:
        return ""
    lines = []
    for i, cmd in enumerate(commands, 1):
        cmd_str = " ".join(cmd.command)
        lines.append(f"{i}. {cmd.description or 'Run command'}: {cmd_str}")
    return "\n".join(lines)


def cmd_bundle(args: argparse.Namespace) -> int:
    """Handle the bundle command."""
    root = Path(args.project_root).resolve() if args.project_root \
        else _detect_project_root(Path.cwd())

    cfg = PyxConfig.load(root)
    if args.output:
        cfg.output_dir = Path(args.output).resolve()
    elif not cfg.output_dir.is_absolute():
        cfg.output_dir = root / cfg.output_dir

    # Resolve input paths
    input_paths: list[Path] = []
    for f in args.files:
        p = Path(f).resolve()
        if not p.exists():
            print(f"pyx: not found: {f}", file=sys.stderr)
            return 1
        input_paths.append(p)

    # Detect or select language
    language = args.language if args.language != "auto" else cfg.language
    if language == "auto":
        try:
            detected = _detect_language(input_paths)
            if not detected:
                print(
                    "pyx: could not detect language from inputs. "
                    "Supported extensions: .dart (Dart), .cs (C#). "
                    "Use --language dart|csharp to specify explicitly.",
                    file=sys.stderr,
                )
                return 1
            language = detected
        except ValueError as e:
            print(f"pyx: {e}", file=sys.stderr)
            return 1
    else:
        # For explicit language, check for mixed inputs
        try:
            _detect_language(input_paths)
        except ValueError as e:
            print(f"pyx: {e}", file=sys.stderr)
            return 1

    # Check for unsupported extensions
    try:
        _check_unsupported_extensions(input_paths, language)
    except ValueError as e:
        print(f"pyx: {e}", file=sys.stderr)
        return 1

    # Discover seeds
    seeds = _discover_seeds(input_paths, language)
    if not seeds:
        print(f"pyx: no {language} files found in the given paths", file=sys.stderr)
        return 1

    # Get adapter and create bundle
    try:
        adapter = _get_adapter(language, cfg)
    except ValueError as e:
        print(f"pyx: {e}", file=sys.stderr)
        return 1

    request = BundleRequest(
        seeds=seeds,
        project_root=root,
        output_dir=cfg.output_dir,
        language=language,
        config={},
    )

    result = adapter.bundle(request)

    # Handle errors
    if not result.success:
        print("pyx: bundle failed", file=sys.stderr)
        if result.errors:
            print(_format_diagnostics(result.errors), file=sys.stderr)
        return 1

    # Print summary
    print(f"✓ Bundled to {result.output_dir}")
    print(f"  language    : {result.manifest.language}")
    print(f"  seeds       : {len(result.manifest.seeds)}")
    print(f"  files       : {len(result.manifest.files)}")
    print(f"  project files: {len(result.manifest.project_files)}")

    # Print diagnostics if any
    if result.manifest.diagnostics:
        diag_text = _format_diagnostics([
            Diagnostic(d["severity"], d["message"], d.get("code"))
            for d in result.manifest.diagnostics
        ])
        if diag_text:
            print(f"\nDiagnostics:\n{diag_text}")

    # Print run commands
    if result.manifest.run_commands:
        print(f"\nRun commands:")
        for cmd in result.manifest.run_commands:
            cmd_str = " ".join(cmd.command)
            print(f"  - {cmd.description or 'Run command'}: {cmd_str}")

    # Run verification if requested
    if args.verify:
        print("\nVerifying bundle...")
        for cmd in result.manifest.run_commands:
            cmd_list = cmd.command
            cwd = result.output_dir / cmd.cwd if cmd.cwd else result.output_dir
            try:
                subprocess.run(cmd_list, cwd=cwd, check=True)
            except subprocess.CalledProcessError as e:
                print(f"pyx: verification failed: {' '.join(cmd_list)}", file=sys.stderr)
                return 1
            except FileNotFoundError as e:
                print(f"pyx: verification command not found: {cmd_list[0]}", file=sys.stderr)
                return 1

    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Handle the init command."""
    root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    dest = root / ".pyx.yaml"
    if dest.exists() and not args.force:
        print(f"pyx: {dest} already exists. Use --force to overwrite.")
        return 1
    dest.write_text("""\
# pyx configuration — https://github.com/renan/pyx

# Where to write bundles (relative to project root)
output_dir: tmp/pyx-bundle

# Default language selection for pyx bundle. Usually auto.
language: auto # auto | dart | csharp

# Adapter-specific settings
adapters:
  dart:
    # Pub cache root used when resolving git dependencies.
    pub_cache: ~/.pub-cache

    # Package names to hide from logs / generated public metadata.
    redact_packages: []
    #  - my_internal_sdk

    # Extra packages to force-bundle from source.
    bundle_from_source: []

  csharp:
    # Path to the chsarp-class-context submodule CLI.
    extractor: vendor/chsarp-class-context/bin/chsarp-class-context
""")
    print(f"✓ Created {dest}")
    return 0


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="pyx",
        description="Bundle test files with their transitive deps — no repo credentials needed.",
    )
    parser.add_argument("--project-root", metavar="DIR",
                        help="Project root (default: nearest pubspec.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)

    # pyx bundle
    p_bundle = sub.add_parser("bundle", help="Create a minimal bundle from test files")
    p_bundle.add_argument("files", nargs="+", metavar="FILE")
    p_bundle.add_argument("-o", "--output", metavar="DIR",
                          help="Output directory (overrides config)")
    p_bundle.add_argument("--language", metavar="LANG", choices=["auto", "dart", "csharp"],
                          default="auto",
                          help="Language (default: auto)")
    p_bundle.add_argument("--verify", action="store_true",
                          help="Run verification commands after bundling")
    p_bundle.set_defaults(func=cmd_bundle)

    # pyx init
    p_init = sub.add_parser("init", help="Create a .pyx.yaml config in the project")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()