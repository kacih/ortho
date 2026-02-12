import os

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def pick_existing(*paths: str) -> str:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return paths[0] if paths else ""
