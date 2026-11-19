"""
SnowVPN — Мой VPN / Прокси для Windows
Новогоднее приложение с рабочими вкладками, анимациями и звуком
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import socket
import threading
import time
import os
import struct
import socketserver
import random
import math
import winsound
import urllib.request
import urllib.error
import base64
import ctypes
from datetime import datetime
from PIL import Image, ImageTk

# Загружаем фон один раз (чтобы не удалялся сборщиком мусора)
BG_IMAGE = None
def _find_bg():
    import sys as _sys
    candidates = ["background.png"]
    # для PyInstaller --onefile файл лежит во временной папке _MEIPASS
    if getattr(_sys, "_MEIPASS", None):
        candidates.append(os.path.join(_sys._MEIPASS, "background.png"))
    # рядом с исполняемым файлом
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(_sys.argv[0])), "background.png"))
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

try:
    _bg_path = _find_bg()
    if _bg_path:
        BG_IMAGE = ImageTk.PhotoImage(Image.open(_bg_path).convert("RGB"))
    else:
        print("Фон не найден")
except Exception as e:
    print("Фон не загружен:", e)

# -----------------------------
# Константы
# -----------------------------
CONFIG_FILE = "config.json"
LOCAL_PROXY_PORT = 8080
USER_ID = socket.gethostname()

APP_TITLE = "SnowVPN — Мой VPN / Прокси"
APP_VERSION = "1.0"

# --- Общий статус подключений через GitHub (бесплатная «база данных») ---
# Токен читается из файла token.txt рядом с приложением (НЕ вшит в код —
# иначе GitHub заблокирует загрузку из-за обнаруженного секрета).
TOKEN_FILE = "token.txt"
def _load_token():
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""

GITHUB_TOKEN = _load_token()
GITHUB_REPO = "jkun1337-max/my-vpn-app"   # твой репозиторий
STATUS_FILE = "status.json"
STATUS_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{STATUS_FILE}"
STATUS_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATUS_FILE}"
DISPLAY_NAME = socket.gethostname()  # имя этого компа — будет видно в списке
MAX_PER_PROXY = 3   # максимум человек на один прокси

# Цвета (новогодняя синяя тема)
BG_DARK = "#0b1220"
SIDEBAR_BG = "#0f172a"
CARD_BG = "#131c2e"
CARD_BG2 = "#16203a"
ACCENT = "#38bdf8"
ACCENT2 = "#0ea5e9"
SUCCESS = "#22c55e"
SUCCESS2 = "#16a34a"
ERROR = "#ef4444"
WARNING = "#eab308"
TEXT = "#e2e8f0"
TEXT_MUTED = "#8b98ad"
BORDER = "#1e293b"

# Вшитые прокси (чтобы работало даже без config.json у друга)
BUILTIN_PROXIES = [
    {"host": "138.219.122.200", "port": 9148, "user": "7Kufgp", "password": "KJwuh8", "country": "Канада", "type": "socks5"},
    {"host": "200.71.127.25", "port": 9979, "user": "7Kufgp", "password": "KJwuh8", "country": "Канада", "type": "socks5"},
    {"host": "168.196.237.162", "port": 9302, "user": "7Kufgp", "password": "KJwuh8", "country": "Канада", "type": "socks5"},
    {"host": "168.196.237.129", "port": 9946, "user": "7Kufgp", "password": "KJwuh8", "country": "Канада", "type": "socks5"},
    {"host": "193.32.154.106", "port": 9239, "user": "2t0GU9", "password": "B4fozL", "country": "Украина", "type": "socks5"},
    {"host": "193.32.152.105", "port": 9989, "user": "2t0GU9", "password": "B4fozL", "country": "Украина", "type": "socks5"},
]

DEFAULT_CONFIG = {
    "proxies": [dict(p) for p in BUILTIN_PROXIES],
    "whitelist": ["discord.com", "discordapp.com"],
    "last_country": "",
    "auto_connect": False,
    "sound_enabled": True,
    "transparent_mode": False,
    "connect_count": 0
}

# -----------------------------
# Модели данных
# -----------------------------
class ProxyEntry:
    def __init__(self, host, port, user="", password="", country="", ptype="http", busy=False, used_by="", latency=None):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.country = country
        self.type = ptype
        self.busy = busy
        self.used_by = used_by
        self.latency = latency

    def to_dict(self):
        return {
            "host": self.host, "port": self.port, "user": self.user,
            "password": self.password, "country": self.country, "type": self.type,
            "busy": self.busy, "used_by": self.used_by, "latency": self.latency
        }

    @staticmethod
    def from_dict(d):
        return ProxyEntry(
            host=d.get("host", ""), port=int(d.get("port", 0)),
            user=d.get("user", ""), password=d.get("password", ""),
            country=d.get("country", ""), ptype=d.get("type", "http"),
            busy=d.get("busy", False), used_by=d.get("used_by", ""),
            latency=d.get("latency")
        )

# -----------------------------
# Конфиг
# -----------------------------
class ConfigManager:
    def __init__(self):
        self.proxies = []
        self.whitelist = []
        self.last_country = ""
        self.auto_connect = False
        self.sound_enabled = True
        self.transparent_mode = False
        self.connect_count = 0
        self.selected_proxy = None
        self.start_time = time.time()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                loaded = data.get("proxies", [])
                # Если в файле нет прокси — берём вшитые
                self.proxies = [ProxyEntry.from_dict(p) for p in loaded] if loaded else [ProxyEntry.from_dict(p) for p in BUILTIN_PROXIES]
                self.whitelist = data.get("whitelist", ["discord.com", "discordapp.com"])
                self.last_country = data.get("last_country", "")
                self.auto_connect = data.get("auto_connect", False)
                self.sound_enabled = data.get("sound_enabled", True)
                self.transparent_mode = data.get("transparent_mode", False)
                self.connect_count = data.get("connect_count", 0)
            except Exception as e:
                print("Ошибка загрузки конфига:", e)
                self.proxies = [ProxyEntry.from_dict(p) for p in BUILTIN_PROXIES]
        else:
            self.proxies = [ProxyEntry.from_dict(p) for p in BUILTIN_PROXIES]
            self.whitelist = ["discord.com", "discordapp.com"]
            self.save()

    def save(self):
        data = {
            "proxies": [p.to_dict() for p in self.proxies],
            "whitelist": self.whitelist,
            "last_country": self.last_country,
            "auto_connect": self.auto_connect,
            "sound_enabled": self.sound_enabled,
            "transparent_mode": self.transparent_mode,
            "connect_count": self.connect_count
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_available(self, country=None):
        result = []
        for p in self.proxies:
            if p.busy:
                continue
            if country and p.country != country:
                continue
            result.append(p)
        return result

    def get_by_country(self, country):
        return [p for p in self.proxies if p.country == country]

    def mark_busy(self, proxy, user):
        proxy.busy = True
        proxy.used_by = user

    def mark_free(self, proxy):
        proxy.busy = False
        proxy.used_by = ""

    def ping_proxy(self, proxy, timeout=3):
        try:
            start = time.time()
            sock = socket.create_connection((proxy.host, proxy.port), timeout=timeout)
            sock.close()
            return int((time.time() - start) * 1000)
        except Exception:
            return None

    def is_whitelisted(self, host):
        host = host.lower()
        for w in self.whitelist:
            w = w.lower().strip()
            if not w:
                continue
            if host == w or host.endswith("." + w):
                return True
        return False


# -----------------------------
# Общий статус подключений (GitHub как база данных)
# -----------------------------
class SharedStatus:
    def __init__(self):
        self.connections = []  # [{"user", "proxy", "country", "since"}]
        self.commands = {}     # {"имя": {"action", "host", "port"}}

    def load(self):
        if not GITHUB_TOKEN:
            return
        try:
            req = urllib.request.Request(STATUS_RAW_URL, headers={"User-Agent": "SnowVPN"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
                self.connections = data.get("connections", [])
                self.commands = data.get("commands", {})
        except Exception:
            pass

    def save(self):
        if not GITHUB_TOKEN:
            return False
        try:
            # сперва подтягиваем свежую версию, чтобы не затирать чужие изменения
            self.load()
            payload = json.dumps({"connections": self.connections,
                                  "commands": self.commands},
                                 ensure_ascii=False, indent=2).encode("utf-8")
            body = {
                "message": "SnowVPN: update",
                "content": base64.b64encode(payload).decode("ascii")
            }
            try:
                req = urllib.request.Request(STATUS_API_URL,
                    headers={"User-Agent": "SnowVPN",
                             "Authorization": f"Bearer {GITHUB_TOKEN}"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    cur = json.loads(r.read().decode("utf-8"))
                    body["sha"] = cur.get("sha")
            except Exception:
                pass
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(STATUS_API_URL, data=data, method="PUT",
                headers={"User-Agent": "SnowVPN",
                         "Authorization": f"Bearer {GITHUB_TOKEN}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return True
        except Exception as e:
            print("Ошибка сохранения статуса:", e)
            return False

    def add(self, proxy):
        """Локальное подключение — от имени этого компа"""
        self.add_manual(proxy, DISPLAY_NAME)

    def add_manual(self, proxy, name):
        """Подключение от заданного имени (команда с веб-панели)"""
        self.load()
        self.connections = [c for c in self.connections if c.get("user") != name]
        self.connections.append({
            "user": name,
            "proxy": f"{proxy.host}:{proxy.port}",
            "country": proxy.country,
            "since": datetime.now().strftime("%H:%M:%S")
        })
        return self.save()

    def remove(self):
        self.load()
        self.connections = [c for c in self.connections if c.get("user") != DISPLAY_NAME]
        return self.save()

    def commands_for_me(self):
        """Вернуть команду для этого компа (по имени компа или любую первую)"""
        if not self.commands:
            return None
        # ищем по имени компа
        if DISPLAY_NAME in self.commands:
            return self.commands[DISPLAY_NAME]
        # иначе берём первую (для веб-панели с ручным именем)
        return next(iter(self.commands.values()), None)

    def clear_command(self):
        self.load()
        self.commands = {}
        return self.save()

    def count_on(self, proxy):
        key = f"{proxy.host}:{proxy.port}"
        return sum(1 for c in self.connections if c.get("proxy") == key)

    def users_on(self, proxy):
        key = f"{proxy.host}:{proxy.port}"
        return [c.get("user") for c in self.connections if c.get("proxy") == key]


# -----------------------------
# Локальный прокси-сервер
# -----------------------------
class LocalProxyHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self._handle_one()
        except Exception as e:
            print("Ошибка обработки:", e)

    def _handle_one(self):
        line = self.rfile.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            return
        if line.upper().startswith("CONNECT"):
            self._handle_connect(line)
        else:
            self._handle_http(line)

    def _parse_connect(self, line):
        parts = line.split()
        if len(parts) < 2:
            return None, None
        target = parts[1]
        if ":" in target:
            host, port = target.rsplit(":", 1)
            return host, int(port)
        return target, 443

    def _handle_connect(self, line):
        host, port = self._parse_connect(line)
        if not host:
            self.wfile.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return
        app = self.server.app
        if app.config.is_whitelisted(host):
            remote = self._connect_direct(host, port)
        else:
            remote = self._connect_via_proxy(host, port)
        if not remote:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        self._relay(self.connection, remote)

    def _handle_http(self, line):
        parts = line.split()
        if len(parts) < 2:
            self.wfile.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return
        url = parts[1]
        if url.startswith("http://"):
            url = url[7:]
        elif url.startswith("https://"):
            url = url[8:]
        host = url.split("/")[0]
        port = 80
        if ":" in host:
            host, port = host.rsplit(":", 1)
            port = int(port)
        app = self.server.app
        if app.config.is_whitelisted(host):
            remote = self._connect_direct(host, port)
        else:
            remote = self._connect_via_proxy(host, port)
        if not remote:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        try:
            remote.sendall(self._build_request(line, host))
            self._relay(self.connection, remote)
        except Exception:
            pass

    def _build_request(self, first_line, host):
        lines = [first_line, f"Host: {host}"]
        while True:
            h = self.rfile.readline().decode("utf-8", errors="ignore").strip()
            if not h:
                break
            if h.lower().startswith("host:"):
                continue
            lines.append(h)
        lines.append("")
        return ("\r\n".join(lines) + "\r\n").encode("utf-8", errors="ignore")

    def _connect_direct(self, host, port):
        try:
            sock = socket.create_connection((host, port), timeout=10)
            return sock
        except Exception:
            return None

    def _connect_via_proxy(self, host, port):
        app = self.server.app
        proxy = app.config.selected_proxy
        if not proxy:
            return None
        try:
            if proxy.type.lower() == "http":
                return self._http_proxy_connect(proxy, host, port)
            elif proxy.type.lower() == "socks5":
                return self._socks5_connect(proxy, host, port)
        except Exception as e:
            print("Via proxy error:", e)
        return None

    def _http_proxy_connect(self, proxy, host, port):
        sock = socket.create_connection((proxy.host, proxy.port), timeout=10)
        connect_line = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        if proxy.user and proxy.password:
            import base64
            auth = base64.b64encode(f"{proxy.user}:{proxy.password}".encode()).decode()
            connect_line += f"Proxy-Authorization: Basic {auth}\r\n"
        connect_line += "\r\n"
        sock.sendall(connect_line.encode())
        response = sock.recv(4096).decode("utf-8", errors="ignore")
        if "200" not in response.split("\r\n")[0]:
            sock.close()
            return None
        return sock

    def _socks5_connect(self, proxy, host, port):
        sock = socket.create_connection((proxy.host, proxy.port), timeout=10)
        if proxy.user and proxy.password:
            sock.sendall(b"\x05\x02\x00\x02")
        else:
            sock.sendall(b"\x05\x01\x00")
        resp = sock.recv(2)
        if resp[0] != 5:
            sock.close()
            return None
        if proxy.user and proxy.password:
            sock.sendall(b"\x01")
            u = len(proxy.user).to_bytes(1, 'big') + proxy.user.encode()
            p = len(proxy.password).to_bytes(1, 'big') + proxy.password.encode()
            sock.sendall(u + p)
            resp = sock.recv(2)
            if resp[1] != 0:
                sock.close()
                return None
        host_bytes = host.encode()
        addr = b"\x05\x01\x00\x03" + len(host_bytes).to_bytes(1, 'big') + host_bytes + struct.pack(">H", port)
        sock.sendall(addr)
        resp = sock.recv(4)
        if len(resp) < 4 or resp[1] != 0:
            sock.close()
            return None
        atyp = resp[3]
        if atyp == 1:
            sock.recv(4 + 2)
        elif atyp == 3:
            sock.recv(1 + sock.recv(1)[0] + 2)
        elif atyp == 4:
            sock.recv(16 + 2)
        return sock

    def _relay(self, client, remote):
        def forward(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
            try:
                dst.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                dst.close()
            except Exception:
                pass
        t1 = threading.Thread(target=forward, args=(client, remote), daemon=True)
        t2 = threading.Thread(target=forward, args=(remote, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()


class ThreadedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler, app):
        self.app = app
        super().__init__(server_address, handler)


# -----------------------------
# Главное приложение
# -----------------------------
class SnowVPNApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1000x700")
        self.root.resizable(False, False)  # запрет разворачивания на весь экран
        self.root.configure(bg=BG_DARK)
        self._setup_window_style()

        self.config = ConfigManager()
        self.config.load()

        self.shared = SharedStatus()
        self.shared.load()

        self.server_thread = None
        self.server = None
        self.running = False
        self.connected_proxy = None
        self.animation_running = True
        self.pulse_state = 0.0
        self.current_tab = "Главная"

        self._build_ui()
        self._start_pulse()
        self._refresh_all()
        self._start_status_refresh()

        if not GITHUB_TOKEN:
            self.log("⚠️ Вставь GitHub-токен в код, чтобы видеть подключения друга")
        else:
            self.log("✅ Общий статус подключений включён")

        if self.config.auto_connect and self.config.get_available():
            self.root.after(1500, self.quick_connect)

    def _setup_window_style(self):
        """Скруглённые углы окна и запрет максимизации (Windows 10/11)"""
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            # убираем кнопку максимизации
            GWL_STYLE = -16
            WS_MAXIMIZEBOX = 0x00010000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style & ~WS_MAXIMIZEBOX)
            # скруглённые углы (Windows 11)
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_int(DWMWA_WINDOW_CORNER_PREFERENCE),
                ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
                ctypes.sizeof(ctypes.c_int)
            )
        except Exception as e:
            print("Стиль окна не применён:", e)

    # --- Построение интерфейса ---
    def _build_ui(self):
        # Верхняя панель
        top_bar = tk.Frame(self.root, bg=SIDEBAR_BG, height=64)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        top_bar.pack_propagate(False)

        logo_frame = tk.Frame(top_bar, bg=SIDEBAR_BG)
        logo_frame.pack(side=tk.LEFT, padx=20)
        tk.Label(logo_frame, text="❄", bg=SIDEBAR_BG, fg=ACCENT,
                 font=("Segoe UI", 20, "bold")).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(logo_frame, text="SnowVPN", bg=SIDEBAR_BG, fg=ACCENT,
                 font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        tk.Label(logo_frame, text=f"v{APP_VERSION}", bg=SIDEBAR_BG, fg=TEXT_MUTED,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(6, 0), pady=(6, 0))

        tk.Label(top_bar, text="Быстрый · Безопасный · Новогодний",
                 bg=SIDEBAR_BG, fg=TEXT_MUTED,
                 font=("Segoe UI", 11)).pack(side=tk.LEFT, padx=40)

        # Основная область
        main = tk.Frame(self.root, bg=BG_DARK)
        main.pack(fill=tk.BOTH, expand=True)

        # Сайдбар
        self.sidebar = tk.Frame(main, bg=SIDEBAR_BG, width=230)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        self.tab_buttons = {}
        sidebar_items = [
            ("🏠", "Главная", "home"),
            ("🌐", "Серверы", "servers"),
            ("📋", "Белый список", "whitelist"),
            ("⚙️", "Настройки", "settings"),
            ("📊", "Статистика", "stats"),
            ("ℹ️", "О программе", "about"),
        ]
        for icon, text, key in sidebar_items:
            btn = tk.Button(
                self.sidebar, text=f"{icon}  {text}",
                bg=SIDEBAR_BG, fg=TEXT_MUTED,
                activebackground=ACCENT2, activeforeground="white",
                relief="flat", font=("Segoe UI", 11),
                anchor="w", padx=22, pady=12, bd=0, highlightthickness=0,
                cursor="hand2",
                command=lambda k=key, t=text: self.switch_tab(k, t)
            )
            btn.pack(fill=tk.X, padx=8, pady=4)
            self.tab_buttons[key] = btn

        # Контент
        self.content = tk.Frame(main, bg=BG_DARK)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Фреймы вкладок
        self.tabs = {}
        self.snow_canvases = []
        self.tabs["home"] = self._build_home_tab()
        self.tabs["servers"] = self._build_servers_tab()
        self.tabs["whitelist"] = self._build_whitelist_tab()
        self.tabs["settings"] = self._build_settings_tab()
        self.tabs["stats"] = self._build_stats_tab()
        self.tabs["about"] = self._build_about_tab()

        for frame in self.tabs.values():
            frame.pack(fill=tk.BOTH, expand=True)
            frame.pack_forget()
        self.tabs["home"].pack(fill=tk.BOTH, expand=True)
        self.tab_buttons["home"].config(bg=ACCENT, fg="white")

        # Декор на главной вкладке: ёлка и снеговик
        if self.snow_canvases:
            home_canvas = self.snow_canvases[0]
            self._draw_tree(home_canvas, 40, 30)
            self._draw_snowman(home_canvas, 690, 30)

        self._start_snow()

    # --- Слой снега для вкладки ---
    def _add_snow_layer(self, frame):
        canvas = tk.Canvas(frame, bg=BG_DARK, highlightthickness=0)
        canvas.place(x=0, y=0, relwidth=1, relheight=1)
        if BG_IMAGE:
            canvas.create_image(0, 0, image=BG_IMAGE, anchor="nw", tags="bg")
        self.snow_canvases.append(canvas)
        return canvas

    # --- Вкладка: Главная ---
    def _build_home_tab(self):
        frame = tk.Frame(self.content, bg=BG_DARK)
        self._add_snow_layer(frame)

        # Верхние индикаторы
        top = tk.Frame(frame, bg=BG_DARK)
        top.pack(fill=tk.X, padx=25, pady=15)

        self.my_ip_card = self._make_info_card(top, "🛡️", "Ваш IP", "—", ACCENT)
        self.my_ip_card.pack(side=tk.LEFT, padx=(0, 12))
        self.server_card = self._make_info_card(top, "🌐", "Сервер", "Не выбрано", SUCCESS)
        self.server_card.pack(side=tk.LEFT)

        # Карточки слева + кнопка по центру
        mid = tk.Frame(frame, bg=BG_DARK)
        mid.pack(fill=tk.BOTH, expand=True, padx=25, pady=10)

        # Левые карточки
        left_cards = tk.Frame(mid, bg=BG_DARK)
        left_cards.pack(side=tk.LEFT, fill=tk.Y)

        self._make_feature_card(left_cards, "⚡", "Высокая скорость", ACCENT)
        self._make_feature_card(left_cards, "🔒", "Защита данных", SUCCESS)
        self._make_feature_card(left_cards, "🚫", "Без логов", ERROR)

        # Центр — кнопка питания
        center = tk.Frame(mid, bg=BG_DARK)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.power_canvas = tk.Canvas(center, width=260, height=260, bg=BG_DARK, highlightthickness=0)
        self.power_canvas.pack(pady=20)

        self.power_glow = self.power_canvas.create_oval(30, 30, 230, 230, fill="#142033", outline="")
        self.power_ring = self.power_canvas.create_oval(50, 50, 210, 210, fill="#111c2f",
                                                        outline=ACCENT, width=4)
        self.power_icon = self.power_canvas.create_text(130, 130, text="⏻", fill=TEXT,
                                                        font=("Segoe UI", 78))

        self.power_canvas.tag_bind(self.power_ring, "<Button-1>", lambda e: self.toggle_connection())
        self.power_canvas.tag_bind(self.power_icon, "<Button-1>", lambda e: self.toggle_connection())
        self.power_canvas.tag_bind(self.power_glow, "<Button-1>", lambda e: self.toggle_connection())

        self.home_status = tk.Label(center, text="Отключено", bg=BG_DARK, fg=TEXT_MUTED,
                                    font=("Segoe UI", 12))
        self.home_status.pack(pady=(0, 15))

        # Кнопка "Выбрать сервер"
        self.btn_choose_server = tk.Button(
            center, text="☰  Выбрать сервер  ▾",
            bg=CARD_BG2, fg=TEXT, activebackground=ACCENT2,
            relief="flat", font=("Segoe UI", 11), cursor="hand2",
            padx=20, pady=9, bd=0, highlightthickness=1,
            highlightbackground=BORDER,
            command=lambda: self.switch_tab("servers", "Серверы")
        )
        self.btn_choose_server.pack()

        # Нижние переключатели
        bottom = tk.Frame(frame, bg=BG_DARK)
        bottom.pack(fill=tk.X, padx=25, pady=(0, 15))

        self._make_toggle(bottom, "📋", "Белый список", "включено",
                          lambda: self.switch_tab("whitelist", "Белый список"))
        self._make_toggle(bottom, "🔍", "Прозрачный режим",
                          "вкл" if self.config.transparent_mode else "выкл",
                          self.toggle_transparent)
        self.auto_toggle = self._make_toggle(bottom, "⚡", "Автоподключение",
                          "вкл" if self.config.auto_connect else "выкл",
                          self.toggle_auto)
        return frame

    # --- Вкладка: Серверы ---
    def _build_servers_tab(self):
        frame = tk.Frame(self.content, bg=BG_DARK)
        self._add_snow_layer(frame)

        tk.Label(frame, text="🌐  Серверы и прокси", bg=BG_DARK, fg=ACCENT,
                 font=("Segoe UI", 18, "bold")).pack(anchor=tk.W, padx=25, pady=20)

        hint = tk.Label(frame, text="Подключение заполняет прокси по очереди: сначала по 1 человеку на каждый, потом по 2, и так до 3. Колонка «Подключён» показывает, кто где.",
                        bg=BG_DARK, fg=TEXT_MUTED, font=("Segoe UI", 10))
        hint.pack(anchor=tk.W, padx=25)

        # Таблица
        table_frame = tk.Frame(frame, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=15)

        columns = ("host", "port", "country", "users", "latency", "status")
        self.server_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        for col, text, width in [("host", "IP / Host", 150), ("port", "Порт", 65),
                                 ("country", "Страна", 100), ("users", "Подключён", 150),
                                 ("latency", "Скорость", 90), ("status", "Статус", 110)]:
            self.server_tree.heading(col, text=text)
            self.server_tree.column(col, width=width, anchor=tk.CENTER)
        self.server_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.server_tree.tag_configure("busy", foreground=ERROR)
        self.server_tree.tag_configure("free", foreground=SUCCESS)

        # Кнопки (добавление/удаление прокси убрано — прокси вшиты в приложение)
        btn_frame = tk.Frame(frame, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, padx=25, pady=(0, 20))
        self._make_action_btn(btn_frame, "⚡ Проверить скорость", self.check_speed, SUCCESS)
        self._make_action_btn(btn_frame, "🔌 Подключить", self.quick_connect, ACCENT2)
        return frame

    # --- Вкладка: Белый список ---
    def _build_whitelist_tab(self):
        frame = tk.Frame(self.content, bg=BG_DARK)
        self._add_snow_layer(frame)

        tk.Label(frame, text="📋  Белый список сайтов", bg=BG_DARK, fg=ACCENT,
                 font=("Segoe UI", 18, "bold")).pack(anchor=tk.W, padx=25, pady=20)

        info = ("Сайты из этого списка идут НАПРЯМУЮ, без прокси.\n"
                "Discord приложение на Windows тоже идёт напрямую — его не нужно настраивать.\n"
                "Вписывай адреса по одному на строку, например: discord.com")
        tk.Label(frame, text=info, bg=BG_DARK, fg=TEXT_MUTED, font=("Segoe UI", 10),
                 justify=tk.LEFT).pack(anchor=tk.W, padx=25)

        text_frame = tk.Frame(frame, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=15)

        self.whitelist_text = scrolledtext.ScrolledText(
            text_frame, wrap=tk.WORD, bg=BG_DARK, fg=TEXT,
            insertbackground=ACCENT, font=("Consolas", 11), relief="flat",
            highlightbackground=BORDER, highlightthickness=1
        )
        self.whitelist_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.whitelist_text.insert("1.0", "\n".join(self.config.whitelist))

        btn_frame = tk.Frame(frame, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, padx=25, pady=(0, 20))
        self._make_action_btn(btn_frame, "💾 Сохранить", self.save_whitelist, SUCCESS)
        return frame

    # --- Вкладка: Настройки ---
    def _build_settings_tab(self):
        frame = tk.Frame(self.content, bg=BG_DARK)
        self._add_snow_layer(frame)

        tk.Label(frame, text="⚙️  Настройки", bg=BG_DARK, fg=ACCENT,
                 font=("Segoe UI", 18, "bold")).pack(anchor=tk.W, padx=25, pady=20)

        settings_frame = tk.Frame(frame, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        settings_frame.pack(fill=tk.X, padx=25, pady=10)

        self.sound_var = tk.BooleanVar(value=self.config.sound_enabled)
        self._make_check(settings_frame, "🔊  Звук подключения", self.sound_var, self.toggle_sound)

        self.auto_var2 = tk.BooleanVar(value=self.config.auto_connect)
        self._make_check(settings_frame, "⚡  Автоподключение при запуске", self.auto_var2, self.toggle_auto)

        self.transparent_var = tk.BooleanVar(value=self.config.transparent_mode)
        self._make_check(settings_frame, "🔍  Прозрачный режим", self.transparent_var, self.toggle_transparent)

        tk.Label(frame, text=f"Локальный прокси: 127.0.0.1:{LOCAL_PROXY_PORT}\n"
                             f"Текущая версия: {APP_VERSION}\n"
                             "В настройках браузера укажи этот адрес как HTTP-прокси.",
                 bg=BG_DARK, fg=TEXT_MUTED, font=("Segoe UI", 10),
                 justify=tk.LEFT).pack(anchor=tk.W, padx=25, pady=20)
        return frame

    # --- Вкладка: Статистика ---
    def _build_stats_tab(self):
        frame = tk.Frame(self.content, bg=BG_DARK)
        self._add_snow_layer(frame)

        tk.Label(frame, text="📊  Статистика", bg=BG_DARK, fg=ACCENT,
                 font=("Segoe UI", 18, "bold")).pack(anchor=tk.W, padx=25, pady=20)

        stats_frame = tk.Frame(frame, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        stats_frame.pack(fill=tk.X, padx=25, pady=10)

        self.stat_labels = {}
        stats = [
            ("proxy_count", "Всего прокси"),
            ("active_proxy", "Активный прокси"),
            ("connect_count", "Подключений"),
            ("uptime", "Время работы"),
            ("status", "Статус"),
        ]
        for key, text in stats:
            row = tk.Frame(stats_frame, bg=CARD_BG)
            row.pack(fill=tk.X, padx=20, pady=8)
            tk.Label(row, text=text + ":", bg=CARD_BG, fg=TEXT_MUTED,
                     font=("Segoe UI", 11)).pack(side=tk.LEFT)
            val = tk.Label(row, text="—", bg=CARD_BG, fg=TEXT,
                           font=("Segoe UI", 11, "bold"))
            val.pack(side=tk.RIGHT)
            self.stat_labels[key] = val

        # Лог
        log_frame = tk.LabelFrame(frame, text="Лог", bg=CARD_BG, fg=ACCENT,
                                  font=("Segoe UI", 10, "bold"), bd=0,
                                  highlightbackground=BORDER, highlightthickness=1)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=15)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, wrap=tk.WORD,
                                                  bg=BG_DARK, fg=TEXT_MUTED,
                                                  insertbackground=ACCENT,
                                                  font=("Consolas", 9), relief="flat",
                                                  highlightbackground=BORDER, highlightthickness=1,
                                                  state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        return frame

    # --- Вкладка: О программе ---
    def _build_about_tab(self):
        frame = tk.Frame(self.content, bg=BG_DARK)
        self._add_snow_layer(frame)

        tk.Label(frame, text="❄  SnowVPN", bg=BG_DARK, fg=ACCENT,
                 font=("Segoe UI", 28, "bold")).pack(pady=(40, 5))
        tk.Label(frame, text=f"Версия {APP_VERSION}", bg=BG_DARK, fg=TEXT_MUTED,
                 font=("Segoe UI", 11)).pack()

        info = (
            "Красивое новогоднее приложение для подключения\n"
            "через купленные IPv4 Shared прокси.\n\n"
            "Возможности:\n"
            "• Быстрое подключение к самому быстрому прокси\n"
            "• Выбор страны\n"
            "• Белый список сайтов (прямое соединение)\n"
            "• Discord приложение идёт мимо прокси\n"
            "• Звук подключения и новогодние анимации\n\n"
            "Настройка: впиши свои прокси в config.json\n"
            "и укажи в браузере прокси 127.0.0.1:8080"
        )
        tk.Label(frame, text=info, bg=BG_DARK, fg=TEXT, font=("Segoe UI", 11),
                 justify=tk.LEFT).pack(pady=25)
        return frame

    # --- Вспомогательные виджеты ---
    def _make_info_card(self, parent, icon, title, value, color):
        card = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(padx=18, pady=12)
        tk.Label(inner, text=icon, bg=CARD_BG, fg=color,
                 font=("Segoe UI", 22)).pack(side=tk.LEFT, padx=(0, 10))
        text_frame = tk.Frame(inner, bg=CARD_BG)
        text_frame.pack(side=tk.LEFT)
        tk.Label(text_frame, text=title, bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Segoe UI", 9)).pack(anchor=tk.W)
        val = tk.Label(text_frame, text=value, bg=CARD_BG, fg=color,
                       font=("Segoe UI", 11, "bold"))
        val.pack(anchor=tk.W)
        card.value_label = val
        return card

    def _make_feature_card(self, parent, icon, text, color):
        card = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(padx=16, pady=12)
        tk.Label(inner, text=icon, bg=CARD_BG, fg=color,
                 font=("Segoe UI", 20)).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(inner, text=text, bg=CARD_BG, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        card.pack(fill=tk.X, pady=5)
        return card

    def _make_toggle(self, parent, icon, text, value, command):
        frame = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        inner = tk.Frame(frame, bg=CARD_BG)
        inner.pack(padx=14, pady=8)
        tk.Label(inner, text=icon, bg=CARD_BG, fg=ACCENT,
                 font=("Segoe UI", 15)).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(inner, text=text, bg=CARD_BG, fg=TEXT,
                 font=("Segoe UI", 10)).pack(side=tk.LEFT)
        val = tk.Label(inner, text=value, bg=CARD_BG, fg=SUCCESS,
                       font=("Segoe UI", 9))
        val.pack(side=tk.LEFT, padx=(8, 0))
        btn = tk.Button(frame, text="→", bg=CARD_BG, fg=ACCENT, relief="flat",
                        cursor="hand2", font=("Segoe UI", 12), command=command,
                        bd=0, highlightthickness=0)
        btn.pack(side=tk.RIGHT, padx=8)
        frame.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X)
        return frame

    def _make_action_btn(self, parent, text, command, color):
        btn = tk.Button(parent, text=text, command=command,
                        bg=color, fg="white", activebackground=color,
                        activeforeground="white", relief="flat",
                        font=("Segoe UI", 10, "bold"), cursor="hand2",
                        padx=16, pady=9, bd=0, highlightthickness=0)
        btn.pack(side=tk.LEFT, padx=(0, 10))
        return btn

    def _make_check(self, parent, text, var, command):
        cb = tk.Checkbutton(parent, text=text, variable=var, command=command,
                            bg=CARD_BG, fg=TEXT, selectcolor="#1e293b",
                            activebackground=CARD_BG, activeforeground=TEXT,
                            font=("Segoe UI", 11), anchor=tk.W, padx=20, pady=10)
        cb.pack(fill=tk.X)
        return cb

    # --- Переключение вкладок ---
    def switch_tab(self, key, title):
        for k, frame in self.tabs.items():
            frame.pack_forget()
        self.tabs[key].pack(fill=tk.BOTH, expand=True)

        for k, btn in self.tab_buttons.items():
            btn.config(bg=SIDEBAR_BG, fg=TEXT_MUTED)
        self.tab_buttons[key].config(bg=ACCENT, fg="white")

        self._refresh_all()

    # --- Рисуем ёлку и снеговика ---
    def _draw_tree(self, canvas, x, y):
        c = tk.Canvas(canvas.master, width=70, height=85, bg=BG_DARK, highlightthickness=0)
        c.create_rectangle(31, 68, 39, 85, fill="#6b3e2a")
        c.create_polygon(35, 2, 5, 35, 65, 35, fill="#166534", outline="#22c55e")
        c.create_polygon(35, 20, 10, 52, 60, 52, fill="#15803d", outline="#22c55e")
        c.create_polygon(35, 38, 15, 68, 55, 68, fill="#16a34a", outline="#22c55e")
        for lx, ly, color in [(24, 28, "#ef4444"), (46, 30, "#eab308"),
                              (35, 44, "#38bdf8"), (22, 55, "#ef4444"),
                              (48, 56, "#eab308"), (35, 64, "#f472b6")]:
            c.create_oval(lx - 3, ly - 3, lx + 3, ly + 3, fill=color, outline="")
        c.create_oval(31, 0, 39, 8, fill="#fef08a", outline="")
        canvas.create_window(x + 35, y + 42, window=c)

    def _draw_snowman(self, canvas, x, y):
        c = tk.Canvas(canvas.master, width=70, height=85, bg=BG_DARK, highlightthickness=0)
        c.create_oval(12, 48, 58, 85, fill="#f8fafc", outline="#cbd5e1")
        c.create_oval(18, 28, 52, 60, fill="#f8fafc", outline="#cbd5e1")
        c.create_oval(24, 8, 46, 32, fill="#f8fafc", outline="#cbd5e1")
        c.create_rectangle(18, 12, 52, 16, fill="#b91c1c")
        c.create_rectangle(25, 0, 45, 13, fill="#b91c1c")
        c.create_oval(29, 17, 32, 20, fill="#0f172a")
        c.create_oval(38, 17, 41, 20, fill="#0f172a")
        c.create_polygon(35, 21, 45, 24, 35, 26, fill="#f97316")
        c.create_oval(20, 35, 24, 39, fill="#334155")
        c.create_oval(46, 35, 50, 39, fill="#334155")
        canvas.create_window(x + 35, y + 42, window=c)

    # --- Анимация ---
    def _start_snow(self):
        self.snowflakes = []
        for canvas in self.snow_canvases:
            canvas_flakes = []
            for _ in range(30):
                x = random.randint(0, 770)
                y = random.randint(0, 700)
                size = random.randint(8, 14)
                speed = random.uniform(1.0, 2.4)
                flake = canvas.create_text(x, y, text="❄", font=("Segoe UI", size),
                                           fill="#cbd5e1", tags="snow")
                canvas_flakes.append({"id": flake, "x": x, "y": y, "speed": speed})
            self.snowflakes.append(canvas_flakes)
        self._animate_snow()

    def _animate_snow(self):
        if not self.animation_running:
            return
        for canvas_flakes in self.snowflakes:
            for flake in canvas_flakes:
                flake["y"] += flake["speed"]
                flake["x"] += math.sin(time.time() + flake["y"] * 0.01) * 0.4
                if flake["y"] > 650:
                    flake["y"] = -15
                    flake["x"] = random.randint(0, 770)
        # обновляем координаты через canvas из self.snow_canvases
        for i, canvas in enumerate(self.snow_canvases):
            for flake in self.snowflakes[i]:
                canvas.coords(flake["id"], flake["x"], flake["y"])
        self.root.after(35, self._animate_snow)

    def _start_pulse(self):
        self._animate_pulse()

    def _animate_pulse(self):
        if not self.animation_running:
            return
        if self.running:
            self.pulse_state = (self.pulse_state + 0.06) % (2 * math.pi)
            intensity = int(60 + 60 * abs(math.sin(self.pulse_state)))
            color = f"#{intensity:02x}ff{intensity:02x}"
            self.power_canvas.itemconfig(self.power_glow, fill=color)
            self.power_canvas.itemconfig(self.power_ring, outline=SUCCESS2, width=5)
            self.power_canvas.itemconfig(self.power_icon, fill="#ffffff")
        else:
            self.power_canvas.itemconfig(self.power_glow, fill="#142033")
            self.power_canvas.itemconfig(self.power_ring, outline=ACCENT, width=4)
            self.power_canvas.itemconfig(self.power_icon, fill=TEXT)
        self.root.after(50, self._animate_pulse)

    # --- Автообновление общего статуса ---
    def _start_status_refresh(self):
        def loop():
            while True:
                time.sleep(5)
                try:
                    self.shared.load()
                    self.root.after(0, self._refresh_all)
                    self.root.after(0, self._check_web_commands)
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def _check_web_commands(self):
        """Выполняет команды с веб-панели (команда кладётся в status.json)"""
        cmd = self.shared.commands_for_me()
        if not cmd:
            return
        action = cmd.get("action")
        if action == "connect":
            host = cmd.get("host")
            port = int(cmd.get("port", 0))
            # Если уже подключены к другому — сначала отключимся
            if self.running:
                if self.connected_proxy and self.connected_proxy.host == host and self.connected_proxy.port == port:
                    return  # уже подключены к нужному
                self.disconnect()
            proxy = next((p for p in self.config.proxies
                          if p.host == host and p.port == port and not p.busy), None)
            if proxy:
                self.config.selected_proxy = proxy
                self.config.mark_busy(proxy, USER_ID)
                self.config.connect_count += 1
                self.config.save()
                self._start_proxy_server()
                self.running = True
                self.connected_proxy = proxy
                self.shared.add_manual(proxy, DISPLAY_NAME)
                self._refresh_all()
                self._play_connect_sound()
                self.log(f"🌐 Веб-панель: подключено к {host}:{port} ({proxy.country})")
        elif action == "disconnect":
            if self.running:
                self.disconnect()
                self.log("🌐 Веб-панель: отключено")
        # отмечаем команду выполненной
        self.shared.clear_command()

    # --- Логика подключения ---
    def toggle_connection(self):
        if self.running:
            self.disconnect()
        else:
            self.quick_connect()

    def quick_connect(self):
        if self.running:
            return
        available = self.config.get_available()
        if not available:
            messagebox.showerror("Ошибка", "Нет свободных прокси.")
            return

        # Сначала пробуем выбранную страну, если там есть места
        country = self.country_combo.get() or None
        pool = [p for p in available if not country or p.country == country]
        if not pool:
            pool = available  # если в выбранной стране всё занято — берём из всех

        # Равномерно: сначала прокси с МЕНЬШИМ числом подключённых.
        # Так сначала заполняются все по 1 человеку, потом по 2, и т.д.
        best = min(pool, key=lambda p: (self.shared.count_on(p),
                                        p.latency if p.latency is not None else 9999))

        if self.shared.count_on(best) >= MAX_PER_PROXY:
            messagebox.showerror("Ошибка", "Все прокси уже заполнены (по 3 человека).")
            return

        self.config.selected_proxy = best
        self.config.mark_busy(best, USER_ID)
        self.config.last_country = best.country
        self.config.connect_count += 1
        self.config.save()
        self.shared.add(best)
        self._start_proxy_server()
        self.running = True
        self.connected_proxy = best
        self._refresh_all()
        self._play_connect_sound()
        self.log(f"✅ Подключено к {best.host}:{best.port} ({best.country}) "
                 f"[людей на прокси: {self.shared.count_on(best)}]")

    def _start_proxy_server(self):
        if self.running:
            return
        try:
            self.server = ThreadedTCPServer(("127.0.0.1", LOCAL_PROXY_PORT), LocalProxyHandler, self)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            self.log(f"🌐 Локальный прокси на 127.0.0.1:{LOCAL_PROXY_PORT}")
        except OSError as e:
            if hasattr(e, 'winerror') and e.winerror == 10048:
                messagebox.showerror("Ошибка", f"Порт {LOCAL_PROXY_PORT} уже занят.")
            else:
                messagebox.showerror("Ошибка", str(e))

    def disconnect(self):
        if not self.running:
            return
        self.shared.remove()
        if self.config.selected_proxy:
            self.config.mark_free(self.config.selected_proxy)
            self.config.selected_proxy = None
            self.config.save()
        try:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
        except Exception:
            pass
        self.running = False
        self.server = None
        self.connected_proxy = None
        self._refresh_all()
        self._play_disconnect_sound()
        self.log("🔌 Отключено")

    # --- Управление прокси ---
    def add_proxy(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Добавить прокси")
        dialog.geometry("380x400")
        dialog.resizable(False, False)
        dialog.configure(bg=BG_DARK)
        dialog.transient(self.root)
        dialog.grab_set()

        fields = {}
        labels = [("Host (IP):", ""), ("Порт:", ""), ("Страна:", ""),
                  ("Тип (http/socks5):", "http"), ("Логин:", ""), ("Пароль:", "")]
        for label, default in labels:
            tk.Label(dialog, text=label, bg=BG_DARK, fg=TEXT,
                     font=("Segoe UI", 10)).pack(pady=(10, 0), anchor=tk.W, padx=20)
            ent = tk.Entry(dialog, bg=CARD_BG, fg=TEXT, insertbackground=ACCENT,
                           relief="flat", font=("Segoe UI", 10))
            ent.insert(0, default)
            ent.pack(fill=tk.X, padx=20, pady=3)
            fields[label] = ent

        def save():
            try:
                host = fields["Host (IP):"].get().strip()
                port = int(fields["Порт:"].get().strip())
                country = fields["Страна:"].get().strip()
                ptype = fields["Тип (http/socks5):"].get().strip().lower()
                user = fields["Логин:"].get().strip()
                password = fields["Пароль:"].get().strip()
                if not host or not country:
                    messagebox.showerror("Ошибка", "Заполни хост и страну", parent=dialog)
                    return
                self.config.proxies.append(ProxyEntry(host, port, user, password, country, ptype))
                self.config.save()
                self._refresh_all()
                self.log(f"➕ Добавлен прокси {host}:{port} ({country})")
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("Ошибка", str(e), parent=dialog)

        btn_frame = tk.Frame(dialog, bg=BG_DARK)
        btn_frame.pack(pady=18)
        tk.Button(btn_frame, text="Сохранить", command=save, bg=SUCCESS, fg="white",
                  relief="flat", font=("Segoe UI", 10, "bold"), cursor="hand2",
                  padx=20, pady=7, bd=0).pack(side=tk.LEFT, padx=8)
        tk.Button(btn_frame, text="Отмена", command=dialog.destroy, bg=CARD_BG, fg=TEXT,
                  relief="flat", font=("Segoe UI", 10), cursor="hand2",
                  padx=20, pady=7, bd=0).pack(side=tk.LEFT, padx=8)

    def delete_proxy(self):
        selected = self.server_tree.selection()
        if not selected:
            messagebox.showinfo("Внимание", "Выбери прокси для удаления")
            return
        item = self.server_tree.item(selected[0])
        host, port = item["values"][0], item["values"][1]
        self.config.proxies = [p for p in self.config.proxies
                               if not (p.host == host and p.port == port)]
        if self.config.selected_proxy and self.config.selected_proxy.host == host:
            self.disconnect()
        self.config.save()
        self._refresh_all()
        self.log("🗑 Прокси удалён")

    def check_speed(self):
        if not self.config.proxies:
            messagebox.showinfo("Информация", "Нет прокси для проверки")
            return
        self.log("⚡ Проверка скорости...")
        for p in self.config.proxies:
            p.latency = self.config.ping_proxy(p, timeout=3)
        self.config.save()
        self._refresh_all()
        self.log("✅ Проверка скорости завершена")

    def save_whitelist(self):
        text = self.whitelist_text.get("1.0", tk.END).strip()
        self.config.whitelist = [x.strip() for x in text.splitlines() if x.strip()]
        self.config.save()
        messagebox.showinfo("Готово", "Белый список сохранён")
        self.log(f"📋 Белый список: {', '.join(self.config.whitelist)}")

    # --- Переключатели ---
    def toggle_auto(self):
        self.config.auto_connect = self.auto_var2.get()
        self.config.save()
        self.log(f"⚡ Автоподключение: {'вкл' if self.config.auto_connect else 'выкл'}")

    def toggle_sound(self):
        self.config.sound_enabled = self.sound_var.get()
        self.config.save()
        self.log(f"🔊 Звук: {'вкл' if self.config.sound_enabled else 'выкл'}")

    def toggle_transparent(self):
        self.config.transparent_mode = not self.config.transparent_mode
        self.config.save()
        self.log(f"🔍 Прозрачный режим: {'вкл' if self.config.transparent_mode else 'выкл'}")
        self._refresh_all()

    # --- Звук ---
    def _play_connect_sound(self):
        if not self.config.sound_enabled:
            return
        try:
            winsound.Beep(700, 150)
            time.sleep(0.05)
            winsound.Beep(1100, 350)
        except Exception:
            pass

    def _play_disconnect_sound(self):
        if not self.config.sound_enabled:
            return
        try:
            winsound.Beep(500, 200)
        except Exception:
            pass

    # --- Лог ---
    def log(self, msg):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # --- Обновление данных ---
    def _refresh_all(self):
        # Таблица серверов
        for item in self.server_tree.get_children():
            self.server_tree.delete(item)
        for p in self.config.proxies:
            status = "Занят" if p.busy else "Свободен"
            tag = "busy" if p.busy else "free"
            lat = f"{p.latency} мс" if p.latency is not None else "—"
            users = self.shared.users_on(p)
            users_text = ", ".join(users) if users else "—"
            self.server_tree.insert("", tk.END,
                                    values=(p.host, p.port, p.country, users_text, lat, status),
                                    tags=(tag,))

        # Статус на главной
        if self.running and self.connected_proxy:
            p = self.connected_proxy
            self.home_status.config(text=f"Подключено: {p.host} ({p.country})", fg=SUCCESS)
            self.my_ip_card.value_label.config(text="Защищён", fg=SUCCESS)
            self.server_card.value_label.config(text=p.country, fg=SUCCESS)
        else:
            self.home_status.config(text="Отключено", fg=TEXT_MUTED)
            self.my_ip_card.value_label.config(text="—", fg=ACCENT)
            self.server_card.value_label.config(text="Не выбрано", fg=SUCCESS)

        # Статистика
        self.stat_labels["proxy_count"].config(text=str(len(self.config.proxies)))
        self.stat_labels["active_proxy"].config(
            text=self.connected_proxy.host if self.connected_proxy else "—")
        self.stat_labels["connect_count"].config(text=str(self.config.connect_count))
        uptime = int(time.time() - self.config.start_time)
        self.stat_labels["uptime"].config(text=f"{uptime // 60} мин {uptime % 60} сек")
        self.stat_labels["status"].config(
            text="Подключено" if self.running else "Отключено",
            fg=SUCCESS if self.running else ERROR)


if __name__ == "__main__":
    root = tk.Tk()
    app = SnowVPNApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.disconnect(), root.destroy()))
    root.mainloop()