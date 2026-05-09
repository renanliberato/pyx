"""Load and validate .pyx.yaml project configuration."""

from __future__ import annotations
import re
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class PyxConfig:
    # Where to write the bundle
    output_dir: Path = Path("tmp/pyx-bundle")
    # Pub cache root (default: ~/.pub-cache)
    pub_cache: Path = field(default_factory=lambda: Path.home() / ".pub-cache")
    # Extra packages to always bundle from source even if pub.dev would suffice
    bundle_from_source: list[str] = field(default_factory=list)
    # Package names to strip from the generated pubspec entirely
    # (source is bundled, but the name never appears in output pubspec or logs)
    redact_packages: list[str] = field(default_factory=list)

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

        if v := scalar("output_dir"):
            cfg.output_dir = Path(v).expanduser()
        if v := scalar("pub_cache"):
            cfg.pub_cache = Path(v).expanduser()

        cfg.bundle_from_source = list_val("bundle_from_source")
        cfg.redact_packages = list_val("redact_packages")
        return cfg
