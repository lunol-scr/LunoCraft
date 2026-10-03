"""Luno Launcher - логика: установка игры, моды из zip, servers.dat, запуск."""
from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Callable, Optional

LAUNCHER_VERSION = "1.1"
Log = Callable[[str], None]
Progress = Callable[[int, int], None]  # (current, max)


# --------------------------------------------------------------------------- #
# Пути и конфиг
# --------------------------------------------------------------------------- #
def _search_dirs() -> list[Path]:
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
        if hasattr(sys, "_MEIPASS"):
            dirs.append(Path(sys._MEIPASS))
    dirs.append(Path(__file__).resolve().parent)
    return dirs


def find_resource(rel: str) -> Path:
    """Ищет файл рядом с exe / в бандле PyInstaller / рядом со скриптом."""
    for d in _search_dirs():
        p = d / rel
        if p.exists():
            return p
    return _search_dirs()[0] / rel


def load_config() -> dict:
    with open(find_resource("config.json"), encoding="utf-8") as f:
        return json.load(f)


def data_dir(cfg: dict) -> Path:
    name = cfg.get("data_dir_name", "LunoCraft")
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    p = base / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def total_ram_mb() -> int:
    try:
        if os.name == "nt":
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.ullTotalPhys / 2 ** 20)
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // 2 ** 20
    except Exception:
        return 8192


