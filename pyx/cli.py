"""pyx CLI entry point."""

from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

from .bundler import bundle
from .config import PyxConfig


def _detect_project_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pubspec.yaml").exists():
            return p
    return start


def cmd_bundle(args: argparse.Namespace) -> int:
    root = Path(args.project_root).resolve() if args.project_root \
        else _detect_project_root(Path.cwd())

    cfg = PyxConfig.load(root)
    if args.output:
        cfg.output_dir = Path(args.output).resolve()
    elif not cfg.output_dir.is_absolute():
        cfg.output_dir = root / cfg.output_dir

    seeds: list[Path] = []
    for f in args.files:
        p = Path(f).resolve()
        if p.is_dir():
            seeds.extend(p.rglob("*.dart"))
        elif p.exists():
            seeds.append(p)
        else:
            print(f"pyx: not found: {f}", file=sys.stderr)
            return 1

    if not seeds:
        print("pyx: no .dart files found in the given paths", file=sys.stderr)
        return 1

    summary = bundle(seeds, root, cfg.output_dir, cfg)

    print(f"✓ {summary['dart_files']} Dart files → {summary['out']}")
    if summary["local_packages"]:
        print(f"  bundled packages : {', '.join(summary['local_packages'])}")
    print(f"  pub.dev deps     : {summary['pub_packages']}")
    print(f"  size             : {summary['size_kb']:.0f} KB")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    dest = root / ".pyx.yaml"
    if dest.exists() and not args.force:
        print(f"pyx: {dest} already exists. Use --force to overwrite.")
        return 1
    dest.write_text("""\
# pyx configuration — https://github.com/renan/pyx

# Where to write bundles (relative to project root)
output_dir: tmp/pyx-bundle

# pub cache root (default: ~/.pub-cache)
# pub_cache: ~/.pub-cache

# Package names to never expose in the generated pubspec.
# Their source is still bundled, but the name is stripped from all output.
# Use this for internal/proprietary packages.
redact_packages: []
#  - my_internal_sdk

# Extra packages to force-bundle from source even if they appear as pub.dev deps.
bundle_from_source: []
""")
    print(f"✓ Created {dest}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pyx",
        description="Bundle Dart/Flutter test files with their transitive deps — no repo credentials needed.",
    )
    parser.add_argument("--project-root", metavar="DIR",
                        help="Project root (default: nearest pubspec.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)

    # pyx bundle
    p_bundle = sub.add_parser("bundle", help="Create a minimal bundle from test files")
    p_bundle.add_argument("files", nargs="+", metavar="TEST_FILE")
    p_bundle.add_argument("-o", "--output", metavar="DIR",
                          help="Output directory (overrides config)")
    p_bundle.set_defaults(func=cmd_bundle)

    # pyx init
    p_init = sub.add_parser("init", help="Create a .pyx.yaml config in the project")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
