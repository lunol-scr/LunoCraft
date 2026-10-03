"""Luno Launcher - окно лаунчера (tkinter + Canvas, стиль в ui.py)."""
from __future__ import annotations

import math
import os
import queue
import threading
import time
import traceback
import zipfile
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

import core
import ui

PANEL, FG, MUTED = "#1c1f26", "#e8eaf0", "#9aa3b5"
OK, BAD = "#6bff7a", "#ff7b7b"


class App:
    def __init__(self) -> None:
        self.cfg = core.load_config()
        self.root_dir = core.data_dir(self.cfg)
        self.settings = core.load_settings(self.root_dir)
        self.mc_version = self.cfg["minecraft_version"]
        self.server = self.cfg["server"]
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.log_lines: list[str] = []
        self.log_win: tk.Toplevel | None = None
        self.log_text: tk.Text | None = None
        self.set_win: tk.Toplevel | None = None
        self._bob_t = 0
        self._bob_y = 0

        max_ram = max(2048, min(core.total_ram_mb() // 512 * 512, 16384))
        self.max_ram = max_ram

        self.win = tk.Tk()
        self.win.title(self.cfg.get("launcher_title", "Luno Launcher"))
        self.win.geometry(f"{ui.W}x{ui.H}")
        self.win.resizable(False, False)
        self.win.configure(bg=ui.GREEN_EDGE)
        self._set_icon()

        self.nick = tk.StringVar(value=self.settings.get("nick", ""))
        self.ram = tk.IntVar(value=min(self.settings.get("ram", self.cfg.get("default_ram_mb", 4096)), max_ram))
        self.auto = tk.BooleanVar(value=self.settings.get("autoconnect", True))
        self.pinned = tk.BooleanVar(value=self.settings.get("mods_pinned", False))
        self.profile = tk.StringVar(value=self.settings.get("profile", "keep"))
        self.banner_block = False

        self.cv = tk.Canvas(self.win, width=ui.W, height=ui.H, highlightthickness=0, bd=0, bg=ui.GREEN_EDGE)
        self.cv.pack()
        self._background()
        self._scene()
        self.cv.itemconfigure("banner", state="hidden")
        self.win.after(100, self._pump)
        self.win.after(50, self._bob)
        threading.Thread(target=self._ping_loop, daemon=True).start()
        if core.is_frozen() and self.cfg.get("auto_update_exe", True) and self.cfg.get("github_repo"):
            threading.Thread(target=self._self_update, daemon=True).start()

    def _set_icon(self) -> None:
        """Иконка окна и панели задач: .ico (BMP-кадры) + PNG как запасной вариант."""
        errors = []
        ico = core.find_resource("assets/icon.ico")
        png = core.find_resource("assets/icon.png")
        if ico.exists():
            try:
                self.win.iconbitmap(str(ico))
            except Exception as e:  # на Linux/macOS .ico может не поддерживаться
                errors.append(f"iconbitmap: {e!r}")
        if png.exists():
            try:
                self._icon_img = tk.PhotoImage(file=str(png))  # PNG понимает сам Tk, Pillow не нужен
                self.win.iconphoto(True, self._icon_img)
            except Exception as e:
                errors.append(f"iconphoto: {e!r}")
        if not ico.exists() and not png.exists():
            errors.append(f"файлы иконки не найдены: {ico} / {png}")
        if errors:
            try:
                (self.root_dir / "icon_error.log").write_text("\n".join(errors), encoding="utf-8")
            except Exception:
                pass

    # ------------------------------------------------------------- сцена --
    def _fonts(self):
        have = set(tkfont.families(self.win))
        family = next((f for f in ("Segoe UI Black", "Arial Black", "Segoe UI", "Helvetica", "Arial")
                       if f in have), "TkDefaultFont")
        return lambda size: (family, -round(size * 1.33), "bold")

    def _background(self) -> None:
        try:
            from PIL import ImageTk
            self._bg = ImageTk.PhotoImage(ui.make_background())
            self.cv.create_image(0, 0, image=self._bg, anchor="nw")
        except Exception:
            self.cv.configure(bg="#3f9a45")  # без Pillow - просто зелёный фон

    def _scene(self) -> None:
        self.F = self._fonts()
        try:
            with zipfile.ZipFile(core.find_resource(self.cfg.get("mods_zip", "assets/mods.zip"))) as z:
                n = sum(1 for x in z.namelist() if x.lower().endswith(".jar"))
            mods = f" · {n} модов"
        except Exception:
            mods = ""
        info = {
            "server_name": self.server["name"],
            "server_ip": self.server["ip"],
            "subtitle": f"Minecraft {self.mc_version} · Fabric{mods}",
            "version_line": f"Fabric · {self.mc_version}",
            "launcher_version": core.LAUNCHER_VERSION,
        }
        self.r = ui.build_scene(self.cv, self.F, info)

        x, y = self.r["nick_xy"]
        self.entry = tk.Entry(self.win, textvariable=self.nick, bg="#0f1115", fg=FG, insertbackground=FG,
                              relief="flat", font=(self.F(10)[0], -15), highlightthickness=1,
                              highlightbackground="#2b2f3c", highlightcolor="#6bff7a")
        self.cv.create_window(x, y, window=self.entry, anchor="nw", width=150, height=26)

        self._bind("btn_play", [self.r["play"]], self.on_play, locked=True)
        self._bind("btn_folder", [self.r["btn_folder"]], lambda: core.open_folder(self.root_dir))
        self._bind("btn_mods", [self.r["btn_mods"]], lambda: core.open_folder(self.root_dir / "mods"))
        self._bind("btn_verify", [self.r["btn_verify"]], lambda: self.on_play(repair=True, run=False),
                   locked=True)
        self._bind("btn_copy", [self.r["copy"]], self.copy_ip)
        self._bind("btn_gear", [self.r["gear"]], self.open_settings)
        self._bind("btn_log", [self.r["log"]], self.open_log)

    def _bind(self, tag: str, panels: list, cmd, locked: bool = False) -> None:
        def enter(_e=None):
            if locked and self.busy:
                return
            for p in panels:
                ui.set_fill(self.cv, p, p["hover"])
            self.cv.configure(cursor="hand2")

        def leave(_e=None):
            if locked and self.busy:
                return
            for p in panels:
                ui.set_fill(self.cv, p, p["fill"])
            self.cv.configure(cursor="")

        def click(_e=None):
            if locked and self.busy:
                return
            cmd()

        self.cv.tag_bind(tag, "<Enter>", enter)
        self.cv.tag_bind(tag, "<Leave>", leave)
        self.cv.tag_bind(tag, "<Button-1>", click)

    def _bob(self) -> None:
        """Лёгкое покачивание блока в центре."""
        self._bob_t += 1
        y = round(math.sin(self._bob_t / 14) * 5)
        if y != self._bob_y:
            self.cv.move("hero", 0, y - self._bob_y)
            self._bob_y = y
        self.win.after(50, self._bob)

    # ------------------------------------------------- окна: лог/настройки --
    def open_log(self) -> None:
        if self.log_win and self.log_win.winfo_exists():
            self.log_win.lift()
            return
        w = tk.Toplevel(self.win)
        w.title("Лог")
        w.geometry("720x420")
        w.configure(bg=PANEL)
        t = tk.Text(w, bg="#12141a", fg="#c8cfdf", relief="flat", font=("Consolas", 9), wrap="word")
        sb = tk.Scrollbar(w, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(fill="both", expand=True)
        t.insert("end", "\n".join(self.log_lines) + ("\n" if self.log_lines else ""))
        t.see("end")
        t.configure(state="disabled")
        self.log_win, self.log_text = w, t

    def _log_add(self, line: str) -> None:
        line = line.rstrip("\n")
        self.log_lines.append(line)
        if len(self.log_lines) > 1500:
            del self.log_lines[:300]
        if self.log_win and self.log_win.winfo_exists() and self.log_text:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def open_settings(self) -> None:
        if self.set_win and self.set_win.winfo_exists():
            self.set_win.lift()
            return
        w = tk.Toplevel(self.win)
        w.title("Настройки")
        w.geometry("440x470")
        w.resizable(False, False)
        w.configure(bg=PANEL)
        self.set_win = w
        fam = self.F(10)[0]
        head = lambda t: tk.Label(w, text=t, bg=PANEL, fg=FG, font=(fam, -15, "bold"))

        # --- память
        head("Оперативная память").pack(anchor="w", padx=20, pady=(16, 2))
        lbl = tk.Label(w, bg=PANEL, fg=OK, font=(fam, -16, "bold"))

        def changed(*_):
            v = int(float(self.ram.get()) // 256 * 256)
            lbl.configure(text=f"{v / 1024:.2f} ГБ".replace(".00", ""))
        tk.Scale(w, from_=2048, to=self.max_ram, resolution=256, orient="horizontal", variable=self.ram,
                 showvalue=False, command=changed, bg=PANEL, fg=FG, troughcolor="#0f1115",
                 highlightthickness=0, bd=0, length=400).pack(padx=20)
        lbl.pack(anchor="w", padx=20)
        changed()

        # --- профиль производительности
        head("Профиль производительности").pack(anchor="w", padx=20, pady=(12, 2))
        labels = {"keep": "Не менять мои настройки", "auto": "Авто (по мощности ПК)", "low": "Слабый ПК",
                  "mid": "Средний ПК", "high": "Мощный ПК"}
        rev = {v: k for k, v in labels.items()}
        disp = tk.StringVar(value=labels.get(self.profile.get(), labels["keep"]))

        def pick(label):
            key = rev[label]
            self.profile.set(key)
            if key != "keep":
                self.ram.set(core.recommended_ram(key, core.total_ram_mb()))
                changed()
        om = tk.OptionMenu(w, disp, *labels.values(), command=pick)
        om.configure(bg="#0f1115", fg=FG, activebackground="#262a36", activeforeground=FG, relief="flat",
                     highlightthickness=0, width=34, anchor="w")
        om.pack(anchor="w", padx=20)
        tk.Label(w, text="Меняет дальность прорисовки, графику и частицы один раз при выборе профиля.",
                 bg=PANEL, fg=MUTED, font=(fam, -12), wraplength=400, justify="left").pack(anchor="w", padx=20)

        # --- вход на сервер
        tk.Checkbutton(w, text="Сразу заходить на сервер после запуска игры", variable=self.auto,
                       bg=PANEL, fg=FG, selectcolor="#0f1115", activebackground=PANEL,
                       activeforeground=FG).pack(anchor="w", padx=16, pady=(10, 0))

        # --- откат модов
        head("Версия модов").pack(anchor="w", padx=20, pady=(12, 2))
        has_prev = (self.root_dir / "cache" / "mods_prev.zip").exists()
        state = tk.Label(w, bg=PANEL, fg=MUTED, font=(fam, -12), wraplength=400, justify="left")
        state.pack(anchor="w", padx=20)

        def refresh():
            if self.pinned.get():
                state.configure(text="Сейчас закреплена ПРОШЛАЯ версия модов (откат).")
            elif has_prev:
                state.configure(text="Сейчас используется актуальная версия. Прошлая сохранена для отката.")
            else:
                state.configure(text="Сейчас используется актуальная версия. Прошлой версии пока нет.")
        refresh()
        bf = tk.Frame(w, bg=PANEL)
        bf.pack(anchor="w", padx=20, pady=6)

        def rollback():
            self.pinned.set(True)
            refresh()
            messagebox.showinfo("Откат модов", "Откат применится при следующем нажатии «Играть».")

        def unpin():
            self.pinned.set(False)
            refresh()
        tk.Button(bf, text="Откатить на прошлую", command=rollback, state="normal" if has_prev else "disabled",
                  bg="#3a4260", fg=FG, relief="flat", padx=10, pady=3).pack(side="left")
        tk.Button(bf, text="Вернуть актуальную", command=unpin, bg="#3a4260", fg=FG, relief="flat",
                  padx=10, pady=3).pack(side="left", padx=8)

        def close():
            self._save()
            w.destroy()
        tk.Button(w, text="Готово", command=close, bg="#5fcb4c", fg="#0e1014", relief="flat",
                  font=(fam, -15, "bold"), padx=24, pady=4, cursor="hand2").pack(pady=14)
        w.protocol("WM_DELETE_WINDOW", close)

    def _save(self) -> None:
        self.settings.update({
            "nick": self.nick.get().strip(),
            "ram": int(float(self.ram.get()) // 256 * 256),
            "autoconnect": self.auto.get(),
            "mods_pinned": self.pinned.get(),
            "profile": self.profile.get(),
        })
        core.save_settings(self.root_dir, self.settings)

    def copy_ip(self) -> None:
        self.win.clipboard_clear()
        self.win.clipboard_append(self.server["ip"])
        self.cv.itemconfigure(self.r["copy_txt"], text="Скопировано!")
        self.win.after(1500, lambda: self.cv.itemconfigure(self.r["copy_txt"], text="Скопировать IP"))

    # ------------------------------------------------------ очередь событий --
    def _set_status(self, s: str) -> None:
        self.cv.itemconfigure(self.r["status"], text=s if len(s) <= 90 else s[:87] + "...")

    def _set_progress(self, cur: int, mx: int) -> None:
        x1, y1, x2, y2 = self.r["bar"]
        frac = max(0.0, min(1.0, cur / mx)) if mx else 0.0
        self.cv.coords(self.r["bar_fill"], x1 + 1, y1 + 1, x1 + 1 + (x2 - x1 - 2) * frac, y2 - 1)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        p = self.r["play"]
        if busy:
            ui.set_fill(self.cv, p, "#6c7a68")
            self.cv.itemconfigure(self.r["play_txt"], text="Ждите...")
            self.cv.configure(cursor="")
        else:
            ui.set_fill(self.cv, p, p["fill"])
            self.cv.itemconfigure(self.r["play_txt"], text="Играть")

    def _pump(self) -> None:
        try:
            while True:
                kind, *a = self.q.get_nowait()
                if kind == "log":
                    self._log_add(a[0])
                elif kind == "status":
                    self._set_status(a[0])
                elif kind == "progress":
                    self._set_progress(a[0], a[1])
                elif kind == "server":
                    self._show_server(a[0])
                elif kind == "banner":
                    self._show_banner(a[0])
                elif kind == "busy":
                    self._set_busy(a[0])
                elif kind == "restart":
                    core.start_updater(a[0], a[1])
                    self.win.destroy()
                    os._exit(0)
                elif kind == "minimize":
                    self.win.iconify()
                elif kind == "restore":
                    self.win.deiconify()
                elif kind == "done":
                    self._set_busy(False)
                elif kind == "error":
                    messagebox.showerror("Ошибка", a[0])
        except queue.Empty:
            pass
        self.win.after(100, self._pump)

    def _show_server(self, info) -> None:
        if info:
            self.cv.itemconfigure(self.r["srv_num"], text=f"{info['online']}/{info['max']}", fill=OK)
            self.cv.itemconfigure(self.r["srv_lbl"], text=f"в сети · {info['latency_ms']} мс")
        else:
            self.cv.itemconfigure(self.r["srv_num"], text="офлайн", fill=BAD)
            self.cv.itemconfigure(self.r["srv_lbl"], text="сервер недоступен")

    def _show_banner(self, status) -> None:
        m = (status or {}).get("maintenance") or {}
        if m.get("enabled"):
            text = str(m.get("message") or "Технические работы на сервере")
            self.cv.itemconfigure(self.r["banner_txt"], text=text if len(text) <= 70 else text[:67] + "...")
            self.cv.itemconfigure("banner", state="normal")
            self.banner_block = bool(m.get("block_play"))
        else:
            self.cv.itemconfigure("banner", state="hidden")
            self.banner_block = False

    def _ping_loop(self) -> None:
        while True:
            self.q.put(("server", core.ping_server(self.server["ip"])))
            url = self.cfg.get("status_url")
            if url:
                self.q.put(("banner", core.fetch_status(url)))
            time.sleep(30)

    def _self_update(self) -> None:
        """Только для собранного .exe: проверяет новую сборку на GitHub и обновляет себя."""
        try:
            remote = core.remote_build(self.cfg)
            if remote is None or remote <= core.local_build():
                return
            self.q.put(("busy", True))
            self.q.put(("status", f"Обновляю лаунчер до сборки {remote}..."))
            log = lambda t: self.q.put(("log", t))
            src, tmp = core.prepare_update(self.cfg, log, lambda c, m: self.q.put(("progress", c, m)))
            self.q.put(("status", "Перезапуск лаунчера..."))
            self.q.put(("restart", src, tmp))
        except Exception as e:
            self.q.put(("log", f"Не удалось обновить лаунчер: {e}"))
            self.q.put(("status", "Не удалось обновить лаунчер"))
            self.q.put(("busy", False))

    # --------------------------------------------------------------- запуск --
    def on_play(self, repair: bool = False, run: bool = True) -> None:
        if self.busy:
            return
        if run and self.banner_block:
            messagebox.showinfo("Технические работы", "Сервер сейчас на обслуживании. Зайдите позже.")
            return
        nick = self.nick.get().strip()
        if run and not core.valid_nick(nick):
            messagebox.showwarning("Ник", "Ник: 3–16 символов, только латиница, цифры и _")
            return
        ram = int(float(self.ram.get()) // 256 * 256)
        if run:
            self._save()
        self._set_busy(True)
        opts = {"autoconnect": self.auto.get(), "pinned": self.pinned.get(), "profile": self.profile.get(),
                "beta": bool(self.settings.get("beta", False)), "strict": bool(self.cfg.get("strict_mods", False))}
        threading.Thread(target=self._worker, args=(nick, ram, repair, run, opts), daemon=True).start()

    def _worker(self, nick: str, ram: int, repair: bool, run: bool, opts: dict) -> None:
        log = lambda t: self.q.put(("log", t))
        status = lambda t: self.q.put(("status", t))
        progress = lambda c, m: self.q.put(("progress", c, m))
        try:
            status("Установка игры...")
            version_id = core.ensure_game(self.mc_version, self.root_dir, log, progress, repair=repair)

            status("Проверка модов...")
            zip_path = core.resolve_mods_zip(self.cfg, self.root_dir, log, progress,
                                             beta=opts["beta"], pinned=opts["pinned"])
            status("Установка модов...")
            core.install_mods(zip_path, self.root_dir, log, progress, strict=opts["strict"])

            core.ensure_server(self.root_dir, self.server["name"], self.server["ip"], log)
            core.ensure_default_options(self.root_dir)
            self._apply_profile(opts["profile"], log)
            log(f"Сервер «{self.server['name']}» ({self.server['ip']}) добавлен в список.")

            if not run:
                status("Файлы проверены")
                return

            status("Запуск Minecraft...")
            cmd = core.build_command(version_id, self.root_dir, nick, ram, self.server["ip"],
                                     opts["autoconnect"])
            proc = core.launch(cmd, self.root_dir)
            self.q.put(("progress", 1, 1))
            status("Игра запущена")
            self.q.put(("minimize",))
            for line in proc.stdout:  # type: ignore[union-attr]
                log(line)
            code = proc.wait()
            self.q.put(("restore",))
            if code == 0:
                status("Игра закрыта")
            else:
                status(f"Игра завершилась с кодом {code} — см. лог")
                self.q.put(("error", f"Игра завершилась с ошибкой (код {code}).\n"
                                     f"Подробности: {self.root_dir / 'logs' / 'latest.log'}"))
        except Exception as e:
            log(traceback.format_exc())
            status("Ошибка")
            self.q.put(("restore",))
            self.q.put(("error", str(e)))
        finally:
            self.q.put(("done",))

    def _apply_profile(self, profile: str, log) -> None:
        """Применяет профиль производительности один раз (при смене профиля)."""
        key = core.resolve_profile(profile)
        if not key or self.settings.get("applied_profile") == key:
            return
        core.set_options(self.root_dir, core.PROFILES[key])
        self.settings["applied_profile"] = key
        core.save_settings(self.root_dir, self.settings)
        log(f"Применён профиль производительности: {key}")

    def run(self) -> None:
        self.win.mainloop()


if __name__ == "__main__":
    # DPI-awareness намеренно НЕ включаем: раскладка фиксирована в пикселях,
    # Windows сам масштабирует окно целиком на HiDPI-экранах.
    try:
        # Свой идентификатор приложения: без него Windows группирует окно под pythonw.exe
        # и показывает на панели задач значок Python вместо нашего.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Luno.Launcher.1")  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        App().run()
    except Exception:  # при запуске через pythonw ошибок не видно - пишем в файл
        import pathlib
        pathlib.Path(__file__).resolve().parent.joinpath("launcher_error.log").write_text(
            traceback.format_exc(), encoding="utf-8")
        raise
