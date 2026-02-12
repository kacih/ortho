from speechcoach.ui.app import SpeechCoachApp

import json
import sys
from pathlib import Path

from speechcoach import __version__


def check_manifest_version():
    root = Path(__file__).parent

    manifest_path = root / "ressources" / "manifest.json"

    if not manifest_path.exists():
        print("❌ ERREUR: manifest.json introuvable :", manifest_path)
        sys.exit(1)

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        print("❌ ERREUR: manifest.json invalide :", e)
        sys.exit(1)

    manifest_version = manifest.get("product", {}).get("app_version")

    if not manifest_version:
        print("❌ ERREUR: app_version manquant dans manifest.json")
        sys.exit(1)

    if manifest_version != __version__:
        print("❌ ERREUR DE VERSION")
        print(f"   Code      : {__version__}")
        print(f"   Manifest  : {manifest_version}")
        print("➡️ Corrigez avant de lancer.")
        sys.exit(1)

    print(f"✅ Version OK : {__version__}")


# Appelé AVANT tout le reste
check_manifest_version()

def main():
    check_manifest_version()
    app = SpeechCoachApp()
    app.mainloop()

if __name__ == "__main__":
    main()
