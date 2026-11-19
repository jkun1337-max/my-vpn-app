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
import sys
import struct
import socketserver
import random
import math
import winsound
import urllib.request
import urllib.error
import base64
import ctypes
import uuid
import winreg
from datetime import datetime
from PIL import Image, ImageTk, ImageDraw
import pystray
from pystray import MenuItem as item

# Путь к фон ищём сразу, но сам PhotoImage создадим позже — когда окно Tk уже есть.
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

BG_IMAGE = None  # создаётся в VPNApp.__init__ после root

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

# База пользователей для входа в приложение (та же, что на сайте)
USERS_DB = [
    {"uid": "user-01", "email": "frost.wolf@protonmail.com", "password": "Fw9#kL2!vN8@qR", "name": "Пользователь 1"},
    {"uid": "user-02", "email": "north.star@outlook.com",    "password": "Ns3%pT7&wM4#jK", "name": "Пользователь 2"},
    {"uid": "user-03", "email": "polar.bear@gmail.com",      "password": "Pb6@mQ1!zX9%rD", "name": "Пользователь 3"},
    {"uid": "user-04", "email": "snow.owl@yandex.ru",        "password": "So4#vH8&nP2!kL", "name": "Пользователь 4"},
    {"uid": "user-05", "email": "ice.fox@mail.ru",           "password": "If7%rB3@wT6#mQ", "name": "Пользователь 5"},
    {"uid": "user-06", "email": "winter.deer@icloud.com",    "password": "Wd2!yN9@kL5&pV", "name": "Пользователь 6"},
]

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
    {"host": "138.219.122.200", "port": 9148, "user": "7Kufgp", "password": "KJwuh8", "country": "Канада", "type": "http"},
    {"host": "200.71.127.25", "port": 9979, "user": "7Kufgp", "password": "KJwuh8", "country": "Канада", "type": "http"},
    {"host": "168.196.237.162", "port": 9302, "user": "7Kufgp", "password": "KJwuh8", "country": "Канада", "type": "http"},
    {"host": "168.196.237.129", "port": 9946, "user": "7Kufgp", "password": "KJwuh8", "country": "Канада", "type": "http"},
    {"host": "193.32.154.106", "port": 9239, "user": "2t0GU9", "password": "B4fozL", "country": "Украина", "type": "http"},
    {"host": "193.32.152.105", "port": 9989, "user": "2t0GU9", "password": "B4fozL", "country": "Украина", "type": "http"},
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
        self.device_id = ""

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
                self.device_id = data.get("device_id", "")
                if not self.device_id:
                    self.device_id = uuid.uuid4().hex[:12]
            except Exception as e:
                print("Ошибка загрузки конфига:", e)
                self.proxies = [ProxyEntry.from_dict(p) for p in BUILTIN_PROXIES]
        else:
            self.proxies = [ProxyEntry.from_dict(p) for p in BUILTIN_PROXIES]
            self.whitelist = ["discord.com", "discordapp.com"]
            self.device_id = uuid.uuid4().hex[:12]
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
        """Все прокси (или по стране). Занятость определяется по общему статусу, не по локальному busy."""
        result = []
        for p in self.proxies:
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
        self.proxies = []      # список прокси из веб-панели
        self.accounts = []     # список аккаунтов из веб-панели
        self._sha = None       # кэш SHA файла status.json
        self._save_lock = threading.Lock()

    def load(self):
        if not GITHUB_TOKEN:
            return
        try:
            # используем API сразу — он даёт и contenido и SHA
            req = urllib.request.Request(STATUS_API_URL,
                headers={"User-Agent": "SnowVPN",
                         "Authorization": f"Bearer {GITHUB_TOKEN}"})
            with urllib.request.urlopen(req, timeout=3) as r:
                d = json.loads(r.read().decode("utf-8"))
                self._sha = d.get("sha")
                content = json.loads(base64.b64decode(d.get("content", "")))
                self.connections = content.get("connections", [])
                self.commands = content.get("commands", {})
                self.proxies = content.get("proxies", [])
                self.accounts = content.get("accounts", [])
        except Exception:
            pass

    def save(self):
        """Асинхронная запись — не блокирует GUI"""
        if not GITHUB_TOKEN:
            return False
        threading.Thread(target=self._save_sync, daemon=True).start()
        return True

    def _save_sync(self):
        with self._save_lock:
            try:
                # подтягиваем свежий SHA перед записью
                try:
                    req = urllib.request.Request(STATUS_API_URL,
                        headers={"User-Agent": "SnowVPN",
                                 "Authorization": f"Bearer {GITHUB_TOKEN}"})
                    with urllib.request.urlopen(req, timeout=3) as r:
                        d = json.loads(r.read().decode("utf-8"))
                        self._sha = d.get("sha")
                except Exception:
                    pass

                payload = json.dumps({"connections": self.connections,
                                      "commands": self.commands,
                                      "proxies": self.proxies,
                                      "accounts": self.accounts},
                                     ensure_ascii=False, indent=2).encode("utf-8")
                body = {
                    "message": "SnowVPN: update",
                    "content": base64.b64encode(payload).decode("ascii")
                }
                if self._sha:
                    body["sha"] = self._sha
                data = json.dumps(body).encode("utf-8")
                req = urllib.request.Request(STATUS_API_URL, data=data, method="PUT",
                    headers={"User-Agent": "SnowVPN",
                             "Authorization": f"Bearer {GITHUB_TOKEN}",
                             "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3) as r:
                    resp = json.loads(r.read().decode("utf-8"))
                    self._sha = resp.get("content", {}).get("sha", self._sha)
            except Exception as e:
                print("Ошибка сохранения статуса:", e)

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

    def commands_for_me(self, uid):
        """Вернуть команду, адресованную ТОЛЬКО этому аккаунту (по UID)"""
        if not self.commands:
            return None
        return self.commands.get(uid)

    def clear_command(self, uid):
        """Удалить только свою команду, не трогая чужие"""
        self.load()
        if uid in self.commands:
            del self.commands[uid]
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
        global BG_IMAGE
        self.root = root
        # Теперь root есть — можно безопасно создать картинку
        _bg_path = _find_bg()
        if _bg_path:
            try:
                BG_IMAGE = ImageTk.PhotoImage(Image.open(_bg_path).convert("RGB"))
            except Exception as e:
                print("Фон не загружен:", e)
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1000x700")
        self.root.resizable(True, True)  # можно разворачивать на весь экран
        self.root.configure(bg=BG_DARK)

        self.config = ConfigManager()
        self.config.load()

        self.shared = SharedStatus()
        self.shared.load()

        self.server_thread = None
        self.server = None
        self.running = False
        self.connected_proxy = None
        self.connect_start = None
        self.animation_running = True
        self.pulse_state = 0.0
        self.current_tab = "Главная"
        self.tray_icon = None

        self._build_ui()
        # рисуем главную сразу (Configure-event может не сработать сразу)
        self.root.update_idletasks()
        if hasattr(self, "home_canvas"):
            self._redraw_home(self.home_canvas.winfo_width(), self.home_canvas.winfo_height())
        self._refresh_all()
        self._start_status_refresh()
        self._tick_uptime()
        self._setup_tray()

        if not GITHUB_TOKEN:
            self.log("⚠️ Вставь GitHub-токен в код, чтобы видеть подключения друга")
        else:
            self.log("✅ Общий статус подключений включён")

        if self.config.auto_connect and self.config.get_available():
            self.root.after(1500, self.quick_connect)

    # --- Скрытие в системный трей ---
    def _make_tray_image(self):
        img = Image.new("RGB", (64, 64), "#0b1220")
        d = ImageDraw.Draw(img)
        d.ellipse([8, 8, 56, 56], fill="#0ea5e9")
        # простая⑥-иконка снежинки
        d.line([(32, 16), (32, 48)], fill="white", width=4)
        d.line([(16, 32), (48, 32)], fill="white", width=4)
        d.line([(20, 20), (44, 44)], fill="white", width=4)
        d.line([(44, 20), (20, 44)], fill="white", width=4)
        return img

    def _setup_tray(self):
        try:
            menu = pystray.Menu(
                item("Показать", lambda icon, it: self._show_from_tray()),
                item("Выход", lambda icon, it: self._quit_app())
            )
            self.tray_icon = pystray.Icon("SnowVPN", self._make_tray_image(),
                                          "SnowVPN", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            # при закрытии окна — сворачивать в трей
            self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        except Exception as e:
            print("Трей не запущен:", e)

    def _hide_to_tray(self):
        self.root.withdraw()  # скрыть окно

    def _show_from_tray(self):
        self.root.after(0, self.root.deiconify)  # показать окно

    def _quit_app(self):
        if self.running:
            self.root.after(0, self.disconnect)
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.after(0, self.root.destroy)

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

    def _setup_styles(self):
        """Тёмные стили для ttk-виджетов (таблица, комбобоксы)"""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background=CARD_BG, fieldbackground=CARD_BG,
                        foreground=TEXT, borderwidth=0, rowheight=26,
                        font=("Segoe UI", 10))
        style.map("Treeview", background=[("selected", ACCENT)])
        style.configure("Treeview.Heading",
                        background=SIDEBAR_BG, foreground=ACCENT,
                        font=("Segoe UI", 10, "bold"))
        style.configure("TCombobox", fieldbackground=CARD_BG,
                        background=CARD_BG, foreground=TEXT)

    # --- Построение интерфейса ---
    def _build_ui(self):
        self._setup_styles()
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

    # --- Слой снега для вкладки (фон-картинка, самый нижний, не ловит клики) ---
    def _add_snow_layer(self, frame, interactive=True):
        canvas = tk.Canvas(frame, bg=BG_DARK, highlightthickness=0)
        if interactive:
            canvas.pack(fill=tk.BOTH, expand=True)  # главная: клики по canvas
        else:
            # остальные вкладки: фон через place, но не перехватывает клики
            canvas.place(x=0, y=0, relwidth=1, relheight=1)
            canvas.bindtags(("all",))
        self.snow_canvases.append(canvas)
        return canvas

    def _paint_bg(self, canvas, w, h):
        """Масштабирует фон под текущий размер canvas"""
        try:
            src = Image.open(_find_bg()).convert("RGB").resize((w, h))
            self._bg_scaled = ImageTk.PhotoImage(src)
            canvas.create_image(0, 0, image=self._bg_scaled, anchor="nw", tags="bg")
        except Exception:
            if BG_IMAGE:
                canvas.create_image(0, 0, image=BG_IMAGE, anchor="nw", tags="bg")

    # --- Вкладка: Главная (авто-масштаб под размер окна) ---
    def _build_home_tab(self):
        frame = tk.Frame(self.content, bg=BG_DARK)
        c = self._add_snow_layer(frame)
        self.home_canvas = c
        c.bind("<Configure>", lambda e: self._redraw_home(e.width, e.height))
        return frame

    def _redraw_home(self, w, h):
        c = self.home_canvas
        if getattr(self, "_home_size", None) == (w, h):
            return
        self._home_size = (w, h)
        c.delete("all")

        # Чёрный фон (без картинки)
        c.create_rectangle(0, 0, w, h, fill="#080c14", tags="bgfill")

        # Белые точки (статичные, без анимации)
        random.seed(7)
        for _ in range(70):
            x = random.randint(0, w)
            y = random.randint(0, int(h * 0.8))
            rr = random.choice([1, 1, 1, 2])
            br = random.choice(["#2a3446", "#3a4a63", "#50617d"])
            c.create_oval(x, y, x + rr, y + rr, fill=br, tags="dots")

        # Сугроб внизу
        snow_y = int(h * 0.82)
        c.create_polygon(
            0, snow_y + 30,
            int(w * 0.2), snow_y - 10,
            int(w * 0.45), snow_y + 20,
            int(w * 0.7), snow_y - 15,
            w, snow_y + 25,
            w, h, 0, h,
            fill="#dbe6f2", tags="snowhill"
        )

        pad = max(20, int(w * 0.03))
        card_w = max(150, int(w * 0.26))

        # Верхние карточки: IP / Сервер / Время работы
        self._draw_canvas_card(c, pad, pad, card_w, 56, "\U0001f6e1\ufe0f", "Ваш IP", "—", ACCENT, "ip")
        self._draw_canvas_card(c, pad + card_w + 12, pad, card_w, 56, "\U0001f310", "Сервер", "Не выбрано", SUCCESS, "server")
        self._draw_canvas_card(c, pad + 2 * (card_w + 12), pad, card_w, 56,
                               "\u23f1", "Время работы", "00:00:00", WARNING, "uptime")

        # Левые карточки
        for i, (icon, text, color) in enumerate([
            ("\u26a1", "Высокая скорость", ACCENT),
            ("\U0001f512", "Защита данных", SUCCESS),
            ("\U0001f6ab", "Без логов", ERROR),
        ]):
            y = pad + 100 + i * 72
            c.create_rectangle(pad, y, pad + card_w, y + 56, fill="#111a2b", outline="#22304d")
            c.create_text(pad + 18, y + 28, text=icon, fill=color,
                          font=("Segoe UI Emoji", 19), anchor="w")
            c.create_text(pad + 55, y + 28, text=text, fill=TEXT,
                          font=("Segoe UI", 10, "bold"), anchor="w")

        # Переключатель OFF / ON (закруглённый) — центр
        cx, cy = int(w * 0.68), int(h * 0.45)
        tw, th = 220, 84
        self.toggle_bg = c.create_rounded_rectangle if hasattr(c, "create_rounded_rectangle") else None

        def round_rect(x1, y1, x2, y2, r=40, **kw):
            pts = []
            for xx, yy, dir in [(x2, y2, 0), (x1, y2, 1), (x1, y1, 2), (x2, y1, 3)]:
                pass
            # простой скруглённый прямоугольник через полигон+дуги
            return c.create_oval(x1, y1, x1 + 2 * r, y1 + 2 * r, **kw)

        # рисуем «таблетку»
        self.switch_track = c.create_oval(cx - tw // 2, cy - th // 2,
                                          cx - tw // 2 + th, cy + th // 2,
                                          fill="#2a3446", outline="")
        c.create_oval(cx + tw // 2 - th, cy - th // 2,
                      cx + tw // 2, cy + th // 2, fill="#2a3446", outline="")
        c.create_rectangle(cx - tw // 2 + th // 2, cy - th // 2,
                           cx + tw // 2 - th // 2, cy + th // 2, fill="#2a3446", outline="")
        self.switch_off_x = cx - tw // 2 + th // 2
        self.switch_on_x = cx + tw // 2 - th // 2
        self.switch_off_y = cy
        self.switch_on_y = cy
        self.switch_knob = c.create_oval(self.switch_off_x - 34, cy - 34,
                                         self.switch_off_x + 34, cy + 34,
                                         fill="#8899b0", outline="")
        self.switch_label = c.create_text(cx, cy, text="OFF", fill="#cbd5e1",
                                          font=("Segoe UI", 18, "bold"))
        # клик по всей таблетке
        for it in (self.switch_track, self.switch_knob, self.switch_label):
            c.tag_bind(it, "<Button-1>", lambda e: self.toggle_connection())
            c.tag_bind(it, "<Enter>", lambda e: c.config(cursor="hand2"))
            c.tag_bind(it, "<Leave>", lambda e: c.config(cursor=""))

        self.home_status = c.create_text(cx, cy + th // 2 + 28, text="Отключено",
                                         fill=TEXT_MUTED, font=("Segoe UI", 12))

        # Кнопка "Проверить IP"
        bw = 190
        self._draw_canvas_button(c, cx - bw // 2, cy + th // 2 + 50, bw, 42,
                                 "\U0001f50e  Проверить IP",
                                 self.check_ip)

        # Выбор страны
        countries = sorted(set(p.country for p in self.config.proxies)) or ["Нет прокси"]
        self.country_var = tk.StringVar()
        self.country_combo = ttk.Combobox(c, textvariable=self.country_var,
                                          values=countries, state="readonly", width=18)
        if self.config.last_country in countries:
            self.country_combo.set(self.config.last_country)
        else:
            self.country_combo.set(countries[0])
        self.country_combo.bind("<<ComboboxSelected>>", self.on_country_selected)
        c.create_window(cx, cy + th // 2 + 100, window=self.country_combo, anchor="center")

        # Нижние кнопки
        n = 3
        bw2 = min(170, (w - pad * 2 - 20) // n)
        gap = 8
        total = bw2 * n + gap * (n - 1)
        startx = (w - total) // 2
        by = h - 58
        self._draw_canvas_button(c, startx, by, bw2, 44, "\U0001f4cb  Белый список",
                                 lambda: self.switch_tab("whitelist", "Белый список"))
        self._draw_canvas_button(c, startx + bw2 + gap, by, bw2, 44, "\U0001f50d  Прозрачный режим",
                                 self.toggle_transparent)
        self._draw_canvas_button(c, startx + 2 * (bw2 + gap), by, bw2, 44, "\u26a1  Автоподключение",
                                 self.toggle_auto)

        self._refresh_all()

    def _draw_canvas_card(self, c, x, y, w, h, icon, title, value, color, tag):
        c.create_rectangle(x, y, x + w, y + h, fill="#152038", outline="#22304d")
        c.create_text(x + 22, y + h // 2, text=icon, fill=color,
                      font=("Segoe UI Emoji", 20), anchor="w")
        c.create_text(x + 55, y + 18, text=title, fill=TEXT_MUTED,
                      font=("Segoe UI", 9), anchor="w")
        val = c.create_text(x + 55, y + 40, text=value, fill=color,
                            font=("Segoe UI", 11, "bold"), anchor="w")
        setattr(self, f"home_{tag}_val", val)

    def _draw_canvas_button(self, c, x, y, w, h, text, command):
        rect = c.create_rectangle(x, y, x + w, y + h, fill="#1b2a45",
                                  outline="#2e4368", width=1)
        label = c.create_text(x + w // 2, y + h // 2, text=text, fill=TEXT,
                              font=("Segoe UI", 10), anchor="center")
        for item in (rect, label):
            c.tag_bind(item, "<Button-1>", lambda e: command())
            c.tag_bind(item, "<Enter>",
                       lambda e: (c.itemconfig(rect, fill="#24406b"), c.config(cursor="hand2")))
            c.tag_bind(item, "<Leave>",
                       lambda e: (c.itemconfig(rect, fill="#1b2a45"), c.config(cursor="")))

    # --- Вкладка: Серверы (список стран с раскрытием) ---
    def _build_servers_tab(self):
        frame = tk.Frame(self.content, bg=BG_DARK)
        self._add_snow_layer(frame, interactive=False)

        tk.Label(frame, text="🌐  Серверы", bg=BG_DARK, fg=ACCENT,
                 font=("Segoe UI", 20, "bold")).pack(anchor=tk.W, padx=25, pady=(18, 4))
        tk.Label(frame, text="Выбери страну, чтобы увидеть серверы и подключиться",
                 bg=BG_DARK, fg=TEXT_MUTED, font=("Segoe UI", 10)).pack(anchor=tk.W, padx=25)

        # Прокручиваемая область для списка стран
        self.servers_list = tk.Frame(frame, bg=BG_DARK)
        self.servers_list.pack(fill=tk.BOTH, expand=True, padx=25, pady=15)

        self.expanded_country = None
        self._render_server_countries()

        # Кнопка проверки скорости
        btn_frame = tk.Frame(frame, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, padx=25, pady=(0, 18))
        self._make_action_btn(btn_frame, "⚡ Проверить скорость", self.check_speed, SUCCESS)
        return frame

    def _render_server_countries(self):
        """Рисуем список стран; по клику раскрываем серверы этой страны"""
        for w in self.servers_list.winfo_children():
            w.destroy()

        countries = {}
        for p in self.config.proxies:
            countries.setdefault(p.country, []).append(p)

        for country in sorted(countries):
            proxies = countries[country]
            expanded = (self.expanded_country == country)

            # строка страны — кнопка со стрелочкой
            row = tk.Frame(self.servers_list, bg=CARD_BG,
                           highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill=tk.X, pady=4)

            arrow = "▾" if expanded else "▸"
            btn = tk.Button(row, text=f"{arrow}  🌐  {country}",
                            bg=CARD_BG, fg=ACCENT, activebackground=ACCENT2,
                            activeforeground="white", relief="flat",
                            font=("Segoe UI", 12, "bold"), anchor="w",
                            padx=16, pady=12, bd=0, cursor="hand2",
                            command=lambda c=country: self._toggle_country(c))
            btn.pack(fill=tk.X)

            if expanded:
                for p in proxies:
                    people = self.shared.count_on(p)
                    lat = f"{p.latency} мс" if p.latency is not None else "—"
                    srv = tk.Frame(row, bg="#16203a")
                    srv.pack(fill=tk.X, padx=16, pady=2)
                    tk.Label(srv, text=f"⚡ {p.host}:{p.port}", bg="#16203a",
                             fg=TEXT, font=("Consolas", 10), anchor="w").pack(side=tk.LEFT)
                    tk.Label(srv, text=f"  {lat}", bg="#16203a", fg=TEXT_MUTED,
                             font=("Segoe UI", 9)).pack(side=tk.LEFT)
                    tk.Label(srv, text=f"  👥 {people} чел.", bg="#16203a",
                             fg=ACCENT, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
                    con_btn = tk.Button(srv, text="Подключить",
                                        bg=ACCENT, fg="#000",
                                        relief="flat", font=("Segoe UI", 9, "bold"),
                                        cursor="hand2", padx=10, pady=3, bd=0,
                                        command=lambda pr=p: self._connect_to_proxy(pr))
                    con_btn.pack(side=tk.RIGHT)

    def _toggle_country(self, country):
        if self.expanded_country == country:
            self.expanded_country = None
        else:
            self.expanded_country = country
        self._render_server_countries()

    def _connect_to_proxy(self, proxy):
        if self.running:
            messagebox.showinfo("Внимание", "Сначала отключись от текущего прокси")
            return
        self._do_connect(proxy)
        self._render_server_countries()

    # --- Вкладка: Белый список ---
    def _build_whitelist_tab(self):
        frame = tk.Frame(self.content, bg=BG_DARK)
        self._add_snow_layer(frame, interactive=False)

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
        self._add_snow_layer(frame, interactive=False)

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
        self._add_snow_layer(frame, interactive=False)

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
        self._add_snow_layer(frame, interactive=False)

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
    def _create_snowflakes(self, w, h):
        self.snowflakes = []
        if not self.snow_canvases:
            return
        c = self.snow_canvases[0]
        for _ in range(16):
            x = random.randint(0, w)
            y = random.randint(0, h)
            size = random.randint(8, 13)
            speed = random.uniform(0.8, 1.8)
            flake = c.create_text(x, y, text="❄", font=("Segoe UI", size),
                                  fill="#cbd5e1", tags="snow")
            self.snowflakes.append({"id": flake, "x": x, "y": y, "speed": speed})

    def _start_snow(self):
        self.snowflakes = []
        self._snow_loop_started = False
        self._animate_snow()

    def _animate_snow(self):
        if not self.animation_running:
            return
        c = self.snow_canvases[0] if self.snow_canvases else None
        if c and self.snowflakes:
            h = c.winfo_height() or 570
            w = c.winfo_width() or 770
            for flake in self.snowflakes:
                flake["y"] += flake["speed"]
                flake["x"] += math.sin(time.time() + flake["y"] * 0.01) * 0.4
                if flake["y"] > h:
                    flake["y"] = -15
                    flake["x"] = random.randint(0, w)
                c.coords(flake["id"], flake["x"], flake["y"])
        self.root.after(120, self._animate_snow)

    def _start_pulse(self):
        self._animate_pulse()

    def _animate_pulse(self):
        if not self.animation_running:
            return
        if not hasattr(self, "power_glow"):
            self.root.after(100, self._animate_pulse)
            return
        if self.running:
            self.pulse_state = (self.pulse_state + 0.06) % (2 * math.pi)
            intensity = int(60 + 60 * abs(math.sin(self.pulse_state)))
            color = f"#{intensity:02x}ff{intensity:02x}"
            self.home_canvas.itemconfig(self.power_glow, fill=color)
            self.home_canvas.itemconfig(self.power_ring, outline=SUCCESS2, width=5)
            self.home_canvas.itemconfig(self.power_icon, fill="#ffffff")
        else:
            self.home_canvas.itemconfig(self.power_glow, fill="#142033")
            self.home_canvas.itemconfig(self.power_ring, outline=ACCENT, width=4)
            self.home_canvas.itemconfig(self.power_icon, fill=TEXT)
        self.root.after(150, self._animate_pulse)

    # --- Автообновление общего статуса ---
    def _start_status_refresh(self):
        def loop():
            while True:
                time.sleep(15)
                try:
                    self.shared.load()
                    self.root.after(0, self._sync_proxies_from_panel)
                    self.root.after(0, self._refresh_all)
                    self.root.after(0, self._check_web_commands)
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def _sync_proxies_from_panel(self):
        """Синхронизирует список прокси с веб-панелью (общий источник status.json)"""
        # Если в status.json есть список — он главный
        if self.shared.proxies:
            remote = set()
            for entry in self.shared.proxies:
                host = entry.get("host")
                port = int(entry.get("port", 0))
                if not host or not port:
                    continue
                remote.add((host, port))
                # добавляем новый, если его нет
                if not any(p.host == host and p.port == port for p in self.config.proxies):
                    self.config.proxies.append(ProxyEntry(
                        host=host, port=port,
                        user=entry.get("user", ""), password=entry.get("pass", ""),
                        country=entry.get("country", ""), ptype=entry.get("type", "http")
                    ))
                    self.log(f"➕ Веб-панель: добавлен прокси {host}:{port} ({entry.get('country','')})")
            # удаляем те, которых больше нет в панели
            to_remove = [p for p in self.config.proxies if (p.host, p.port) not in remote]
            for p in to_remove:
                self.config.proxies.remove(p)
                if self.connected_proxy and self.connected_proxy.host == p.host and self.connected_proxy.port == p.port:
                    self.root.after(0, self.disconnect)
                self.log(f"🗑 Веб-панель: удалён прокси {p.host}:{p.port}")
            if to_remove or len(self.config.proxies) != len(remote):
                self.config.save()

        # Синхронизируем аккаунты (логин/пароль/ID) из панели
        if self.shared.accounts:
            for acc in self.shared.accounts:
                uid = acc.get("uid", "")
                if not uid:
                    continue
                if not any(u["uid"] == uid for u in USERS_DB):
                    USERS_DB.append({
                        "uid": uid,
                        "email": acc.get("email", ""),
                        "password": acc.get("password", ""),
                        "name": acc.get("name", uid)
                    })
                    self.log(f"👤 Веб-панель: добавлен аккаунт {uid}")

    def _check_web_commands(self):
        """Выполняет ТОЛЬКО команды, адресованные этому аккаунту (по UID)"""
        uid = getattr(self, "my_uid", "")
        if not uid:
            return
        cmd = self.shared.commands_for_me(uid)
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
                          if p.host == host and p.port == port), None)
            if proxy:
                self.config.selected_proxy = proxy
                self.config.connect_count += 1
                self.config.save()
                self._start_proxy_server()
                self.running = True
                self.connected_proxy = proxy
                self.shared.add_manual(proxy, getattr(self, "my_name", DISPLAY_NAME))
                self._refresh_all()
                self._play_connect_sound()
                self.log(f"🌐 Веб-панель: подключено к {host}:{port} ({proxy.country})")
        elif action == "disconnect":
            if self.running:
                self.disconnect()
                self.log("🌐 Веб-панель: отключено")
        # отмечаем ТОЛЬКО свою команду выполненной
        self.shared.clear_command(uid)

    # --- Логика подключения ---
    def toggle_connection(self):
        if self.running:
            self.disconnect()
        else:
            self.quick_connect()

    def _is_free(self, proxy):
        """Свободен ли прокси (0 подключённых в общем статусе)"""
        return self.shared.count_on(proxy) == 0

    def _pick_best(self, pool):
        """Самый быстрый прокси (без проверки занятости)"""
        if not pool:
            return None
        return min(pool, key=lambda p: p.latency if p.latency is not None else 9999)

    def quick_connect(self):
        """Подключение: выбранная страна, самый быстрый прокси"""
        if self.running:
            return
        country = self.country_combo.get() or None
        pool = self.config.get_available(country)
        if not pool:
            messagebox.showerror("Ошибка", "Нет прокси в этой стране.")
            return
        best = self._pick_best(pool)
        if best:
            self._do_connect(best)

    def _do_connect(self, best):
        self.config.selected_proxy = best
        self.config.last_country = best.country
        self.config.connect_count += 1
        self.config.save()
        self.shared.add(best)
        self._start_proxy_server()
        self._set_system_proxy(True)   # включаем системный прокси Windows
        self.running = True
        self.connected_proxy = best
        self.connect_start = time.time()
        self._refresh_all()
        self._play_connect_sound()
        self.log(f"✅ Подключено к {best.host}:{best.port} ({best.country}) "
                 f"[{best.latency if best.latency is not None else '?'} мс]")

    def _set_system_proxy(self, enable):
        """Включает/выключает системный HTTP/HTTPS прокси Windows через реестр"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_WRITE
            )
            if enable:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ,
                                  f"127.0.0.1:{LOCAL_PROXY_PORT}")
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ,
                                  "<local>;localhost;127.0.0.1")
            else:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            # уведомляем Windows об изменении настроек
            try:
                import ctypes
                INTERNET_OPTION_SETTINGS_CHANGED = 39
                INTERNET_OPTION_REFRESH = 37
                ctypes.windll.wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
                ctypes.windll.wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
            except Exception:
                pass
            self.log(f"🖥️ Системный прокси Windows: {'включён' if enable else 'выключен'}")
        except Exception as e:
            self.log(f"⚠️ Не удалось изменить прокси Windows: {e}")

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
        self._set_system_proxy(False)  # выключаем системный прокси Windows
        self.shared.remove()
        if self.config.selected_proxy:
            self.config.selected_proxy = None
            self.config.save()
        self.connect_start = None
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

    def check_ip(self):
        """Показывает текущий IP (через прокси, если включён)"""
        if not self.running:
            messagebox.showinfo("Проверка IP", "VPN выключен — включи его, чтобы увидеть IP прокси.")
            return
        self.log("🔍 Запрашиваем IP...")
        def worker():
            try:
                import urllib.request
                req = urllib.request.Request("https://api.ipify.org?format=json",
                    headers={"User-Agent": "SnowVPN"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = json.loads(r.read().decode("utf-8"))
                    ip = data.get("ip", "?")
                self.root.after(0, lambda: (
                    messagebox.showinfo("Ваш IP сейчас", f"IP: {ip}\nСтрана: {self.connected_proxy.country}\nПрокси: {self.connected_proxy.host}:{self.connected_proxy.port}"),
                    self.log(f"🌐 Текущий IP: {ip}")
                ))
            except Exception as e:
                self.root.after(0, lambda: (
                    messagebox.showerror("Ошибка", f"Не удалось получить IP: {e}\n\nВозможно прокси не работает."),
                    self.log(f"❌ Ошибка получения IP: {e}")
                ))
        threading.Thread(target=worker, daemon=True).start()

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
    def on_country_selected(self, event=None):
        """Смена страны в выпадающем списке"""
        country = self.country_combo.get()
        self.config.last_country = country
        self.config.save()
        # обновляем статус на главной
        total = len(self.config.get_available(country))
        self.home_canvas.itemconfig(
            self.home_status,
            text=f"Страна: {country} · серверов: {total}",
            fill=ACCENT
        )

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
    def _tick_uptime(self):
        """Обновляет время работы прокси каждую секунду"""
        if self.running and self.connect_start and hasattr(self, "home_uptime_val"):
            elapsed = int(time.time() - self.connect_start)
            hh = elapsed // 3600
            mm = (elapsed % 3600) // 60
            ss = elapsed % 60
            self.home_canvas.itemconfig(
                self.home_uptime_val,
                text=f"{hh:02d}:{mm:02d}:{ss:02d}",
                fill=SUCCESS
            )
        self.root.after(1000, self._tick_uptime)

    def _refresh_all(self):
        # Список стран на вкладке «Серверы»
        if hasattr(self, "servers_list") and self.servers_list.winfo_exists():
            self._render_server_countries()

        # Статус на главной + переключатель OFF/ON
        if self.running and self.connected_proxy:
            p = self.connected_proxy
            self.home_canvas.itemconfig(self.home_status,
                                        text=f"Подключено: {p.host} ({p.country})", fill=SUCCESS)
            self.home_canvas.itemconfig(self.home_ip_val, text="Защищён", fill=SUCCESS)
            self.home_canvas.itemconfig(self.home_server_val, text=p.country, fill=SUCCESS)
            # переключатель в ON
            self.home_canvas.itemconfig(self.switch_knob, fill=SUCCESS)
            self.home_canvas.itemconfig(self.switch_label, text="ON", fill="#eafff2")
            self.home_canvas.coords(
                self.switch_knob,
                self.switch_on_x - 34, self.switch_on_y - 34,
                self.switch_on_x + 34, self.switch_on_y + 34
            )
        else:
            self.home_canvas.itemconfig(self.home_status, text="Отключено", fill=TEXT_MUTED)
            self.home_canvas.itemconfig(self.home_ip_val, text="—", fill=ACCENT)
            self.home_canvas.itemconfig(self.home_server_val, text="Не выбрано", fill=SUCCESS)
            # переключатель в OFF
            self.home_canvas.itemconfig(self.switch_knob, fill="#8899b0")
            self.home_canvas.itemconfig(self.switch_label, text="OFF", fill="#cbd5e1")
            if hasattr(self, "switch_off_x"):
                self.home_canvas.coords(
                    self.switch_knob,
                    self.switch_off_x - 34, self.switch_off_y - 34,
                    self.switch_off_x + 34, self.switch_off_y + 34
                )
            self.home_canvas.itemconfig(self.home_uptime_val, text="00:00:00", fill=WARNING)

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


class LoginWindow:
    """Окно входа в приложение"""
    def __init__(self, root, on_success):
        self.root = root
        self.on_success = on_success
        self.root.title("SnowVPN — Вход")
        self.root.geometry("420x420")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_DARK)

        # центрируем
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 210
        y = (self.root.winfo_screenheight() // 2) - 210
        self.root.geometry(f"+{x}+{y}")

        header = tk.Frame(self.root, bg=SIDEBAR_BG, height=70)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="❄ SnowVPN", bg=SIDEBAR_BG, fg=ACCENT,
                 font=("Segoe UI", 18, "bold")).pack(pady=18)

        card = tk.Frame(self.root, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True, padx=25, pady=20)

        tk.Label(card, text="Вход", bg=CARD_BG, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack(pady=(20, 5))
        tk.Label(card, text="Введите email и пароль", bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Segoe UI", 10)).pack(pady=(0, 20))

        tk.Label(card, text="Email", bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Segoe UI", 10)).pack(anchor=tk.W, padx=25)
        self.email = tk.Entry(card, bg=BG_DARK, fg=TEXT, insertbackground=ACCENT,
                              relief="flat", font=("Segoe UI", 11))
        self.email.pack(fill=tk.X, padx=25, pady=(3, 12))

        tk.Label(card, text="Пароль", bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Segoe UI", 10)).pack(anchor=tk.W, padx=25)
        self.password = tk.Entry(card, bg=BG_DARK, fg=TEXT, insertbackground=ACCENT,
                                 relief="flat", font=("Segoe UI", 11), show="•")
        self.password.pack(fill=tk.X, padx=25, pady=(3, 12))
        self.password.bind("<Return>", lambda e: self.try_login())

        btn = tk.Button(card, text="Войти", command=self.try_login,
                        bg=ACCENT, fg="#000", activebackground=ACCENT2,
                        activeforeground="white", relief="flat",
                        font=("Segoe UI", 11, "bold"), cursor="hand2",
                        padx=20, pady=8, bd=0)
        btn.pack(pady=10)

        self.alert = tk.Label(card, text="", bg=CARD_BG, fg=ERROR,
                              font=("Segoe UI", 10))
        self.alert.pack()

    def try_login(self):
        email = self.email.get().strip().lower()
        password = self.password.get()
        user = next((u for u in USERS_DB
                     if u["email"].lower() == email and u["password"] == password), None)
        if user:
            self.root.destroy()
            self.on_success(user)
        else:
            self.alert.config(text="Неверный email или пароль")


def run_main_app(user):
    root = tk.Tk()
    app = SnowVPNApp(root)
    app.my_uid = user.get("uid", "")  # ID аккаунта, под которым вошли
    app.my_name = user.get("name", "")
    root.mainloop()


if __name__ == "__main__":
    # Не разрешаем запускать больше одной копии (один экземпляр)
    import ctypes
    kernel32 = ctypes.windll.kernel32
    MUTEX_NAME = "SnowVPN_Single_Instance_Mutex"
    mutex = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        # уже запущен — просто выходим
        sys.exit(0)

    login_root = tk.Tk()
    LoginWindow(login_root, run_main_app)
    login_root.mainloop()