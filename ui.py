"""Luno Launcher - отрисовка интерфейса на Canvas (блочный «майнкрафтовый» стиль).

Модуль не импортирует tkinter: все функции работают с любым объектом,
у которого есть методы create_rectangle / create_polygon / create_text / ...
"""
from __future__ import annotations

import math
import random

W, H = 1000, 620

GREEN_EDGE = "#1e6830"
WHITE = "#ffffff"
INK = "#0e1014"
MUTED = "#9aa3b5"
PLAY_GREEN = "#5fcb4c"


def shade(hexcolor: str, f: float) -> str:
    """f < 1 - темнее, f > 1 - светлее."""
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if f < 1:
        r, g, b = int(r * f), int(g * f), int(b * f)
    else:
        k = f - 1
        r, g, b = int(r + (255 - r) * k), int(g + (255 - g) * k), int(b + (255 - b) * k)
    return f"#{r:02x}{g:02x}{b:02x}"


def make_background(w: int = W, h: int = H):
    """Зелёный фон со светлым свечением в центре и бледными «пикселями»."""
    from PIL import Image, ImageDraw
    sw, sh = w // 4, h // 4
    inner, outer = (150, 229, 128), (28, 100, 46)
    small = Image.new("RGB", (sw, sh))
    px = small.load()
    cx, cy = sw * 0.5, sh * 0.5
    maxd = math.hypot(sw * 0.62, sh * 0.78)
    for y in range(sh):
        for x in range(sw):
            t = min(1.0, math.hypot(x - cx, (y - cy) * 1.1) / maxd) ** 0.95
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(inner, outer))
    img = small.resize((w, h), Image.BICUBIC).convert("RGBA")
    rnd = random.Random(7)
    over = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for _ in range(46):
        s = rnd.choice((16, 24, 32, 40))
        x, y = rnd.randrange(0, w - s), rnd.randrange(0, h - s)
        d.rectangle((x, y, x + s, y + s), fill=(255, 255, 255, rnd.randrange(8, 24)))
    return Image.alpha_composite(img, over).convert("RGB")


# ----------------------------------------------------------------- примитивы --
def text(cv, x, y, s, font, fill=WHITE, anchor="w", tags=(), shadow=True):
    ids = []
    if shadow:
        ids.append(cv.create_text(x + 2, y + 2, text=s, font=font, fill="#0b1f10", anchor=anchor, tags=tags))
    ids.append(cv.create_text(x, y, text=s, font=font, fill=fill, anchor=anchor, tags=tags))
    return ids[-1], ids


def panel(cv, x1, y1, x2, y2, fill, tag=None, hover=None, shadow=True):
    """Блочная панель со скошенными «пиксельными» углами, бликом и тенью."""
    t = (tag,) if tag else ()
    if shadow:
        cv.create_rectangle(x1 + 4, y1 + 10, x2 + 4, y2 + 8, fill="#175024", outline="", tags=t)
    b = "#0b0d11"
    cv.create_rectangle(x1 + 4, y1, x2 - 4, y2, fill=b, outline="", tags=t)
    cv.create_rectangle(x1, y1 + 4, x2, y2 - 4, fill=b, outline="", tags=t)
    body = cv.create_rectangle(x1 + 4, y1 + 4, x2 - 4, y2 - 4, fill=fill, outline="", tags=t)
    hi = cv.create_rectangle(x1 + 4, y1 + 4, x2 - 4, y1 + 8, fill=shade(fill, 1.22), outline="", tags=t)
    lo = cv.create_rectangle(x1 + 4, y2 - 8, x2 - 4, y2 - 4, fill=shade(fill, 0.72), outline="", tags=t)
    return {"body": body, "hi": hi, "lo": lo, "fill": fill, "hover": hover or shade(fill, 1.14),
            "box": (x1, y1, x2, y2)}


def set_fill(cv, p, color):
    cv.itemconfigure(p["body"], fill=color)
    cv.itemconfigure(p["hi"], fill=shade(color, 1.22))
    cv.itemconfigure(p["lo"], fill=shade(color, 0.72))


