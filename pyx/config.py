"""Load and validate .pyx.yaml project configuration."""

from __future__ import annotations
import re
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class DartConfig:
    """Dart adapter configuration."""
    pub_cache: Path = field(default_factory=lambda: Path.home() / ".pub-cache")
    redact_packages: list[str] = field(default_factory=list)
    bundle_from_source: list[str] = field(default_factory=list)


@dataclass
class CsharpConfig:
    """C# adapter configuration."""
    extractor: Path = Path("vendor/chsarp-class-context/bin/chsarp-class-context")


@dataclass
class AdaptersConfig:
    """Adapter-specific configurations."""
    dart: DartConfig = field(default_factory=DartConfig)
    csharp: CsharpConfig = field(default_factory=CsharpConfig)


@dataclass
class PyxConfig:
    """pyx project configuration."""
    output_dir: Path = Path("tmp/pyx-bundle")
    language: str = "auto"  # auto | dart | csharp
    adapters: AdaptersConfig = field(default_factory=AdaptersConfig)

    @classmethod
    def load(cls, project_root: Path) -> "PyxConfig":
        config_path = project_root / ".pyx.yaml"
        if not config_path.exists():
            return cls()

        text = config_path.read_text()
        cfg = cls()

        def scalar(key: str) -> str | None:
            m = re.search(rf"^{key}:\s*(.+)$", text, re.MULTILINE)
            return m.group(1).strip().strip("\"'") if m else None

        def list_val(key: str) -> list[str]:
            # Inline: key: [a, b, c]
            m = re.search(rf"^{key}:\s*\[([^\]]*)\]", text, re.MULTILINE)
            if m:
                return [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()]
            # Block list: key:\n  - a\n  - b
            m = re.search(rf"^{key}:\s*\n((?:\s+-\s+.+\n?)+)", text, re.MULTILINE)
            if m:
                return [re.sub(r"^\s*-\s*", "", l).strip().strip("\"'")
                        for l in m.group(1).splitlines() if l.strip()]
            return []

        def block(key: str) -> str | None:
            m = re.search(rf"^{key}:\s*\n((?:[ \t]+.+\n?)+)", text, re.MULTILINE)
            return m.group(1).rstrip() if m else None

        if v := scalar("output_dir"):
            cfg.output_dir = Path(v).expanduser()
        if v := scalar("language"):
            cfg.language = v

        # Parse adapters section
        adapters_block = block("adapters")
        if adapters_block:
            # Dart config
            dart_block_match = re.search(r"dart:\s*\n((?:[ \t]+.+\n?)+)", adapters_block, re.MULTILINE)
            if dart_block_match:
                dart_block = dart_block_match.group(1)
                if v := re.search(r"pub_cache:\s*(.+)", dart_block):
                    cfg.adapters.dart.pub_cache = Path(v.group(1).strip()).expanduser()
                cfg.adapters.dart.redact_packages = _extract_list_from_block(dart_block, "redact_packages")
                cfg.adapters.dart.bundle_from_source = _extract_list_from_block(dart_block, "bundle_from_source")

            # C# config
            csharp_block_match = re.search(r"csharp:\s*\n((?:[ \t]+.+\n?)+)", adapters_block, re.MULTILINE)
            if csharp_block_match:
                csharp_block = csharp_block_match.group(1)
                if v := re.search(r"extractor:\s*(.+)", csharp_block):
                    cfg.adapters.csharp.extractor = Path(v.group(1).strip()).expanduser()
        elif config_path.exists():
            # Config file exists but has no adapters section - this is an error
            raise ValueError(
                "Invalid .pyx.yaml: missing 'adapters' section. "
                "Config must use the adapter-based shape. See `pyx init` for an example."
            )

        return cfg


def _extract_list_from_block(block: str, key: str) -> list[str]:
    """Extract a list value from a config block."""
    # Inline: key: [a, b, c]
    m = re.search(rf"{key}:\s*\[([^\]]*)\]", block, re.MULTILINE)
    if m:
        return [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()]
    # Block list: key:\n    - a\n    - b
    m = re.search(rf"{key}:\s*\n((?:[ \t]+-\s+.+\n?)+)", block, re.MULTILINE)
    if m:
        return [re.sub(r"^\s*-\s*", "", l).strip().strip("\"'")
                for l in m.group(1).splitlines() if l.strip()]
    return []