# --------------------------------------------------------------------------- #
# Настройки пользователя
# --------------------------------------------------------------------------- #
def load_settings(root: Path) -> dict:
    try:
        return json.loads((root / "launcher_settings.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(root: Path, data: dict) -> None:
    (root / "launcher_settings.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Оффлайн-аккаунт
# --------------------------------------------------------------------------- #
def valid_nick(nick: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_]{3,16}", nick or "") is not None


def offline_uuid(nick: str) -> str:
    """Тот же UUID, который сервер с online-mode=false выдаёт игроку."""
    h = bytearray(hashlib.md5(("OfflinePlayer:" + nick).encode("utf-8")).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(h)))


# --------------------------------------------------------------------------- #
# Мини-NBT (для servers.dat)
# --------------------------------------------------------------------------- #
def _rd(fmt: str, f) -> object:
    return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]


def _read_payload(t: int, f):
    if t == 1: return _rd(">b", f)
    if t == 2: return _rd(">h", f)
    if t == 3: return _rd(">i", f)
    if t == 4: return _rd(">q", f)
    if t == 5: return _rd(">f", f)
    if t == 6: return _rd(">d", f)
    if t == 7:
        return f.read(_rd(">i", f))
    if t == 8:
        return f.read(_rd(">H", f)).decode("utf-8", "replace")
    if t == 9:
        et = _rd(">B", f)
        n = _rd(">i", f)
        return (et, [_read_payload(et, f) for _ in range(n)])
    if t == 10:
        d = {}
        while True:
            t2 = _rd(">B", f)
            if t2 == 0:
                return d
            name = _read_payload(8, f)
            d[name] = (t2, _read_payload(t2, f))
    if t == 11:
        return [_rd(">i", f) for _ in range(_rd(">i", f))]
    if t == 12:
        return [_rd(">q", f) for _ in range(_rd(">i", f))]
    raise ValueError(f"unknown NBT tag {t}")


def _write_payload(t: int, v, out: io.BytesIO) -> None:
    if t == 1: out.write(struct.pack(">b", v))
    elif t == 2: out.write(struct.pack(">h", v))
    elif t == 3: out.write(struct.pack(">i", v))
    elif t == 4: out.write(struct.pack(">q", v))
    elif t == 5: out.write(struct.pack(">f", v))
    elif t == 6: out.write(struct.pack(">d", v))
    elif t == 7:
        out.write(struct.pack(">i", len(v))); out.write(v)
    elif t == 8:
        b = v.encode("utf-8"); out.write(struct.pack(">H", len(b))); out.write(b)
    elif t == 9:
        et, items = v
        out.write(struct.pack(">Bi", et, len(items)))
        for it in items:
            _write_payload(et, it, out)
    elif t == 10:
        for name, (t2, v2) in v.items():
            out.write(struct.pack(">B", t2)); _write_payload(8, name, out); _write_payload(t2, v2, out)
        out.write(b"\x00")
    elif t == 11:
        out.write(struct.pack(">i", len(v)))
        for x in v: out.write(struct.pack(">i", x))
    elif t == 12:
        out.write(struct.pack(">i", len(v)))
        for x in v: out.write(struct.pack(">q", x))
    else:
        raise ValueError(f"unknown NBT tag {t}")


def nbt_loads(data: bytes) -> dict:
    f = io.BytesIO(data)
    if _rd(">B", f) != 10:
        raise ValueError("root is not a compound")
    _read_payload(8, f)  # имя корня
    return _read_payload(10, f)


def nbt_dumps(root: dict) -> bytes:
    out = io.BytesIO()
    out.write(b"\x0a\x00\x00")
    _write_payload(10, root, out)
    return out.getvalue()


def ensure_server(game_dir: Path, name: str, ip: str, log: Log = print) -> None:
    """Добавляет сервер первым в список мультиплеера, остальные не трогает."""
    path = game_dir / "servers.dat"
    root: dict = {}
    if path.exists():
        try:
            root = nbt_loads(path.read_bytes())
        except Exception:
            shutil.copy2(path, path.with_suffix(".dat.bak"))
            log("servers.dat был повреждён — сделана копия .bak, создаю новый")
            root = {}
    et, items = (10, [])
    if "servers" in root and root["servers"][0] == 9:
        et, items = root["servers"][1]
    if et != 10:
        et, items = 10, []
    items = [s for s in items if str(s.get("ip", (8, ""))[1]).lower() != ip.lower()]
    items.insert(0, {"name": (8, name), "ip": (8, ip)})
    root["servers"] = (9, (10, items))
    tmp = path.with_suffix(".dat.tmp")
    tmp.write_bytes(nbt_dumps(root))
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Пинг сервера (Server List Ping)
# --------------------------------------------------------------------------- #
def _varint(n: int) -> bytes:
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += struct.pack("B", b | (0x80 if n else 0))
        if not n:
            return out


def _read_varint(sock: socket.socket) -> int:
    n = 0
    for i in range(5):
        b = sock.recv(1)
        if not b:
            raise ConnectionError("closed")
        n |= (b[0] & 0x7F) << (7 * i)
        if not b[0] & 0x80:
            return n
    raise ValueError("varint too long")


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def ping_server(address: str, timeout: float = 4.0) -> Optional[dict]:
    """Возвращает {'online','max','version','latency_ms'} или None, если сервер недоступен."""
    host, _, port = address.partition(":")
    port = int(port or 25565)
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            hs = _varint(0) + _varint(767) + _varint(len(host)) + host.encode() \
                + struct.pack(">H", port) + _varint(1)
            s.sendall(_varint(len(hs)) + hs)
            t0 = time.perf_counter()
            s.sendall(_varint(1) + b"\x00")
            _read_varint(s)                       # длина пакета
            _read_varint(s)                       # id пакета
            slen = _read_varint(s)
            data = json.loads(_recv_exact(s, slen).decode("utf-8", "replace"))
            ms = int((time.perf_counter() - t0) * 1000)
        pl = data.get("players", {})
        return {"online": pl.get("online", 0), "max": pl.get("max", 0),
                "version": data.get("version", {}).get("name", "?"), "latency_ms": ms}
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Моды из zip
# --------------------------------------------------------------------------- #
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _http_get(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": "LunoLauncher"})
    return urllib.request.urlopen(req, timeout=timeout)


def resolve_mods_zip(cfg: dict, root: Path, log: Log, progress: Progress = lambda c, m: None) -> Path:
    """Возвращает путь к zip с модами.

    Если в config.json задан mods_manifest_url - читает маленький mods.json
    ({"url": ..., "sha256": ...}) и скачивает zip только когда он изменился.
    Без интернета использует ранее скачанную копию. Без manifest - берёт assets/mods.zip.
    """
    manifest_url = (cfg.get("mods_manifest_url") or "").strip()
    local = find_resource(cfg.get("mods_zip", "assets/mods.zip"))
    if not manifest_url:
        if not local.exists():
            raise FileNotFoundError(f"Не найден архив с модами: {local}")
        return local

    cache = root / "cache"
    cache.mkdir(exist_ok=True)
    cached, meta = cache / "mods.zip", cache / "mods_meta.json"

    try:
        with _http_get(manifest_url, 15) as r:
            manifest = json.loads(r.read().decode("utf-8"))
        url = manifest["url"]
        want = str(manifest.get("sha256", "")).lower()
    except Exception as e:
        log(f"Не удалось проверить обновления модов ({e}).")
        if cached.exists():
            log("Использую ранее скачанную сборку модов.")
            return cached
        if local.exists():
            return local
        raise RuntimeError("Не удалось получить список модов. Проверьте интернет и ссылку в config.json.")

    have = ""
    try:
        have = json.loads(meta.read_text(encoding="utf-8")).get("sha256", "")
    except Exception:
        pass
    if cached.exists() and want and have == want:
        log("Сборка модов актуальна.")
        return cached

    log("Скачиваю обновление модов...")
    tmp = cached.with_suffix(".tmp")
    try:
        with _http_get(url, 30) as r, open(tmp, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                progress(done, total or done)
        got = _sha256(tmp)
        if want and got != want:
            raise ValueError("контрольная сумма не совпала: файл повреждён или mods.json не обновлён")
        os.replace(tmp, cached)
        meta.write_text(json.dumps({"sha256": got}), encoding="utf-8")
        return cached
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log(f"Ошибка загрузки модов: {e}")
        if cached.exists():
            log("Использую ранее скачанную сборку модов.")
            return cached
        raise RuntimeError(f"Не удалось скачать моды: {e}")


def install_mods(zip_path: Path, game_dir: Path, log: Log, progress: Progress) -> None:
    """Распаковывает .jar из zip в <game>/mods. Файлы лаунчера обновляются/удаляются
    по манифесту, чужие моды игрока не трогаются."""
    mods_dir = game_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = mods_dir / ".luno_manifest.json"
    zip_hash = _sha256(zip_path)

    with zipfile.ZipFile(zip_path) as z:
        entries = {}
        for info in z.infolist():
            base = os.path.basename(info.filename.replace("\\", "/"))
            if info.is_dir() or not base.lower().endswith(".jar") or base.startswith("._") \
                    or info.filename.startswith("__MACOSX"):
                continue
            entries[base] = info

        old = {}
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

        up_to_date = (old.get("zip_sha256") == zip_hash and
                      all((mods_dir / n).exists() and (mods_dir / n).stat().st_size == i.file_size
                          for n, i in entries.items()))
        if up_to_date:
            log(f"Моды актуальны ({len(entries)} шт.)")
            progress(1, 1)
            return

        for name in old.get("files", []):
            if name not in entries:
                try:
                    (mods_dir / name).unlink()
                    log(f"Удалён устаревший мод: {name}")
                except FileNotFoundError:
                    pass

        log(f"Устанавливаю моды: {len(entries)} шт.")
        total = len(entries)
        for i, (name, info) in enumerate(sorted(entries.items()), 1):
            dest = mods_dir / name
            tmp = dest.with_suffix(".jar.tmp")
            with z.open(info) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out)
            os.replace(tmp, dest)
            progress(i, total)

    manifest_path.write_text(json.dumps({"zip_sha256": zip_hash, "files": sorted(entries)}, indent=2),
                             encoding="utf-8")
    managed = set(entries)
    extra = [p.name for p in mods_dir.glob("*.jar") if p.name not in managed]
    if extra:
        log(f"В папке mods есть {len(extra)} сторонних модов — они оставлены как есть.")


def ensure_default_options(game_dir: Path) -> None:
    """Только при первом запуске: русский язык и без экрана специальных возможностей."""
    p = game_dir / "options.txt"
    if not p.exists():
        p.write_text("lang:ru_ru\nonboardAccessibility:false\ntutorialStep:none\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Установка игры и запуск
# --------------------------------------------------------------------------- #
def _fabric_version_id(mc_dir: Path, mc_version: str) -> Optional[str]:
    import minecraft_launcher_lib as mll
    pat = re.compile(rf"^fabric-loader-(.+)-{re.escape(mc_version)}$")
    best, best_key = None, None
    for v in mll.utils.get_installed_versions(str(mc_dir)):
        m = pat.match(v["id"])
        if m:
            key = [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", m.group(1))]
            if best is None or key > best_key:
                best, best_key = v["id"], key
    return best


def ensure_game(mc_version: str, mc_dir: Path, log: Log, progress: Progress,
                repair: bool = False) -> str:
    """Ставит Minecraft + Fabric + Java (если нет). Возвращает id версии для запуска."""
    import minecraft_launcher_lib as mll

    state = {"max": 0}
    cb = {"setStatus": lambda t: log(t),
          "setMax": lambda m: state.__setitem__("max", m),
          "setProgress": lambda v: progress(v, state["max"])}

    version_id = _fabric_version_id(mc_dir, mc_version)
    marker = mc_dir / f".luno_ok_{mc_version}"

    if version_id is None:
        log(f"Устанавливаю Minecraft {mc_version} + Fabric (первый запуск, это займёт несколько минут)...")
        mll.fabric.install_fabric(mc_version, str(mc_dir), callback=cb)
        version_id = _fabric_version_id(mc_dir, mc_version)
        if version_id is None:
            raise RuntimeError("Fabric не установился — проверьте интернет и попробуйте ещё раз")
        marker.write_text(version_id)
    elif repair or not marker.exists():
        log("Проверяю файлы игры...")
        try:
            mll.install.install_minecraft_version(version_id, str(mc_dir), callback=cb)
            marker.write_text(version_id)
        except Exception as e:
            log(f"Проверка не удалась ({e}). Пробую запустить с тем, что есть.")

    # Java нужной версии (для 1.21.x — Java 21)
    try:
        vjson = json.loads((mc_dir / "versions" / mc_version / f"{mc_version}.json").read_text(encoding="utf-8"))
        comp = vjson.get("javaVersion", {}).get("component")
        if comp and not mll.runtime.get_executable_path(comp, str(mc_dir)):
            log("Скачиваю Java...")
            mll.runtime.install_jvm_runtime(comp, str(mc_dir), callback=cb)
    except Exception as e:
        log(f"Предупреждение при установке Java: {e}")
    return version_id


def build_command(version_id: str, mc_dir: Path, nick: str, ram_mb: int,
                  server_ip: str, autoconnect: bool) -> list[str]:
    import minecraft_launcher_lib as mll
    options = {
        "username": nick,
        "uuid": offline_uuid(nick),
        "token": "0",
        "gameDirectory": str(mc_dir),
        "launcherName": "LunoLauncher",
        "launcherVersion": LAUNCHER_VERSION,
        "jvmArguments": [f"-Xmx{ram_mb}M", f"-Xms{min(ram_mb, 1024)}M"],
    }
    if autoconnect:
        options["quickPlayMultiplayer"] = server_ip
    cmd = mll.command.get_minecraft_command(version_id, str(mc_dir), options)
    if autoconnect and "--quickPlayMultiplayer" not in cmd:
        cmd += ["--quickPlayMultiplayer", server_ip]
    return cmd


def launch(cmd: list[str], game_dir: Path) -> subprocess.Popen:
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    return subprocess.Popen(cmd, cwd=str(game_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", creationflags=flags)


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
