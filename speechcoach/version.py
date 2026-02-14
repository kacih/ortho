"""Single source of truth for the application version.

Keep this file minimal. Other modules (config, __init__, etc.) should import
APP_VERSION / __version__ from here to avoid mismatch regressions.
"""

from __future__ import annotations

import os

APP_NAME = "SpeechCoach"
APP_VERSION = "8.0.4"
__version__ = APP_VERSION


def sync_manifest_version() -> None:
    """Best-effort: keep ressources/manifest.json product.app_version in sync.

    Never raises. Can be disabled with SPEECHCOACH_SYNC_MANIFEST=0.
    """
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(base_dir)
        manifest_path = os.path.join(project_root, "ressources", "manifest.json")
        if not os.path.exists(manifest_path):
            return

        import json  # local import to keep module lightweight

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        prod = data.get("product") or {}
        if prod.get("app_version") != APP_VERSION:
            prod["app_version"] = APP_VERSION
            data["product"] = prod
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        return


if os.environ.get("SPEECHCOACH_SYNC_MANIFEST", "1") not in ("0", "false", "False"):
    sync_manifest_version()
