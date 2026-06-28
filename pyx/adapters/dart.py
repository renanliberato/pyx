"""Dart language adapter for pyx bundles."""

from __future__ import annotations
import json
import re
import shutil
from collections import deque
from pathlib import Path
from typing import Any

from ..domain import (
    BundleRequest,
    BundleResult,
    BundleManifest,
    RunCommand,
    Diagnostic,
    DiagnosticSeverity,
    LanguageAdapter,
)
from ..pubspec import get_package_name, parse_deps, generate


class DartAdapter:
    """Dart/Flutter bundle adapter.

    Handles:
    - Walking Dart import graphs transitively from seed .dart files
    - Resolving local Pub dependencies (path and git)
    - Generating clean pubspec.yaml
    - Copying only imported files
    """

    def __init__(self, pub_cache: Path, redact_packages: list[str] | None = None):
        self.pub_cache = pub_cache
        self.redact_packages = redact_packages or []

    @property
    def language(self) -> str:
        return "dart"

    @property
    def file_extensions(self) -> list[str]:
        return [".dart"]

    def bundle(self, request: BundleRequest) -> BundleResult:
        """Create a Dart bundle from the given request."""
        if request.output_dir.exists():
            shutil.rmtree(request.output_dir)
        request.output_dir.mkdir(parents=True, exist_ok=True)

        diagnostics: list[Diagnostic] = []

        # Parse pubspec and resolve dependencies
        try:
            path_pkgs, git_pkgs, pub_deps = parse_deps(request.project_root, self.pub_cache)
            pkg_name = get_package_name(request.project_root)
            local_pkgs = {**path_pkgs, **git_pkgs}
        except Exception as e:
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
                errors=[Diagnostic(DiagnosticSeverity.ERROR, f"Failed to parse pubspec: {e}")],
            )

        # Collect transitively needed files
        dart_files, used_local, used_pub = self._collect(
            request.seeds, request.project_root, local_pkgs, pkg_name
        )
        used_pkgs = used_local | used_pub

        # Copy dart source files
        copied = 0
        copied_files: list[str] = []
        for src in dart_files:
            dst = None
            # Local package files → bundled_packages/<name>/
            for name, pkg_path in local_pkgs.items():
                try:
                    rel = src.relative_to(pkg_path)
                    dst = request.output_dir / "bundled_packages" / name / rel
                    break
                except ValueError:
                    continue
            # Repo files → keep original relative path
            if dst is None:
                try:
                    dst = request.output_dir / src.relative_to(request.project_root)
                except ValueError:
                    continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
            copied_files.append(str(dst.relative_to(request.output_dir)))

        # Copy pubspec.yaml for each bundled local package
        project_files: list[str] = []
        for name in used_local:
            src = local_pkgs[name] / "pubspec.yaml"
            if src.exists():
                dst_dir = request.output_dir / "bundled_packages" / name
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst_dir / "pubspec.yaml")
                project_files.append(f"bundled_packages/{name}/pubspec.yaml")

        # Generate clean pubspec.yaml
        generate(
            request.project_root,
            request.output_dir,
            used_pkgs,
            path_pkgs,
            git_pkgs,
            pub_deps,
            self.redact_packages,
        )
        project_files.append("pubspec.yaml")

        # Copy auxiliary files
        for name in ["dart_test.yaml", "analysis_options.yaml"]:
            src = request.project_root / name
            if src.exists():
                shutil.copy2(src, request.output_dir / name)
                project_files.append(name)

        # Write manifest
        redacted = set(self.redact_packages)
        manifest = BundleManifest(
            language=self.language,
            seeds=[str(s.relative_to(request.project_root)) for s in request.seeds],
            files=copied_files,
            project_files=project_files,
            dependencies={
                "local_packages": sorted(p for p in used_local if p not in redacted),
                "pub_packages": len(used_pub),
            },
            run_commands=[
                RunCommand(
                    command=["flutter", "pub", "get"],
                    cwd=None,
                    description="Install dependencies",
                ),
                RunCommand(
                    command=["flutter", "test", "--no-test-assets"] + [str(s) for s in request.seeds],
                    cwd=None,
                    description="Run tests",
                ),
            ],
            diagnostics=diagnostics,
        )

        manifest_path = request.output_dir / "pyx-manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2))

        return BundleResult(
            success=True,
            manifest=manifest,
            output_dir=request.output_dir,
            errors=diagnostics,
        )

    def _collect(
        self,
        seeds: list[Path],
        root: Path,
        local_pkgs: dict[str, Path],
        pkg_name: str,
    ) -> tuple[set[Path], set[str], set[str]]:
        """BFS over import graph.

        Returns:
            dart_files — all transitively needed .dart files
            used_local_pkgs — local package names (path/git) actually imported
            used_pub_pkgs — pub.dev package names actually imported
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
            for imp in self._parse_imports(f):
                if not imp.startswith("package:") or imp.startswith("dart:"):
                    pass
                else:
                    name = imp.split("/")[0][len("package:"):]
                    if name in local_pkgs:
                        used_local.add(name)
                    elif name != pkg_name:
                        used_pub.add(name)
                resolved = self._resolve(imp, f, root, pkg_name, local_pkgs)
                if resolved and resolved not in visited:
                    queue.append(resolved)

        return visited, used_local, used_pub

    def _parse_imports(self, file: Path) -> list[str]:
        """Parse import/export/part statements from a Dart file."""
        try:
            content = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        results = []
        # Match full import/export/part statements including multi-line conditional imports
        for stmt_m in re.finditer(
            r"""^(?:import|export|part(?!\s+of))\s+['"][^'"]+['"](?:[^;]|\n)*?;""",
            content,
            re.MULTILINE,
        ):
            stmt = stmt_m.group(0)
            # Capture every quoted .dart URL (base + all conditional branches)
            results.extend(re.findall(r"""['"]([^'"]+\.dart)['"]""", stmt))
        return results

    def _resolve(
        self,
        imp: str,
        current: Path,
        root: Path,
        pkg_name: str,
        local_pkgs: dict[str, Path],
    ) -> Path | None:
        """Resolve an import string to a file path."""
        if imp.startswith("dart:"):
            return None
        if imp.startswith(f"package:{pkg_name}/"):
            return root / "lib" / imp[len(f"package:{pkg_name}/") :]
        for name, pkg_path in local_pkgs.items():
            if imp.startswith(f"package:{name}/"):
                return pkg_path / "lib" / imp[len(f"package:{name}/") :]
        if imp.startswith("package:"):
            return None  # pub.dev dep
        return (current.parent / imp).resolve()