"""Создаёт файл-манифест модов для лаунчера (на случай ручной работы).

Использование:
    python make_mods_manifest.py mods.zip https://github.com/ВАШ_НИК/РЕПО/releases/download/mods-v2/mods.zip [mods.json]

Третий аргумент - имя выходного файла (по умолчанию mods.json; для тестового канала - mods_beta.json).
Обычно это делает GitHub Actions автоматически (см. .github/workflows/update-mods-manifest.yml).
"""
import hashlib
import json
import sys
from pathlib import Path

if len(sys.argv) not in (3, 4):
    sys.exit(__doc__)
zip_path, url = Path(sys.argv[1]), sys.argv[2]
out = Path(sys.argv[3]) if len(sys.argv) == 4 else Path("mods.json")
h = hashlib.sha256()
with open(zip_path, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
out.write_text(json.dumps({"url": url, "sha256": h.hexdigest(), "size": zip_path.stat().st_size}, indent=2),
               encoding="utf-8")
print(f"{out} создан, sha256:", h.hexdigest())