def avatar(cv, x, y, px=6):
    """Пиксельная голова 8x8 (без чужих скинов и логотипов)."""
    skin, hair, eye, mouth = "#c68c63", "#4a2f1b", "#3b3ba8", "#8a4b32"
    grid = ["HHHHHHHH", "HHHHHHHH", "HSSSSSSH", "SSSSSSSS", "SESSSSES", "SSSSSSSS", "SSMMMMSS", "SSSSSSSS"]
    col = {"H": hair, "S": skin, "E": eye, "M": mouth}
    for j, row in enumerate(grid):
        for i, c in enumerate(row):
            cv.create_rectangle(x + i * px, y + j * px, x + (i + 1) * px, y + (j + 1) * px,
                                fill=col[c], outline="")


def grass_block(cv, cx, cy, s, tags=(), seed=3, grid=6):
    """Изометрический блок травы из мелких «пикселей»."""
    rnd = random.Random(seed)
    a = s * 0.866
    h = a * 0.5

    def vary(rgb, amt=16):
        d = rnd.randint(-amt, amt)
        return "#%02x%02x%02x" % tuple(max(0, min(255, c + d)) for c in rgb)

    def cells(origin, ue, ve, color_fn):
        ox, oy = origin
        for i in range(grid):
            for j in range(grid):
                u0, u1, v0, v1 = i / grid, (i + 1) / grid, j / grid, (j + 1) / grid
                pts = []
                for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
                    pts += [ox + u * ue[0] + v * ve[0], oy + u * ue[1] + v * ve[1]]
                cv.create_polygon(*pts, fill=color_fn(i, j), outline="", tags=tags)

    n = (cx, cy - s / 2 - h)
    w_ = (cx - a, cy - s / 2)
    cells(n, (a, h), (-a, h), lambda i, j: vary((104, 190, 62)))
    dirt = (136, 96, 66)
    grass = (96, 178, 56)
    cells(w_, (a, h), (0, s), lambda i, j: vary(grass if j == 0 else dirt, 12) if j != 1 or rnd.random() < .5
          else vary(grass, 12))
    s_ = (cx, cy - s / 2 + h)
    cells(s_, (a, -h), (0, s), lambda i, j: shade(vary(grass if j == 0 else dirt, 12), 0.78))
    outline = [cx, cy - s / 2 - h, cx + a, cy - s / 2, cx + a, cy + s / 2, cx, cy + s / 2 + h,
               cx - a, cy + s / 2, cx - a, cy - s / 2, cx, cy - s / 2 - h]
    cv.create_line(*outline, fill="#16240f", width=3, tags=tags)
    cv.create_line(cx - a, cy - s / 2, cx, cy - s / 2 + h, cx + a, cy - s / 2, fill="#16240f", width=2, tags=tags)
    cv.create_line(cx, cy - s / 2 + h, cx, cy + s / 2 + h, fill="#16240f", width=2, tags=tags)


def folder_icon(cv, x, y, color="#ffd34d", tags=()):
    cv.create_rectangle(x, y, x + 34, y + 12, fill=shade(color, 0.8), outline="#1a1a1a", width=2, tags=tags)
    cv.create_rectangle(x, y + 8, x + 70, y + 52, fill=color, outline="#1a1a1a", width=2, tags=tags)
    cv.create_rectangle(x + 4, y + 12, x + 66, y + 18, fill=shade(color, 1.35), outline="", tags=tags)


def check_icon(cv, x, y, tags=()):
    cv.create_rectangle(x, y, x + 56, y + 56, fill="#ffffff", outline="#1a1a1a", width=3, tags=tags)
    cv.create_line(x + 12, y + 30, x + 24, y + 42, x + 46, y + 14, fill="#2f9e44", width=8, tags=tags)


