"""Создаёт mods.json для лаунчера.

Использование:
    python make_mods_manifest.py mods.zip https://github.com/ВАШ_НИК/РЕПО/releases/download/mods-v1/mods.zip

Загрузите mods.zip в GitHub Releases, а получившийся mods.json закоммитьте в репозиторий.
"""
import hashlib
import json
import sys
from pathlib import Path

if len(sys.argv) != 3:
    sys.exit(__doc__)
zip_path, url = Path(sys.argv[1]), sys.argv[2]
h = hashlib.sha256()
with open(zip_path, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
Path("mods.json").write_text(json.dumps({"url": url, "sha256": h.hexdigest(), "size": zip_path.stat().st_size},
                                        indent=2), encoding="utf-8")
print("mods.json создан, sha256:", h.hexdigest())
