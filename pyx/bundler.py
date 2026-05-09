"""Core bundling logic: import graph traversal and file collection."""

from __future__ import annotations
import re
import shutil
from pathlib import Path
from collections import deque

from .pubspec import get_package_name, parse_deps, generate
from .config import PyxConfig


def _parse_imports(file: Path) -> list[str]:
    try:
        content = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    results = []
    # Match full import/export/part statements including multi-line conditional imports
    for stmt_m in re.finditer(
        r"""^(?:import|export|part(?!\s+of))\s+['"][^'"]+['"](?:[^;]|\n)*?;""",
        content, re.MULTILINE,
    ):
        stmt = stmt_m.group(0)
        # Capture every quoted .dart URL (base + all conditional branches)
        results.extend(re.findall(r"""['"]([^'"]+\.dart)['"]""", stmt))
    return results


def _resolve(imp: str, current: Path, root: Path, pkg_name: str,
             local_pkgs: dict) -> Path | None:
    if imp.startswith("dart:"):
        return None
    if imp.startswith(f"package:{pkg_name}/"):
        return root / "lib" / imp[len(f"package:{pkg_name}/"):]
    for name, pkg_path in local_pkgs.items():
        if imp.startswith(f"package:{name}/"):
            return pkg_path / "lib" / imp[len(f"package:{name}/"):]
    if imp.startswith("package:"):
        return None  # pub.dev dep
    return (current.parent / imp).resolve()


def collect(seeds: list[Path], root: Path, local_pkgs: dict,
            pkg_name: str) -> tuple[set[Path], set[str], set[str]]:
    """
    BFS over import graph.
    Returns:
      dart_files       — all transitively needed .dart files
      used_local_pkgs  — local package names (path/git) actually imported
      used_pub_pkgs    — pub.dev package names actually imported
    """
    visited: set[Path] = set()
    queue: deque[Path] = deque(seeds)
    used_local: set[str] = set()
    used_pub: set[str] = set()

    while queue:
        f = queue.popleft()
        if f in visited or not f.exists():
            continue
        visited.add(f)
        for imp in _parse_imports(f):
            if not imp.startswith("package:") or imp.startswith("dart:"):
                pass
            else:
                name = imp.split("/")[0][len("package:"):]
                if name in local_pkgs:
                    used_local.add(name)
                elif name != pkg_name:
                    used_pub.add(name)
            resolved = _resolve(imp, f, root, pkg_name, local_pkgs)
            if resolved and resolved not in visited:
                queue.append(resolved)

    return visited, used_local, used_pub


def bundle(seeds: list[Path], root: Path, out: Path, cfg: PyxConfig) -> dict:
    """
    Build a self-contained bundle at `out`.
    Returns a summary dict with counts and size.
    """
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    path_pkgs, git_pkgs, pub_deps = parse_deps(root, cfg.pub_cache)
    pkg_name = get_package_name(root)
    local_pkgs = {**path_pkgs, **git_pkgs}

    dart_files, used_local, used_pub = collect(seeds, root, local_pkgs, pkg_name)
    used_pkgs = used_local | used_pub

    # Copy dart source files
    copied = 0
    for src in dart_files:
        dst = None
        # Local package files → bundled_packages/<name>/
        for name, pkg_path in local_pkgs.items():
            try:
                rel = src.relative_to(pkg_path)
                dst = out / "bundled_packages" / name / rel
                break
            except ValueError:
                continue
        # Repo files → keep original relative path
        if dst is None:
            try:
                dst = out / src.relative_to(root)
            except ValueError:
                continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    # Copy pubspec.yaml for each bundled local package
    for name in used_local:
        src = local_pkgs[name] / "pubspec.yaml"
        if src.exists():
            dst_dir = out / "bundled_packages" / name
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst_dir / "pubspec.yaml")

    # Generate clean pubspec.yaml
    generate(root, out, used_pkgs, path_pkgs, git_pkgs, pub_deps,
             cfg.redact_packages)

    # Copy auxiliary files (no pubspec.lock — regenerated clean from the new pubspec)
    for name in ["dart_test.yaml", "analysis_options.yaml"]:
        src = root / name
        if src.exists():
            shutil.copy2(src, out / name)

    total_kb = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1024
    redacted = set(cfg.redact_packages)
    return {
        "dart_files": copied,
        "local_packages": sorted(p for p in used_local if p not in redacted),
        "pub_packages": len(used_pub),
        "size_kb": total_kb,
        "out": out,
    }