# -------------------------------------------------------------------- сцена --
def build_scene(cv, F, info: dict) -> dict:
    """Рисует весь экран. Возвращает id элементов, которые потом обновляются."""
    r: dict = {}
    name = info["server_name"]

    # заголовок
    text(cv, 28, 40, name.upper(), F(24), WHITE, "w")
    text(cv, 30, 68, "ЛАУНЧЕР", F(10), "#d6f5cf", "w")

    # --- верхняя панель
    r["srv_panel"] = panel(cv, 420, 24, 590, 84, "#1c1f26")
    r["srv_num"], _ = text(cv, 442, 46, "...", F(20), "#6bff7a", "w")
    r["srv_lbl"], _ = text(cv, 442, 70, "проверяю", F(9), MUTED, "w", shadow=False)

    r["acc_panel"] = panel(cv, 602, 24, 840, 84, "#1c1f26")
    avatar(cv, 616, 36)
    r["nick_xy"] = (676, 34)
    text(cv, 678, 71, "Аккаунт Luno · офлайн", F(8), MUTED, "w", shadow=False)

    r["gear"] = panel(cv, 850, 24, 910, 84, "#1c1f26", tag="btn_gear")
    text(cv, 880, 54, "⚙", F(22), WHITE, "center", tags=("btn_gear",), shadow=False)
    r["log"] = panel(cv, 920, 24, 980, 84, "#3c7d2a", tag="btn_log")
    text(cv, 950, 54, "ЛОГ", F(11), WHITE, "center", tags=("btn_log",))

    # --- карточки слева
    cards = [("btn_folder", "Папка игры", "#2d6bd1", 112),
             ("btn_mods", "Папка модов", "#d6482f", 244),
             ("btn_verify", "Проверка файлов", "#7a4fd0", 376)]
    for tag, label, color, y in cards:
        p = panel(cv, 24, y, 214, y + 118, color, tag=tag)
        r[tag] = p
        cv.create_rectangle(28, y + 78, 210, y + 114, fill=shade(color, 0.55), outline="", tags=(tag,))
        text(cv, 40, y + 97, label, F(11), WHITE, "w", tags=(tag,))
        if tag == "btn_folder":
            folder_icon(cv, 66, y + 16, tags=(tag,))
        elif tag == "btn_mods":
            grass_block(cv, 119, y + 40, 38, tags=(tag,), seed=11, grid=4)
        else:
            check_icon(cv, 92, y + 14, tags=(tag,))

    # --- герой по центру
    cv.create_oval(385, 438, 615, 474, fill="#1c6a2c", outline="")
    grass_block(cv, 500, 292, 160, tags=("hero",))
    text(cv, 500, 470, info["subtitle"], F(11), WHITE, "center")

    # --- баннер (техработы / сообщения); по умолчанию скрыт
    r["banner"] = panel(cv, 230, 92, 740, 126, "#9a6a00", tag="banner")
    r["banner_txt"], _ = text(cv, 485, 109, "", F(10), WHITE, "center", tags=("banner",))

    # --- карточка сервера справа
    r["srv_card"] = panel(cv, 760, 226, 980, 408, "#14261a")
    text(cv, 780, 252, "СЕРВЕР", F(10), "#b6ff6b", "w")
    text(cv, 780, 284, name, F(15), WHITE, "w")
    text(cv, 780, 312, info["server_ip"], F(10), "#c9d4c3", "w", shadow=False)
    text(cv, 780, 334, info["version_line"], F(9), MUTED, "w", shadow=False)
    r["copy"] = panel(cv, 780, 354, 960, 392, "#3c7d2a", tag="btn_copy")
    r["copy_txt"], _ = text(cv, 870, 373, "Скопировать IP", F(11), WHITE, "center", tags=("btn_copy",))

    # --- статус и прогресс
    r["status"], _ = text(cv, 230, 492, "Готов к запуску", F(10), WHITE, "w")
    r["bar"] = (230, 500, 860, 508)
    cv.create_rectangle(230, 500, 860, 508, fill="#10321a", outline="#0b0d11", width=2)
    r["bar_fill"] = cv.create_rectangle(231, 501, 231, 507, fill="#8cff6a", outline="")

    # --- нижняя синяя панель
    r["info"] = panel(cv, 224, 516, 620, 604, "#1f4e9a")
    cv.create_rectangle(240, 528, 318, 592, fill="#2b2118", outline="#0b0d11", width=3)
    grass_block(cv, 279, 556, 30, seed=5, grid=4)
    text(cv, 336, 536, "ИГРАЕМ НА", F(9), "#a9c8ff", "w", shadow=False)
    text(cv, 336, 562, name, F(18), WHITE, "w")
    text(cv, 336, 588, info["version_line"], F(9), "#a9c8ff", "w", shadow=False)

    # --- кнопка «Играть»
    r["play"] = panel(cv, 632, 516, 872, 604, PLAY_GREEN, tag="btn_play", hover="#74dd60")
    r["play_icon"] = cv.create_polygon(672, 544, 672, 578, 702, 561, fill=INK, outline="", tags=("btn_play",))
    r["play_txt"], _ = text(cv, 790, 560, "Играть", F(24), INK, "center", tags=("btn_play",), shadow=False)

    text(cv, 24, 608, "v" + info["launcher_version"], F(8), "#bfe8b8", "w", shadow=False)
    return r
