import json

_DEPENDENCY_SECTIONS = ("dependencies", "devDependencies", "peerDependencies")


class AstroFramework:
    def detect(self, context) -> bool:
        """True when package.json declares `astro` or an astro.config.* file exists."""
        root = context.project_root
        if any(root.glob("astro.config.*")):
            return True
        try:
            manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(manifest, dict):
            return False
        return any(
            isinstance(manifest.get(section), dict) and "astro" in manifest[section]
            for section in _DEPENDENCY_SECTIONS
        )

    def enrich(self, context) -> None:
        pass
