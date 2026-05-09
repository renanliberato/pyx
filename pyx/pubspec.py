"""Parse pubspec.yaml and generate a clean, credential-free version."""

from __future__ import annotations
import re
from pathlib import Path


def get_package_name(pkg_root: Path) -> str:
    text = (pkg_root / "pubspec.yaml").read_text()
    m = re.search(r"^name:\s*['\"]?(\w+)['\"]?", text, re.MULTILINE)
    return m.group(1) if m else ""


def parse_deps(root: Path, pub_cache: Path) -> tuple[dict, dict, dict]:
    """
    Parse pubspec.yaml. Returns:
      path_pkgs — {name: absolute_path}
      git_pkgs  — {name: absolute_path}  (resolved from pub cache)
      pub_deps  — {name: version_string}
    """
    text = (root / "pubspec.yaml").read_text()
    path_pkgs, git_pkgs, pub_deps = {}, {}, {}

    # path: deps — two-line pattern allowing blank lines / comments between entries
    for m in re.finditer(
        r"^\s{2,4}(\w+):\s*\n(?:[ \t]*#[^\n]*\n|\s*\n)*\s{4,}path:\s*(.+)$",
        text, re.MULTILINE,
    ):
        name, raw = m.group(1), m.group(2).strip()
        p = Path(raw)
        path_pkgs[name] = (p if p.is_absolute() else root / p).resolve()

    # git: deps — resolved from pub cache
    for m in re.finditer(
        r"^\s{2,4}(\w+):\s*\n(?:[ \t]*#[^\n]*\n|\s*\n)*\s{4,}git:\s*\n((?:\s{6,}.+\n?)*)",
        text, re.MULTILINE,
    ):
        name = m.group(1)
        git_block = m.group(2)
        url_m = re.search(r"url:\s*(.+)", git_block)
        path_m = re.search(r"path:\s*(.+)", git_block)
        if not url_m:
            continue
        url = url_m.group(1).strip()
        sub = path_m.group(1).strip() if path_m else ""
        repo_slug = url.rstrip("/").split("/")[-1].removesuffix(".git")
        candidates = list((pub_cache / "git").glob(f"{repo_slug}-*"))
        if candidates:
            pkg_root = candidates[0]
            if sub:
                pkg_root = pkg_root / sub
            git_pkgs[name] = pkg_root.resolve()

    # pub.dev deps — simple `name: version` lines inside dep sections
    in_dep = False
    for line in text.splitlines():
        if re.match(r"^(dependencies|dev_dependencies):", line):
            in_dep = True
            continue
        if in_dep and re.match(r"^\S", line):
            in_dep = False
        if not in_dep:
            continue
        m = re.match(r"^  (\w+):\s*(\^?[\d\w.+\-<>=]+)\s*(?:#.*)?$", line)
        if m:
            name, ver = m.group(1), m.group(2).strip()
            if name not in path_pkgs and name not in git_pkgs:
                pub_deps[name] = ver

    return path_pkgs, git_pkgs, pub_deps


def _extract_scalar(text: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _extract_block(text: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*\n((?:[ \t]+.+\n?)*)", text, re.MULTILINE)
    return m.group(1).rstrip() if m else ""


def _dev_dep_names(text: str) -> set[str]:
    block = _extract_block(text, "dev_dependencies")
    return {m.group(1) for m in re.finditer(r"^\s{2,4}(\w+):", block, re.MULTILINE)}


def generate(
    root: Path,
    out: Path,
    used_pkgs: set[str],
    path_pkgs: dict,
    git_pkgs: dict,
    pub_deps: dict,
    redact_packages: list[str],
) -> None:
    """Write a clean pubspec.yaml with no private git/path references."""
    orig = (root / "pubspec.yaml").read_text()
    dev_names = _dev_dep_names(orig)
    local_pkgs = {**path_pkgs, **git_pkgs}
    redacted = set(redact_packages)

    runtime_deps: dict[str, tuple] = {}
    dev_deps: dict[str, tuple] = {}

    for name in used_pkgs:
        target = dev_deps if name in dev_names else runtime_deps
        if name in local_pkgs:
            target[name] = ("path", f"./bundled_packages/{name}")
        elif name in pub_deps:
            target[name] = ("ver", pub_deps[name])

    name_val    = _extract_scalar(orig, "name")
    desc_val    = _extract_scalar(orig, "description")
    version_val = _extract_scalar(orig, "version")
    env_block   = _extract_block(orig, "environment")

    lines = []
    lines.append(f"name: {name_val}")
    if desc_val:
        lines.append(f"description: {desc_val}")
    lines.append("publish_to: none")
    if version_val:
        lines.append(f"version: {version_val}")
    if env_block:
        lines += ["environment:", env_block]
    lines += ["", "flutter:", "  uses-material-design: true", ""]

    def write_dep(name: str, kind: str, val: str) -> list[str]:
        if kind == "path":
            return [f"  {name}:", f"    path: {val}"]
        return [f"  {name}: {val}"]

    lines.append("dependencies:")
    lines += ["  flutter:", "    sdk: flutter"]
    for name, (kind, val) in sorted(runtime_deps.items()):
        lines.extend(write_dep(name, kind, val))

    lines += ["", "dev_dependencies:"]
    lines += ["  flutter_test:", "    sdk: flutter"]
    for name, (kind, val) in sorted(dev_deps.items()):
        lines.extend(write_dep(name, kind, val))

    (out / "pubspec.yaml").write_text("\n".join(lines) + "\n")
