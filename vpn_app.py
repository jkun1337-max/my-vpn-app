"""
Мой VPN / Прокси для Windows
Без возможности добавления прокси через интерфейс — только через config.json
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

# -----------------------------
# Константы
# -----------------------------
CONFIG_FILE = "config.json"
LOCAL_PROXY_PORT = 8080
USER_ID = socket.gethostname()

APP_TITLE = "Мой VPN / Прокси"
APP_VERSION = "1.0"

DARK_BG = "#1e1e2e"
DARK_SURFACE = "#2a2a3c"
ACCENT = "#7aa2f7"
SUCCESS = "#3ddc97"
WARNING = "#f0a838"
ERROR = "#f44336"
TEXT = "#e0e0e0"
TEXT_MUTED = "#9aa0b6"

DEFAULT_CONFIG = {
    "proxies": [],
    "whitelist": ["discord.com", "discordapp.com"],
    "last_country": "",
    "auto_connect": False
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
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "country": self.country,
            "type": self.type,
            "busy": self.busy,
            "used_by": self.used_by,
            "latency": self.latency
        }

    @staticmethod
    def from_dict(d):
        return ProxyEntry(
            host=d.get("host", ""),
            port=int(d.get("port", 0)),
            user=d.get("user", ""),
            password=d.get("password", ""),
            country=d.get("country", ""),
            ptype=d.get("type", "http"),
            busy=d.get("busy", False),
            used_by=d.get("used_by", ""),
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
        self.selected_proxy = None

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.proxies = [ProxyEntry.from_dict(p) for p in data.get("proxies", [])]
                self.whitelist = data.get("whitelist", ["discord.com", "discordapp.com"])
                self.last_country = data.get("last_country", "")
                self.auto_connect = data.get("auto_connect", False)
            except Exception as e:
                print("Ошибка загрузки конфига:", e)
                self.proxies = []
                self.whitelist = ["discord.com", "discordapp.com"]
        else:
            self.save()

    def save(self):
        data = {
            "proxies": [p.to_dict() for p in self.proxies],
            "whitelist": self.whitelist,
            "last_country": self.last_country,
            "auto_connect": self.auto_connect
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
# Главное окно
# -----------------------------
class VPNApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("800x650")
        self.root.minsize(700, 550)
        self.root.configure(bg=DARK_BG)

        self.config = ConfigManager()
        self.config.load()

        self.server_thread = None
        self.server = None
        self.running = False
        self.speed_test_active = False

        self._setup_styles()
        self._build_ui()
        self._refresh_proxy_list()
        self._update_status()

        if self.config.auto_connect and self.config.get_available():
            self.root.after(1000, self.quick_connect)

    # --- Стили ---
    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background=DARK_BG)
        style.configure("TLabel", background=DARK_BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=DARK_BG, foreground=ACCENT, font=("Segoe UI", 16, "bold"))
        style.configure("Status.TLabel", background=DARK_BG, foreground=TEXT_MUTED, font=("Segoe UI", 10))

        style.configure("Treeview",
                        background=DARK_SURFACE,
                        fieldbackground=DARK_SURFACE,
                        foreground=TEXT,
                        borderwidth=0,
                        font=("Segoe UI", 10),
                        rowheight=28)
        style.map("Treeview", background=[("selected", ACCENT)])

        style.configure("Treeview.Heading",
                        background=DARK_SURFACE,
                        foreground=ACCENT,
                        font=("Segoe UI", 10, "bold"))

        style.configure("Accent.TButton",
                        background=ACCENT,
                        foreground="white",
                        font=("Segoe UI", 10, "bold"),
                        borderwidth=0,
                        focuscolor=ACCENT)
        style.map("Accent.TButton", background=[("active", "#5c7ff2")])

        style.configure("Danger.TButton",
                        background=ERROR,
                        foreground="white",
                        font=("Segoe UI", 10),
                        borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#c9302c")])

        style.configure("Success.TButton",
                        background=SUCCESS,
                        foreground="white",
                        font=("Segoe UI", 10),
                        borderwidth=0)
        style.map("Success.TButton", background=[("active", "#2fb87f")])

    # --- Интерфейс ---
    def _build_ui(self):
        pad = {"padx": 20, "pady": 12}

        header = tk.Frame(self.root, bg=DARK_BG)
        header.pack(fill=tk.X, **pad)
        tk.Label(header, text="🛡️  " + APP_TITLE, bg=DARK_BG, fg=ACCENT,
                 font=("Segoe UI", 18, "bold")).pack(side=tk.LEFT)
        tk.Label(header, text=f"v{APP_VERSION}", bg=DARK_BG, fg=TEXT_MUTED,
                 font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=10)

        ctrl = tk.Frame(self.root, bg=DARK_SURFACE, highlightthickness=0)
        ctrl.pack(fill=tk.X, padx=20, pady=(0, 12))

        btn_row = tk.Frame(ctrl, bg=DARK_SURFACE)
        btn_row.pack(pady=14)

        self.btn_connect = tk.Button(btn_row, text="🔌  Быстрый подключ", command=self.quick_connect,
                                     bg=ACCENT, fg="white", activebackground="#5c7ff2",
                                     activeforeground="white", relief="flat",
                                     font=("Segoe UI", 11, "bold"), cursor="hand2",
                                     padx=24, pady=8, bd=0, highlightthickness=0)
        self.btn_connect.pack(side=tk.LEFT, padx=8)

        self.btn_disconnect = tk.Button(btn_row, text="❌  Отключить", command=self.disconnect,
                                        bg=ERROR, fg="white", activebackground="#c9302c",
                                        activeforeground="white", relief="flat",
                                        font=("Segoe UI", 11), cursor="hand2",
                                        padx=20, pady=8, bd=0, highlightthickness=0,
                                        state=tk.DISABLED)
        self.btn_disconnect.pack(side=tk.LEFT, padx=8)

        country_row = tk.Frame(ctrl, bg=DARK_SURFACE)
        country_row.pack(pady=(10, 14))
        tk.Label(country_row, text="Страна:", bg=DARK_SURFACE, fg=TEXT,
                 font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0, 8))
        self.country_var = tk.StringVar()
        self.country_combo = ttk.Combobox(country_row, textvariable=self.country_var,
                                          state="readonly", width=20, font=("Segoe UI", 10))
        self.country_combo.pack(side=tk.LEFT, padx=5)
        self.country_combo.bind("<<ComboboxSelected>>", self.on_country_selected)

        self.status_label = tk.Label(self.root, text="Готов к работе", bg=DARK_BG,
                                     fg=TEXT_MUTED, font=("Segoe UI", 10))
        self.status_label.pack(anchor=tk.W, padx=20)

        list_frame = tk.LabelFrame(self.root, text="Мои прокси", bg=DARK_SURFACE, fg=ACCENT,
                                   font=("Segoe UI", 11, "bold"), bd=0, highlightthickness=1,
                                   highlightbackground="#3a3a4e")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 12))

        columns = ("host", "port", "country", "latency", "status")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=7)
        self.tree.heading("host", text="IP / Host")
        self.tree.heading("port", text="Порт")
        self.tree.heading("country", text="Страна")
        self.tree.heading("latency", text="Скорость")
        self.tree.heading("status", text="Статус")

        self.tree.column("host", width=140, anchor=tk.W)
        self.tree.column("port", width=60, anchor=tk.CENTER)
        self.tree.column("country", width=130, anchor=tk.W)
        self.tree.column("latency", width=100, anchor=tk.CENTER)
        self.tree.column("status", width=130, anchor=tk.CENTER)

        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        btns2 = tk.Frame(list_frame, bg=DARK_SURFACE)
        btns2.pack(fill=tk.X, padx=8, pady=(0, 8))
        # Кнопка "Добавить прокси" убрана — прокси вводится только в config.json
        tk.Button(btns2, text="🗑 Удалить", command=self.delete_proxy,
                  bg=DARK_BG, fg=ERROR, activebackground="#2a2a3c", activeforeground=ERROR,
                  relief="flat", font=("Segoe UI", 9), cursor="hand2",
                  padx=14, pady=5, bd=0, highlightthickness=0).pack(side=tk.LEFT, padx=4)
        tk.Button(btns2, text="⚡ Проверить скорость", command=self.check_speed,
                  bg=DARK_BG, fg=SUCCESS, activebackground="#2a2a3c", activeforeground=SUCCESS,
                  relief="flat", font=("Segoe UI", 9), cursor="hand2",
                  padx=16, pady=5, bd=0, highlightthickness=0).pack(side=tk.LEFT, padx=4)

        wl_frame = tk.LabelFrame(self.root, text="Белый список сайтов (прямое соединение, без прокси)",
                                 bg=DARK_SURFACE, fg=ACCENT, font=("Segoe UI", 11, "bold"),
                                 bd=0, highlightthickness=1, highlightbackground="#3a3a4e")
        wl_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 12))

        self.wl_text = scrolledtext.ScrolledText(wl_frame, height=5, wrap=tk.WORD,
                                                 bg=DARK_BG, fg=TEXT, insertbackground=ACCENT,
                                                 font=("Consolas", 10), relief="flat",
                                                 highlightbackground="#3a3a4e", highlightthickness=1)
        self.wl_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.wl_text.insert("1.0", "\n".join(self.config.whitelist))

        tk.Button(wl_frame, text="💾 Сохранить белый список", command=self.save_whitelist,
                  bg=ACCENT, fg="white", activebackground="#5c7ff2", activeforeground="white",
                  relief="flat", font=("Segoe UI", 9), cursor="hand2",
                  padx=14, pady=5, bd=0, highlightthickness=0).pack(anchor=tk.E, padx=8, pady=(0, 8))

        log_frame = tk.LabelFrame(self.root, text="Лог", bg=DARK_SURFACE, fg=ACCENT,
                                  font=("Segoe UI", 10, "bold"), bd=0, highlightthickness=1,
                                  highlightbackground="#3a3a4e")
        log_frame.pack(fill=tk.X, padx=20, pady=(0, 12))
        self.log_text = scrolledtext.ScrolledText(log_frame, height=5, wrap=tk.WORD,
                                                  bg=DARK_BG, fg=TEXT_MUTED, insertbackground=ACCENT,
                                                  font=("Consolas", 9), relief="flat",
                                                  highlightbackground="#3a3a4e", highlightthickness=1,
                                                  state=tk.DISABLED)
        self.log_text.pack(fill=tk.X, padx=8, pady=8)

        hint = ("💡 В настройках браузера укажи прокси 127.0.0.1:8080. "
                "Discord приложение не настраивай — оно идёт напрямую. "
                "Прокси добавляй только в файл config.json вручную.")
        tk.Label(self.root, text=hint, bg=DARK_BG, fg=TEXT_MUTED,
                 font=("Segoe UI", 9), wraplength=760).pack(pady=(0, 14))

    def log(self, msg, level="info"):
        colors = {"info": TEXT_MUTED, "success": SUCCESS, "error": ERROR, "warn": WARNING}
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _refresh_proxy_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        countries = set()
        for p in self.config.proxies:
            countries.add(p.country)
            status = "Занят" if p.busy else ("Свободен" if p.latency is not None else "Неизвестно")
            tag = "busy" if p.busy else "free"
            lat_text = f"{p.latency} мс" if p.latency is not None else "—"
            self.tree.insert("", tk.END,
                             values=(p.host, p.port, p.country, lat_text, status),
                             tags=(tag,))
        self.tree.tag_configure("busy", foreground=ERROR)
        self.tree.tag_configure("free", foreground=SUCCESS)

        country_list = sorted(countries)
        self.country_combo["values"] = country_list
        if self.config.last_country and self.config.last_country in country_list:
            self.country_combo.set(self.config.last_country)
        elif country_list:
            self.country_combo.set(country_list[0])

    def _update_status(self):
        if self.running and self.config.selected_proxy:
            p = self.config.selected_proxy
            self.status_label.config(
                text=f"● Подключено: {p.host}:{p.port}  ({p.country})",
                fg=SUCCESS)
            self.btn_connect.config(state=tk.DISABLED)
            self.btn_disconnect.config(state=tk.NORMAL)
        else:
            self.status_label.config(text="○ Отключено", fg=TEXT_MUTED)
            self.btn_connect.config(state=tk.NORMAL)
            self.btn_disconnect.config(state=tk.DISABLED)

    # --- Действия ---
    def quick_connect(self):
        if self.running:
            messagebox.showinfo("Внимание", "Уже подключено. Сначала отключите.")
            return

        country = self.country_combo.get() or None
        available = self.config.get_available(country)

        if not available:
            if country:
                messagebox.showerror("Ошибка", f"Все прокси страны '{country}' заняты. Выберите другую страну.")
            else:
                messagebox.showerror("Ошибка", "Нет доступных прокси. Добавьте их в файл config.json.")
            return

        best = min(available, key=lambda p: p.latency if p.latency is not None else 9999)

        self.config.selected_proxy = best
        self.config.mark_busy(best, USER_ID)
        self.config.last_country = best.country
        self.config.save()

        self._start_local_proxy()
        self._refresh_proxy_list()
        self._update_status()
        self.log(f"✅ Подключено к {best.host}:{best.port} ({best.country})", "success")

    def _start_local_proxy(self):
        if self.running:
            return
        try:
            self.server = ThreadedTCPServer(("127.0.0.1", LOCAL_PROXY_PORT), LocalProxyHandler, self)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            self.running = True
            self.log(f"🌐 Локальный прокси запущен на 127.0.0.1:{LOCAL_PROXY_PORT}", "info")
        except OSError as e:
            if hasattr(e, 'winerror') and e.winerror == 10048:
                messagebox.showerror("Ошибка", f"Порт {LOCAL_PROXY_PORT} уже занят.")
            else:
                messagebox.showerror("Ошибка", str(e))

    def disconnect(self):
        if not self.running:
            return
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
        self._refresh_proxy_list()
        self._update_status()
        self.log("🔌 Отключено", "warn")

    def on_country_selected(self, event=None):
        country = self.country_combo.get()
        self.config.last_country = country
        self.config.save()
        avail = self.config.get_available(country)
        busy = len(self.config.get_by_country(country)) - len(avail)
        self.status_label.config(text=f"Страна: {country}. Свободно: {len(avail)}, Занято: {busy}")
        self._refresh_proxy_list()

    def delete_proxy(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Внимание", "Выберите прокси для удаления")
            return
        item = self.tree.item(selected[0])
        host, port = item["values"][0], item["values"][1]
        self.config.proxies = [p for p in self.config.proxies if not (p.host == host and p.port == port)]
        if self.config.selected_proxy and self.config.selected_proxy.host == host and self.config.selected_proxy.port == port:
            self.disconnect()
        self.config.save()
        self._refresh_proxy_list()
        self.log("🗑 Прокси удалён", "warn")

    def check_speed(self):
        if not self.config.proxies:
            messagebox.showinfo("Информация", "Нет прокси для проверки")
            return
        self.speed_test_active = True
        self.log("⚡ Проверка скорости прокси...", "info")
        for p in self.config.proxies:
            lat = self.config.ping_proxy(p, timeout=3)
            p.latency = lat
        self.config.save()
        self._refresh_proxy_list()
        self.speed_test_active = False
        self.log("✅ Проверка скорости завершена", "success")

    def save_whitelist(self):
        text = self.wl_text.get("1.0", tk.END).strip()
        self.config.whitelist = [x.strip() for x in text.splitlines() if x.strip()]
        self.config.save()
        messagebox.showinfo("Готово", "Белый список сохранён")
        self.log(f"📋 Белый список: {', '.join(self.config.whitelist)}", "info")


if __name__ == "__main__":
    root = tk.Tk()
    app = VPNApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.disconnect(), root.destroy()))
    root.mainloop()