#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
game_macro_gui.py — 遊戲重複按鍵工具（圖形介面版，黑金主題）

架構：角色 → 一份「技能輪替」＋ 多個「組合」
    技能輪替（冷卻）：主畫面直接編輯，F8 開始／暫停後常駐執行，
        各鍵獨立倒數、冷卻到了就按。
    組合：一次全部列出，各自綁熱鍵；按熱鍵隨時插播（輪替暫停），
        打完 N 輪自動恢復輪替。新增／編輯組合走獨立彈窗。

安裝:
    uv sync                        # 依賴：customtkinter、pynput
    # Windows 遊戲建議加裝 pydirectinput（uv 會依平台自動安裝）

執行:
    uv run game_macro_gui.py

全域熱鍵（皆可自訂）：
    開始 / 暫停技能輪替（預設 F8，可於全域設定更改）
    結束程式（預設 F9，可於全域設定更改）
    各組合的插播熱鍵可在組合彈窗中自訂（單鍵或組合鍵，如 F1、Ctrl+Shift+K）

按鍵欄位除了鍵盤鍵（1、q、space、f5...）也支援滑鼠：右鍵、左鍵、中鍵

設定檔為同目錄的 profiles.json（會自動從舊版格式升級）。
"""

import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import customtkinter as ctk
from pynput import keyboard
from pynput.keyboard import Controller, Key
from pynput.mouse import Button, Controller as MouseController

# macOS：繞過 pynput 已知的 Caps Lock 崩潰（pynput issue #510）。
# 監聽遮罩移除 NSSystemDefined（媒體鍵/系統事件），避免監聽執行緒
# 把 Caps Lock 系統事件轉成 NSEvent 時觸發 macOS 主執行緒斷言而閃退。
# 副作用僅是偵測不到音量/亮度等媒體鍵，本程式用不到。
if sys.platform == "darwin":
    try:
        import Quartz
        from pynput.keyboard._darwin import Listener as _DarwinKbListener
        _DarwinKbListener._EVENTS = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) |
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp) |
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged))
    except Exception:
        pass

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles.json")

DEFAULT_CONFIG = {
    "global": {
        "hold_range": [0.04, 0.09],
        "global_gap": 0.12,
        "focus_window_keyword": "",
        "use_directinput": True,
        "hotkey_toggle": "<f8>",
        "hotkey_quit": "<f9>"
    },
    "profiles": [
        {"name": "角色1",
         "rotation": {"actions": [
             {"key": "1", "interval": 8.0, "jitter": 0.0, "start_delay": 0.0}]},
         "combos": [
             {"name": "右鍵+K×20", "hotkey": "<f1>",
              "repeat": 20, "round_gap": [0.8, 1.6],
              "steps": [
                  {"key": "右鍵", "wait_min": 0.15, "wait_max": 0.4},
                  {"key": "k", "wait_min": 0.3, "wait_max": 0.7}
              ]}
         ]}
    ]
}

# ---------------- 黑金主題 tokens ----------------

COL_BG = "#121212"            # 視窗底
COL_CARD = "#1E1E1E"          # 卡片面
COL_FIELD = "#262626"         # 輸入欄位底
COL_BORDER = "#3A3A3A"        # 欄位/次要按鈕邊線
COL_TEXT = "#EAEAEA"          # 主文字
COL_SUBTEXT = "#9E9E9E"       # 次要文字
COL_GOLD = "#D4AF37"          # 金 accent（主按鈕、標題、選中）
COL_GOLD_HOVER = "#E0C158"
COL_GOLD_DARK = "#8F6E14"
COL_GOLD_DARK_HOVER = "#A58220"
COL_ON_GOLD = "#181818"       # 金底上的文字
COL_DANGER = "#B3453F"        # 危險紅（僅刪除類）
COL_DANGER_HOVER = "#C9564F"
COL_DANGER_TEXT = "#E08983"
COL_TREE_BG = "#1A1A1A"
COL_TREE_HEAD = "#242424"

_SYS_FONT_FAMILY = None


def sys_font_family():
    """系統 UI 字體（macOS = 蘋方/SF、Windows = Segoe UI），CJK 交給系統 fallback。"""
    global _SYS_FONT_FAMILY
    if _SYS_FONT_FAMILY is None:
        try:
            _SYS_FONT_FAMILY = tkfont.nametofont("TkDefaultFont").actual("family")
        except Exception:
            _SYS_FONT_FAMILY = ""
    return _SYS_FONT_FAMILY


def make_font(size=13, weight="normal"):
    fam = sys_font_family()
    if fam:
        return ctk.CTkFont(family=fam, size=size, weight=weight)
    return ctk.CTkFont(size=size, weight=weight)


def apply_dark_titlebar(win):
    """macOS 標題列強制深色；其餘平台由 CustomTkinter 自行處理。"""
    if sys.platform == "darwin":
        try:
            win.tk.call("::tk::unsupported::MacWindowStyle",
                        "appearance", win._w, "darkaqua")
        except Exception:
            pass


def uniquify(names):
    """讓下拉選單顯示名稱唯一（重名時附序號），選擇時才能以名稱反查索引。"""
    seen, out = {}, []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return out


def make_btn(master, text, command, kind="secondary", width=72, height=30, font=None):
    """黑金按鈕分級：primary 金實心 / secondary 深灰描邊 / danger 紅字描邊 / danger_solid 紅實心。"""
    font = font or make_font(13)
    common = dict(master=master, text=text, command=command,
                  width=width, height=height, corner_radius=8, font=font)
    if kind == "primary":
        return ctk.CTkButton(fg_color=COL_GOLD, hover_color=COL_GOLD_HOVER,
                             text_color=COL_ON_GOLD, **common)
    if kind == "danger":
        return ctk.CTkButton(fg_color="transparent", hover_color="#38211F",
                             border_width=1, border_color="#5A2F2B",
                             text_color=COL_DANGER_TEXT, **common)
    if kind == "danger_solid":
        return ctk.CTkButton(fg_color=COL_DANGER, hover_color=COL_DANGER_HOVER,
                             text_color="#F7ECEC", **common)
    return ctk.CTkButton(fg_color="#2C2C2C", hover_color="#383838",
                         border_width=1, border_color=COL_BORDER,
                         text_color=COL_TEXT, **common)


# 滑鼠按鍵別名（在按鍵欄位直接填這些字即可）
MOUSE_ALIASES = {
    "右鍵": "right", "滑鼠右鍵": "right", "mouse_right": "right", "rclick": "right",
    "左鍵": "left", "滑鼠左鍵": "left", "mouse_left": "left", "lclick": "left",
    "中鍵": "middle", "滑鼠中鍵": "middle", "mouse_middle": "middle",
}


def mouse_button(name):
    return MOUSE_ALIASES.get(name.strip().lower())


# ---------------- 熱鍵規格 ----------------
# 儲存格式採 pynput HotKey 規格，如 "<f1>"、"<ctrl>+<shift>+k"

MOD_KEYS = {
    Key.ctrl: "ctrl", Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl",
    Key.shift: "shift", Key.shift_l: "shift", Key.shift_r: "shift",
    Key.alt: "alt", Key.alt_l: "alt", Key.alt_r: "alt", Key.alt_gr: "alt",
    Key.cmd: "cmd", Key.cmd_l: "cmd", Key.cmd_r: "cmd",
}
MOD_ORDER = ("ctrl", "alt", "shift", "cmd")


def normalize_spec(spec):
    """相容舊格式：'f1' → '<f1>'。"""
    if spec and "+" not in spec and not spec.startswith("<") and len(spec) > 1:
        return f"<{spec}>"
    return spec


def spec_display(spec):
    """'<ctrl>+<shift>+k' → 'Ctrl+Shift+K'"""
    if not spec:
        return "（無）"
    parts = []
    for t in spec.split("+"):
        t = t.strip()
        if t.startswith("<") and t.endswith(">"):
            t = t[1:-1]
        parts.append(t.capitalize() if len(t) > 1 else t.upper())
    return "+".join(parts)


# ---------------- 按鍵後端 ----------------

class PynputBackend:
    name = "pynput"

    def __init__(self):
        self.kb = Controller()
        self.mouse = MouseController()

    def _resolve(self, n):
        if len(n) == 1:
            return n
        k = getattr(Key, n.lower(), None)
        if k is None:
            raise ValueError(f"不認得的按鍵：{n!r}")
        return k

    def tap(self, name, hold):
        btn = mouse_button(name)
        if btn:
            b = getattr(Button, btn)
            self.mouse.press(b)
            try:
                time.sleep(hold)
            finally:
                self.mouse.release(b)
            return
        k = self._resolve(name)
        self.kb.press(k)
        try:
            time.sleep(hold)
        finally:
            self.kb.release(k)

    def click(self, x, y, button="left", hold=0.05):
        b = getattr(Button, button, Button.left)
        self.mouse.position = (x, y)
        time.sleep(0.02)          # 給系統一點時間完成游標移動
        self.mouse.press(b)
        try:
            time.sleep(hold)
        finally:
            self.mouse.release(b)


class DirectInputBackend:
    name = "pydirectinput"

    def __init__(self):
        import pydirectinput
        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False
        self.di = pydirectinput

    def tap(self, name, hold):
        btn = mouse_button(name)
        if btn:
            self.di.mouseDown(button=btn)
            try:
                time.sleep(hold)
            finally:
                self.di.mouseUp(button=btn)
            return
        self.di.keyDown(name.lower())
        try:
            time.sleep(hold)
        finally:
            self.di.keyUp(name.lower())

    def click(self, x, y, button="left", hold=0.05):
        self.di.moveTo(int(x), int(y))
        self.di.mouseDown(button=button)
        try:
            time.sleep(hold)
        finally:
            self.di.mouseUp(button=button)


def make_backend(use_di, log):
    if use_di and sys.platform == "win32":
        try:
            return DirectInputBackend()
        except ImportError:
            log("未安裝 pydirectinput，改用 pynput（遊戲若沒反應請安裝它）")
    return PynputBackend()


# ---------------- 視窗焦點 ----------------

_win_cache = {"t": 0.0, "title": ""}


def active_window_title():
    now = time.monotonic()
    if now - _win_cache["t"] < 0.5:
        return _win_cache["title"]
    title = ""
    try:
        if sys.platform == "win32":
            import ctypes
            u = ctypes.windll.user32
            h = u.GetForegroundWindow()
            n = u.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, buf, n + 1)
            title = buf.value
        elif sys.platform == "darwin":
            title = subprocess.check_output(
                ["osascript", "-e",
                 'tell application "System Events" to get name of '
                 'first application process whose frontmost is true'],
                text=True, timeout=1).strip()
        else:
            title = subprocess.check_output(
                ["xdotool", "getactivewindow", "getwindowname"],
                text=True, timeout=1).strip()
    except Exception:
        title = ""
    _win_cache.update(t=now, title=title)
    return title


def list_window_titles(_retry=1):
    """列出目前開啟的視窗/程式名稱，供「只在視窗標題含」下拉選單使用。
    macOS System Events 偶發 -1719 索引錯誤，失敗時重試一次。"""
    titles = []
    try:
        if sys.platform == "win32":
            import ctypes
            u = ctypes.windll.user32
            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def _cb(h, _):
                if u.IsWindowVisible(h):
                    n = u.GetWindowTextLengthW(h)
                    if n:
                        buf = ctypes.create_unicode_buffer(n + 1)
                        u.GetWindowTextW(h, buf, n + 1)
                        titles.append(buf.value)
                return True
            u.EnumWindows(_cb, None)
        elif sys.platform == "darwin":
            out = subprocess.check_output(
                ["osascript", "-e",
                 'tell application "System Events" to get name of every '
                 'application process whose background only is false'],
                text=True, timeout=3).strip()
            titles = [t.strip() for t in out.split(",") if t.strip()]
        else:
            out = subprocess.check_output(["wmctrl", "-l"], text=True, timeout=3)
            titles = [ln.split(None, 3)[3] for ln in out.splitlines()
                      if len(ln.split(None, 3)) > 3]
    except Exception:
        pass
    if not titles and _retry > 0:
        time.sleep(0.3)
        return list_window_titles(_retry - 1)
    return sorted(set(titles))


BTN_DISP = {"left": "左鍵", "right": "右鍵", "middle": "中鍵"}
DISP_BTN = {v: k for k, v in BTN_DISP.items()}


def window_rect(keyword):
    """找標題（或程式名）含關鍵字的視窗，回傳左上角座標 (x, y)；找不到回傳 None。"""
    kw = (keyword or "").strip().lower()
    if not kw:
        return None
    try:
        if sys.platform == "win32":
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            found = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def _cb(h, _):
                if u.IsWindowVisible(h):
                    n = u.GetWindowTextLengthW(h)
                    if n:
                        buf = ctypes.create_unicode_buffer(n + 1)
                        u.GetWindowTextW(h, buf, n + 1)
                        if kw in buf.value.lower():
                            r = wt.RECT()
                            u.GetWindowRect(h, ctypes.byref(r))
                            found.append((r.left, r.top))
                            return False
                return True
            u.EnumWindows(_cb, None)
            return found[0] if found else None
        if sys.platform == "darwin":
            import Quartz
            opts = (Quartz.kCGWindowListOptionOnScreenOnly |
                    Quartz.kCGWindowListExcludeDesktopElements)
            for info in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
                if info.get(Quartz.kCGWindowLayer, 0) != 0:
                    continue
                name = (f"{info.get(Quartz.kCGWindowOwnerName, '')} "
                        f"{info.get(Quartz.kCGWindowName, '')}").lower()
                if kw in name:
                    b = info.get(Quartz.kCGWindowBounds) or {}
                    return (int(b.get("X", 0)), int(b.get("Y", 0)))
            return None
        out = subprocess.check_output(["wmctrl", "-lG"], text=True, timeout=2)
        for ln in out.splitlines():
            parts = ln.split(None, 7)
            if len(parts) >= 8 and kw in parts[7].lower():
                return (int(parts[2]), int(parts[3]))
    except Exception:
        pass
    return None


# ---------------- 設定檔載入與升級 ----------------

def migrate_config(cfg):
    """舊版格式一路升級到新版：角色 = rotation（輪替）＋ combos（組合列表）。

    v1：角色即單一巨集（actions/steps/combo_steps 直接掛在角色上）
    v2：角色包含 macros 列表（各巨集有 mode，可能同時存多模式清單）
    v3（現行）：rotation.actions ＋ combos[{name, hotkey, repeat, round_gap, steps}]
    """
    for p in cfg.get("profiles", []):
        # v1 → v2
        if "macros" not in p and "rotation" not in p and "combos" not in p:
            m = {"name": p.get("name", "組合1"), "mode": p.get("mode", "cooldown")}
            for k in ("actions", "steps", "combo_steps", "repeat", "round_gap", "hotkey"):
                if k in p:
                    m[k] = p.pop(k)
            p.pop("mode", None)
            p["macros"] = [m]
        # v2 → v3：冷卻清單併入輪替；combo_steps 照搬成組合；
        # 循序清單轉成「無限輪、固定間隔」的組合（行為等價）
        if "macros" in p:
            rotation_actions, combos = [], []
            for m in p.pop("macros"):
                rotation_actions += list(m.get("actions") or [])
                steps = m.get("combo_steps") or []
                if steps:
                    c = {"name": m.get("name", "組合"),
                         "repeat": int(m.get("repeat", 10) or 0),
                         "round_gap": m.get("round_gap", [1.0, 3.0]),
                         "steps": steps}
                    if m.get("hotkey"):
                        c["hotkey"] = m["hotkey"]
                    combos.append(c)
                seq = m.get("steps") or []
                if seq:
                    c = {"name": m.get("name", "組合") + ("（循序）" if steps else ""),
                         "repeat": 0, "round_gap": [0.0, 0.0],
                         "steps": [{"key": s.get("key", ""),
                                    "wait_min": s.get("wait", 1.0),
                                    "wait_max": s.get("wait", 1.0)} for s in seq]}
                    if m.get("hotkey") and not steps:
                        c["hotkey"] = m["hotkey"]
                    combos.append(c)
            p["rotation"] = {"actions": rotation_actions}
            p["combos"] = combos
        p.setdefault("rotation", {"actions": []})
        p.setdefault("combos", [])
    return cfg


# ---------------- 主程式 ----------------

class App:
    def __init__(self, root):
        self.root = root
        root.title("按鍵助手")
        root.geometry("820x940")
        root.minsize(740, 820)

        self.msg_q = queue.Queue()
        self.running = threading.Event()
        self.stopping = threading.Event()
        self.generation = 0
        self.count = 0
        self.runtime = None          # 開始時凍結的（執行設定, 全域設定）
        self.active = None           # ("rotation", 角色索引) 或 ("combo", 角色索引, 組合索引)
        self.resume_state = None     # 組合插播前的輪替現場 (runtime, active)，打完自動恢復
        self.backend = None
        self.macro_hotkeys = []      # 目前角色各組合的 HotKey 監聽物件
        self.ctrl_hotkeys = []       # 輪替開關/結束程式 的 HotKey 監聽物件
        self.capture_win = None      # 熱鍵擷取中的視窗
        self.capture_cb = None       # 擷取結果回呼
        self.cap_reserved = {}       # 擷取時不可用的熱鍵 {spec: 用途說明}
        self.cap_mods = set()        # 目前按住的修飾鍵
        self.coord_win = None        # 座標擷取中的視窗
        self.coord_cb = None         # 座標擷取回呼
        self._mouse = MouseController()   # 讀取游標位置用

        self.cfg = self.load_config()
        self.cur_p = 0               # 目前角色索引
        gset = self.cfg["global"]
        self.hk_toggle_spec = normalize_spec(gset.get("hotkey_toggle") or "<f8>")
        self.hk_quit_spec = normalize_spec(gset.get("hotkey_quit") or "<f9>")

        self.build_ui()
        self.refresh_profile_list()
        self.load_profile_into_ui()
        self.rebuild_hotkeys()
        self._rebuild_control_hotkeys()
        root.after(1200, lambda: self._refresh_window_list(quiet=True))

        threading.Thread(target=self.worker, daemon=True).start()
        self.hotkeys = keyboard.Listener(on_press=self.on_hotkey,
                                         on_release=self.on_hotkey_release)
        self.hotkeys.start()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll_queue)

    # ---------- 目前選擇 ----------

    def prof(self):
        return self.cfg["profiles"][self.cur_p]

    # ---------- 主題化訊息框 ----------

    def msg_info(self, title, msg):
        MsgBox(self.root, title, msg)

    def msg_warn(self, title, msg):
        MsgBox(self.root, title, msg, kind="warning")

    def msg_error(self, title, msg):
        MsgBox(self.root, title, msg, kind="error")

    def ask_yesno(self, title, msg, danger=False):
        return bool(MsgBox(self.root, title, msg, ask=True, danger=danger).answer)

    # ---------- 設定檔 ----------

    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg.setdefault("global", {})
                cfg.setdefault("profiles", [])
                if cfg["profiles"]:
                    return migrate_config(cfg)
            except Exception as e:
                self.msg_warn("設定檔", f"profiles.json 讀取失敗，使用預設值。\n{e}")
        return migrate_config(json.loads(json.dumps(DEFAULT_CONFIG)))

    def save_config(self):
        try:
            self.commit_ui()
        except ValueError as e:
            self.msg_error("儲存失敗", f"輪替清單的數字欄位格式不對：{e}")
            return
        g = self.cfg["global"]
        g["focus_window_keyword"] = self.var_focus.get().strip()
        g["use_directinput"] = bool(self.var_di.get())
        g["hotkey_toggle"] = self.hk_toggle_spec
        g["hotkey_quit"] = self.hk_quit_spec
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
            self.log(f"已儲存設定 → {os.path.basename(CONFIG_PATH)}")
        except Exception as e:
            self.msg_error("儲存失敗", str(e))

    # ---------- UI ----------

    def build_ui(self):
        self.root.configure(fg_color=COL_BG)

        self.f_body = make_font(13)
        self.f_bold = make_font(13, "bold")
        self.f_title = make_font(15, "bold")
        self.f_start = make_font(14, "bold")
        self.f_small = make_font(12)
        mono = {"darwin": "Menlo", "win32": "Consolas"}.get(sys.platform, "DejaVu Sans Mono")
        self.f_mono = ctk.CTkFont(family=mono, size=12)

        # Treeview 黑金樣式（輪替表、組合表、彈窗步驟表共用）
        fam = sys_font_family()
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Gold.Treeview", background=COL_TREE_BG,
                        fieldbackground=COL_TREE_BG, foreground=COL_TEXT,
                        rowheight=28, borderwidth=0, relief="flat", font=(fam, 12),
                        bordercolor=COL_TREE_BG, lightcolor=COL_TREE_BG,
                        darkcolor=COL_TREE_BG)
        style.configure("Gold.Treeview.Heading", background=COL_TREE_HEAD,
                        foreground=COL_GOLD, relief="flat", borderwidth=0,
                        font=(fam, 12, "bold"), padding=(6, 5),
                        bordercolor=COL_TREE_BG, lightcolor=COL_TREE_HEAD,
                        darkcolor=COL_TREE_HEAD)
        style.map("Gold.Treeview",
                  background=[("selected", COL_GOLD)],
                  foreground=[("selected", COL_ON_GOLD)])
        style.map("Gold.Treeview.Heading", background=[("active", "#2E2E2E")])

        self.root.grid_columnconfigure(0, weight=1)
        # minsize 保證按鈕直欄不會被裁掉
        self.root.grid_rowconfigure(1, weight=3, minsize=228)   # 輪替卡
        self.root.grid_rowconfigure(2, weight=2, minsize=168)   # 組合卡
        self.root.grid_rowconfigure(5, weight=2)   # 日誌卡

        # ── 卡片 1：角色 ──
        sel = self._card(row=0, pady=(12, 4))
        r1 = ctk.CTkFrame(sel, fg_color="transparent")
        r1.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(r1, text="角色", font=self.f_bold, text_color=COL_SUBTEXT,
                     width=36, anchor="w").pack(side="left")
        self.cmb_p = ctk.CTkComboBox(
            r1, width=180, height=28, state="readonly", command=self.on_pick_profile,
            font=self.f_body, dropdown_font=self.f_body,
            fg_color=COL_FIELD, border_color=COL_BORDER,
            button_color="#303030", button_hover_color="#3C3C3C",
            dropdown_fg_color="#232323", dropdown_hover_color="#333333",
            dropdown_text_color=COL_TEXT, text_color=COL_TEXT)
        self.cmb_p.pack(side="left", padx=(2, 8))
        make_btn(r1, "新增", self.add_profile, width=56, font=self.f_body).pack(side="left", padx=2)
        make_btn(r1, "複製", self.copy_profile, width=56, font=self.f_body).pack(side="left", padx=2)
        make_btn(r1, "重新命名", self.rename_profile, width=84, font=self.f_body).pack(side="left", padx=2)
        make_btn(r1, "刪除", self.del_profile, kind="danger", width=56, font=self.f_body).pack(side="left", padx=2)

        # ── 卡片 2：技能輪替（冷卻） ──
        rot = self._card(row=1, expand=True)
        head = ctk.CTkFrame(rot, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(head, text="技能輪替", font=self.f_title,
                     text_color=COL_GOLD).pack(side="left")
        self.lbl_rot_hint = ctk.CTkLabel(
            head, text=f"　{self._t_disp()} 開始／暫停　各鍵獨立倒數，冷卻到了就按",
            font=self.f_small, text_color=COL_SUBTEXT)
        self.lbl_rot_hint.pack(side="left")
        body = ctk.CTkFrame(rot, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(side="right", fill="y", padx=(10, 0))
        wrap = ctk.CTkFrame(body, fg_color=COL_TREE_BG, corner_radius=8)
        wrap.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, style="Gold.Treeview", show="headings",
                                 selectmode="browse")
        sb = ctk.CTkScrollbar(wrap, command=self.tree.yview, fg_color="transparent",
                              button_color="#3A3A3A", button_hover_color="#4E4E4E")
        sb.pack(side="right", fill="y", padx=(0, 4), pady=8)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self.tree.configure(yscrollcommand=sb.set,
                            columns=("key", "interval", "jitter", "delay"))
        for c, h in zip(("key", "interval", "jitter", "delay"),
                        ("按鍵", "間隔(秒)", "浮動±(秒)", "起始延遲(秒)")):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=90, anchor="center")
        self.tree.bind("<Double-1>", lambda e: self.edit_action())
        make_btn(btns, "新增動作", self.add_action, kind="primary",
                 width=92, height=28, font=self.f_body).pack(pady=(0, 2))
        make_btn(btns, "編輯", self.edit_action, width=92, height=28,
                 font=self.f_body).pack(pady=2)
        make_btn(btns, "刪除", self.del_action, kind="danger", width=92, height=28,
                 font=self.f_body).pack(pady=2)
        make_btn(btns, "上移", lambda: self.move_action(-1), width=92, height=28,
                 font=self.f_body).pack(pady=2)
        make_btn(btns, "下移", lambda: self.move_action(1), width=92, height=28,
                 font=self.f_body).pack(pady=2)

        # ── 卡片 3：組合列表 ──
        cmb = self._card(row=2, expand=True)
        chead = ctk.CTkFrame(cmb, fg_color="transparent")
        chead.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(chead, text="組合", font=self.f_title,
                     text_color=COL_GOLD).pack(side="left")
        ctk.CTkLabel(chead, text="　按熱鍵隨時插播，打完自動恢復輪替　雙擊列＝編輯",
                     font=self.f_small, text_color=COL_SUBTEXT).pack(side="left")
        cbody = ctk.CTkFrame(cmb, fg_color="transparent")
        cbody.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        cbtns = ctk.CTkFrame(cbody, fg_color="transparent")
        cbtns.pack(side="right", fill="y", padx=(10, 0))
        cwrap = ctk.CTkFrame(cbody, fg_color=COL_TREE_BG, corner_radius=8)
        cwrap.pack(side="left", fill="both", expand=True)
        self.tree_c = ttk.Treeview(cwrap, style="Gold.Treeview", show="headings",
                                   selectmode="browse")
        csb = ctk.CTkScrollbar(cwrap, command=self.tree_c.yview, fg_color="transparent",
                               button_color="#3A3A3A", button_hover_color="#4E4E4E")
        csb.pack(side="right", fill="y", padx=(0, 4), pady=8)
        self.tree_c.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self.tree_c.configure(yscrollcommand=csb.set,
                              columns=("name", "hotkey", "steps", "repeat"))
        for c, h, w in (("name", "名稱", 160), ("hotkey", "熱鍵", 110),
                        ("steps", "步驟數", 70), ("repeat", "輪數", 70)):
            self.tree_c.heading(c, text=h)
            self.tree_c.column(c, width=w, anchor="center")
        self.tree_c.bind("<Double-1>", lambda e: self.edit_combo())
        make_btn(cbtns, "新增組合", self.add_combo, kind="primary",
                 width=92, height=28, font=self.f_body).pack(pady=(0, 2))
        make_btn(cbtns, "編輯", self.edit_combo, width=92, height=28,
                 font=self.f_body).pack(pady=2)
        make_btn(cbtns, "刪除", self.del_combo, kind="danger", width=92, height=28,
                 font=self.f_body).pack(pady=2)

        # ── 卡片 4：全域設定 ──
        opt = self._card(row=3)
        ctk.CTkLabel(opt, text="全域設定", font=self.f_title,
                     text_color=COL_GOLD).pack(anchor="w", padx=14, pady=(10, 2))
        orow = ctk.CTkFrame(opt, fg_color="transparent")
        orow.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(orow, text="只在視窗標題含", font=self.f_body,
                     text_color=COL_TEXT).pack(side="left")
        self.var_focus = tk.StringVar(value=self.cfg["global"].get("focus_window_keyword", ""))
        self.cmb_focus = ctk.CTkComboBox(
            orow, width=200, height=28, variable=self.var_focus,
            values=["（不限制）"], command=self._pick_focus,
            font=self.f_body, dropdown_font=self.f_body,
            fg_color=COL_FIELD, border_color=COL_BORDER,
            button_color="#303030", button_hover_color="#3C3C3C",
            dropdown_fg_color="#232323", dropdown_hover_color="#333333",
            dropdown_text_color=COL_TEXT, text_color=COL_TEXT)
        self.cmb_focus.pack(side="left", padx=6)
        ctk.CTkLabel(orow, text="時才按鍵（可直接輸入，留空 = 不限制）", font=self.f_body,
                     text_color=COL_TEXT).pack(side="left")
        make_btn(orow, "↻ 重新整理視窗", lambda: self._refresh_window_list(),
                 width=120, height=28, font=self.f_body).pack(side="left", padx=8)
        self.var_di = tk.BooleanVar(value=self.cfg["global"].get("use_directinput", True))
        ctk.CTkCheckBox(opt, text="使用 DirectInput（Windows 遊戲建議勾選）",
                        variable=self.var_di, onvalue=True, offvalue=False,
                        font=self.f_body, text_color=COL_TEXT,
                        fg_color=COL_GOLD, hover_color=COL_GOLD_HOVER,
                        checkmark_color=COL_ON_GOLD, border_color="#4A4A4A",
                        checkbox_width=20, checkbox_height=20,
                        corner_radius=5).pack(anchor="w", padx=14, pady=4)
        hkrow = ctk.CTkFrame(opt, fg_color="transparent")
        hkrow.pack(fill="x", padx=14, pady=(2, 12))
        ctk.CTkLabel(hkrow, text="控制熱鍵：輪替開關", font=self.f_body,
                     text_color=COL_TEXT).pack(side="left")
        self.lbl_hk_toggle = ctk.CTkLabel(hkrow, text=spec_display(self.hk_toggle_spec),
                                          font=self.f_body, text_color=COL_GOLD,
                                          fg_color=COL_FIELD, corner_radius=6,
                                          width=90, height=26)
        self.lbl_hk_toggle.pack(side="left", padx=6)
        make_btn(hkrow, "設定", lambda: self.capture_control_hotkey("toggle"),
                 width=52, height=28, font=self.f_body).pack(side="left")
        ctk.CTkLabel(hkrow, text="　結束程式", font=self.f_body,
                     text_color=COL_TEXT).pack(side="left")
        self.lbl_hk_quit = ctk.CTkLabel(hkrow, text=spec_display(self.hk_quit_spec),
                                        font=self.f_body, text_color=COL_GOLD,
                                        fg_color=COL_FIELD, corner_radius=6,
                                        width=90, height=26)
        self.lbl_hk_quit.pack(side="left", padx=6)
        make_btn(hkrow, "設定", lambda: self.capture_control_hotkey("quit"),
                 width=52, height=28, font=self.f_body).pack(side="left")

        # ── 控制列 ──
        ctl = ctk.CTkFrame(self.root, fg_color="transparent")
        ctl.grid(row=4, column=0, sticky="ew", padx=12, pady=4)
        self.btn_start = make_btn(ctl, self._btn_text_start(), self.toggle, kind="primary",
                                  width=170, height=40, font=self.f_start)
        self.btn_start.pack(side="left")
        make_btn(ctl, "儲存設定", self.save_config, width=92, height=40,
                 font=self.f_body).pack(side="left", padx=8)
        self.lbl_status = ctk.CTkLabel(
            ctl, text=self._idle_status(),
            font=self.f_small, text_color=COL_SUBTEXT, anchor="w")
        self.lbl_status.pack(side="left", padx=8, fill="x", expand=True)

        # ── 卡片 5：日誌 ──
        logc = self._card(row=5, expand=True, pady=(4, 12))
        ctk.CTkLabel(logc, text="日誌", font=self.f_title,
                     text_color=COL_GOLD).pack(anchor="w", padx=14, pady=(10, 2))
        self.txt = ctk.CTkTextbox(logc, state="disabled", font=self.f_mono,
                                  fg_color="#161616", text_color="#CFCFCF",
                                  corner_radius=8, border_width=0)
        self.txt.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _card(self, row, expand=False, pady=(4, 4)):
        card = ctk.CTkFrame(self.root, fg_color=COL_CARD, corner_radius=12)
        card.grid(row=row, column=0, sticky="nsew" if expand else "ew",
                  padx=12, pady=pady)
        return card

    def _entry(self, master, var=None, width=64):
        e = ctk.CTkEntry(master, width=width, height=28, textvariable=var,
                         font=self.f_body, fg_color=COL_FIELD,
                         border_color=COL_BORDER, text_color=COL_TEXT,
                         corner_radius=6)
        # tk 底層 Entry 停用時預設換成系統亮色底，會在深色卡片上刺出白塊
        try:
            e._entry.configure(disabledbackground=COL_FIELD,
                               disabledforeground="#6E6E6E")
        except Exception:
            pass
        return e

    # ---------- 角色管理 ----------

    def refresh_profile_list(self):
        names = uniquify([p.get("name", f"角色{i+1}")
                          for i, p in enumerate(self.cfg["profiles"])])
        self._p_names = names
        self.cmb_p.configure(values=names)
        self.cur_p = min(self.cur_p, len(names) - 1)
        self.cmb_p.set(names[self.cur_p])

    def on_pick_profile(self, choice=None):
        self.commit_ui_safe()
        if choice in self._p_names:
            self.cur_p = self._p_names.index(choice)
        self.load_profile_into_ui()
        self.rebuild_hotkeys()
        self.log(f"切換角色：{self.prof().get('name')}（熱鍵改對應此角色的組合）")

    def add_profile(self):
        self.commit_ui_safe()
        name = self.ask_text("新增角色", "角色名稱：", f"角色{len(self.cfg['profiles'])+1}")
        if not name:
            return
        self.cfg["profiles"].append(
            {"name": name, "rotation": {"actions": []}, "combos": []})
        self.cur_p = len(self.cfg["profiles"]) - 1
        self.refresh_profile_list()
        self.load_profile_into_ui()
        self.rebuild_hotkeys()

    def copy_profile(self):
        self.commit_ui_safe()
        src = self.prof()
        dup = json.loads(json.dumps(src))
        dup["name"] = src.get("name", "角色") + "-複製"
        self.cfg["profiles"].append(dup)
        self.cur_p = len(self.cfg["profiles"]) - 1
        self.refresh_profile_list()
        self.load_profile_into_ui()
        self.rebuild_hotkeys()

    def rename_profile(self):
        p = self.prof()
        name = self.ask_text("重新命名角色", "新名稱：", p.get("name", ""))
        if name:
            p["name"] = name
            self.refresh_profile_list()

    def del_profile(self):
        if len(self.cfg["profiles"]) <= 1:
            self.msg_info("刪除", "至少要保留一個角色。")
            return
        if self.ask_yesno("刪除",
                          f"確定刪除角色「{self.prof().get('name')}」？\n"
                          f"它的技能輪替與所有組合都會一併刪除。",
                          danger=True):
            del self.cfg["profiles"][self.cur_p]
            self.cur_p = 0
            self.refresh_profile_list()
            self.load_profile_into_ui()
            self.rebuild_hotkeys()

    # ---------- 載入 / 寫回 ----------

    def load_profile_into_ui(self):
        self.tree.delete(*self.tree.get_children())
        for a in self.prof().get("rotation", {}).get("actions", []):
            self.tree.insert("", "end", values=(
                a.get("key", ""), a.get("interval", 1.0),
                a.get("jitter", 0.0), a.get("start_delay", 0.0)))
        self.refresh_combo_list()

    def commit_ui(self):
        """把輪替表寫回目前角色（組合由彈窗直接寫入，不經過這裡）。"""
        rows = [self.tree.item(i, "values") for i in self.tree.get_children()]
        self.prof()["rotation"] = {"actions": [
            {"key": r[0], "interval": float(r[1]),
             "jitter": float(r[2]), "start_delay": float(r[3])} for r in rows]}

    def commit_ui_safe(self):
        try:
            self.commit_ui()
        except ValueError:
            pass   # 切換角色時欄位格式錯就放棄這次寫回，不擋操作

    # ---------- 組合管理 ----------

    def refresh_combo_list(self):
        self.tree_c.delete(*self.tree_c.get_children())
        for c in self.prof().get("combos", []):
            repeat = int(c.get("repeat", 0) or 0)
            self.tree_c.insert("", "end", values=(
                c.get("name", "組合"),
                spec_display(normalize_spec(c.get("hotkey"))),
                len(c.get("steps") or []),
                "無限" if repeat == 0 else repeat))

    def _selected_combo_index(self):
        sel = self.tree_c.selection()
        return self.tree_c.index(sel[0]) if sel else None

    def add_combo(self):
        d = ComboDialog(self, None)
        if d.result:
            self.prof()["combos"].append(d.result)
            self._dedupe_hotkey(len(self.prof()["combos"]) - 1)
            self.refresh_combo_list()
            self.rebuild_hotkeys()

    def edit_combo(self):
        ci = self._selected_combo_index()
        if ci is None:
            return
        d = ComboDialog(self, self.prof()["combos"][ci])
        if d.result:
            self.prof()["combos"][ci] = d.result
            self._dedupe_hotkey(ci)
            self.refresh_combo_list()
            self.rebuild_hotkeys()

    def del_combo(self):
        ci = self._selected_combo_index()
        if ci is None:
            return
        c = self.prof()["combos"][ci]
        if self.ask_yesno("刪除", f"確定刪除組合「{c.get('name')}」？", danger=True):
            del self.prof()["combos"][ci]
            self.refresh_combo_list()
            self.rebuild_hotkeys()

    def _dedupe_hotkey(self, keep_idx):
        """同角色內一顆熱鍵只綁一個組合：新設定者優先，解除其他綁定。"""
        combos = self.prof()["combos"]
        spec = normalize_spec(combos[keep_idx].get("hotkey"))
        if not spec:
            return
        for i, c in enumerate(combos):
            if i != keep_idx and normalize_spec(c.get("hotkey")) == spec:
                c.pop("hotkey", None)
                self.log(f"熱鍵 {spec_display(spec)} 改綁到「{combos[keep_idx].get('name')}」，"
                         f"已解除「{c.get('name')}」的綁定")

    # ---------- 輪替動作編輯 ----------

    def ask_text(self, title, label, initial=""):
        return AskDialog(self.root, title, [(label, initial)]).result_one()

    def add_action(self):
        d = AskDialog(self.root, "新增動作",
                      [("按鍵（如 1、q、space、右鍵）", ""),
                       ("間隔秒數", "5.0"), ("浮動±秒", "0"), ("起始延遲秒", "0")])
        vals = d.result()
        if vals and vals[0].strip():
            self.tree.insert("", "end", values=(vals[0].strip(),
                                                vals[1] or "5.0", vals[2] or "0", vals[3] or "0"))

    def edit_action(self):
        sel = self.tree.selection()
        if not sel:
            return
        old = list(self.tree.item(sel[0], "values"))
        d = AskDialog(self.root, "編輯動作",
                      list(zip(["按鍵", "間隔秒數", "浮動±秒", "起始延遲秒"], old)))
        vals = d.result()
        if vals and vals[0].strip():
            self.tree.item(sel[0], values=[vals[0].strip()] + vals[1:])

    def del_action(self):
        for i in self.tree.selection():
            self.tree.delete(i)

    def move_action(self, d):
        sel = self.tree.selection()
        if not sel:
            return
        i = self.tree.index(sel[0])
        self.tree.move(sel[0], "", max(0, i + d))

    # ---------- 控制熱鍵與視窗清單 ----------

    def _t_disp(self):
        return spec_display(self.hk_toggle_spec)

    def _q_disp(self):
        return spec_display(self.hk_quit_spec)

    def _btn_text_start(self):
        return f"▶ 開始輪替（{self._t_disp()}）"

    def _btn_text_pause(self):
        return f"⏸ 暫停（{self._t_disp()}）"

    def _idle_status(self):
        return f"待命中。{self._t_disp()} 開始/暫停輪替，{self._q_disp()} 結束（全域有效）"

    def _rebuild_control_hotkeys(self):
        hks = []
        for spec, fn in ((self.hk_toggle_spec, self.toggle),
                         (self.hk_quit_spec, self.on_close)):
            try:
                combo = keyboard.HotKey.parse(spec)
            except Exception:
                self.log(f"控制熱鍵 {spec!r} 無法解析，已忽略")
                continue
            hks.append(keyboard.HotKey(combo, lambda fn=fn: self.root.after(0, fn)))
        self.ctrl_hotkeys = hks

    def _control_reserved(self, exclude=None):
        """擷取熱鍵時的衝突表：{spec: 用途}。exclude 排除正在重設的那顆。"""
        res = {}
        if exclude != "toggle":
            res[self.hk_toggle_spec] = "「輪替開關」"
        if exclude != "quit":
            res[self.hk_quit_spec] = "「結束程式」"
        for c in self.prof().get("combos", []):
            s = normalize_spec(c.get("hotkey"))
            if s:
                res[s] = f"組合「{c.get('name')}」"
        return res

    def capture_control_hotkey(self, which):
        label = "輪替開關（開始/暫停）" if which == "toggle" else "結束程式"

        def cb(spec):
            if not spec:
                self.log("控制熱鍵不可清除，維持原設定")
                return
            if which == "toggle":
                self.hk_toggle_spec = spec
                self.cfg["global"]["hotkey_toggle"] = spec
                self.lbl_hk_toggle.configure(text=spec_display(spec))
            else:
                self.hk_quit_spec = spec
                self.cfg["global"]["hotkey_quit"] = spec
                self.lbl_hk_quit.configure(text=spec_display(spec))
            self._rebuild_control_hotkeys()
            self.lbl_rot_hint.configure(
                text=f"　{self._t_disp()} 開始／暫停　各鍵獨立倒數，冷卻到了就按")
            if not self.running.is_set():
                self.btn_start.configure(text=self._btn_text_start())
                self.lbl_status.configure(text=self._idle_status())
            self.log(f"{label} 熱鍵改為 {spec_display(spec)}（記得按「儲存設定」）")

        self.capture_hotkey_for(label, cb, self._control_reserved(exclude=which))

    def _pick_focus(self, choice=None):
        if choice == "（不限制）":
            self.var_focus.set("")

    def _refresh_window_list(self, quiet=False):
        if getattr(self, "_win_refresh_busy", False):
            return
        self._win_refresh_busy = True

        def work():
            titles = list_window_titles()
            # 不能在執行緒裡碰 Tk：丟給 poll_queue 在主執行緒套用
            self.msg_q.put(("winlist", (titles, quiet)))
        threading.Thread(target=work, daemon=True).start()

    def _apply_window_list(self, titles, quiet):
        self._win_refresh_busy = False
        self.cmb_focus.configure(values=["（不限制）"] + titles)
        if not quiet:
            self.log(f"視窗清單已更新（{len(titles)} 個），下拉選單選擇即可")

    # ---------- 執行 ----------

    def _global_snapshot(self):
        return {
            "hold_range": self.cfg["global"].get("hold_range", [0.04, 0.09]),
            "global_gap": self.cfg["global"].get("global_gap", 0.12),
            "focus": self.var_focus.get().strip(),
        }

    def _ensure_backend(self):
        if self.backend is None:
            self.backend = make_backend(self.var_di.get(), self.log)
            self.log(f"輸入方式：{self.backend.name}")

    def toggle(self):
        if self.running.is_set():
            self.stop_run()
        else:
            self.start_run()

    def stop_run(self, reason="已暫停"):
        self.running.clear()
        self.resume_state = None
        self.msg_q.put(("status", reason))
        self.msg_q.put(("btn", self._btn_text_start()))

    def start_run(self):
        """F8／開始按鈕：啟動技能輪替。"""
        self.resume_state = None
        try:
            self.commit_ui()
        except ValueError as e:
            self.msg_error("設定有誤", f"輪替清單的數字欄位格式不對：{e}")
            return
        acts = self.prof().get("rotation", {}).get("actions") or []
        if not acts:
            self.msg_info("提示", "技能輪替還沒有任何動作，先按「新增動作」加幾個吧。")
            return
        self._ensure_backend()
        m = {"name": "技能輪替", "mode": "cooldown",
             "actions": json.loads(json.dumps(acts))}
        self.runtime = (m, self._global_snapshot())
        self.active = ("rotation", self.cur_p)
        self.generation += 1
        self.running.set()
        pname = self.prof().get("name")
        self.msg_q.put(("status", f"輪替執行中：{pname}"))
        self.msg_q.put(("btn", self._btn_text_pause()))
        self.log(f"開始輪替：{pname}（{len(acts)} 個動作）")

    def trigger_combo(self, ci):
        """組合熱鍵：插播——輪替暫停，打完自動恢復；插播中再按一次＝取消並立刻恢復。"""
        if self.capture_win is not None or self.coord_win is not None:
            return
        combos = self.prof().get("combos", [])
        if ci >= len(combos):
            return
        c = combos[ci]
        disp = spec_display(normalize_spec(c.get("hotkey")))
        if self.running.is_set() and self.active == ("combo", self.cur_p, ci):
            if self.resume_state is not None:
                self.log(f"{disp} 再次按下，取消「{c.get('name')}」插播")
                self.running.clear()
                self._resume_rotation()
            else:
                self.stop_run(f"{disp}：已停止")
                self.log(f"{disp} 再次按下，停止「{c.get('name')}」")
            return
        steps = c.get("steps") or []
        if not steps:
            self.log(f"「{c.get('name')}」還沒有任何步驟，未啟動（雙擊組合列表可編輯）")
            return
        if (self.running.is_set() and self.resume_state is None
                and self.runtime and self.runtime[0].get("mode") == "cooldown"):
            # 輪替執行中 → 記住現場，組合打完自動接回來
            self.resume_state = (self.runtime, self.active)
            self.log("輪替暫停，組合插播中（打完自動恢復）")
        if self.running.is_set():
            self.running.clear()
        self._ensure_backend()
        m = {"name": c.get("name", "組合"), "mode": "combo",
             "repeat": int(c.get("repeat", 0) or 0),
             "round_gap": list(c.get("round_gap", [1.0, 3.0])),
             "combo_steps": json.loads(json.dumps(steps))}
        self.runtime = (m, self._global_snapshot())
        self.active = ("combo", self.cur_p, ci)
        self.generation += 1
        self.running.set()
        self.msg_q.put(("status", f"組合插播中：{c.get('name')}"))
        self.msg_q.put(("btn", self._btn_text_pause()))
        self.log(f"{disp} 觸發「{c.get('name')}」")

    def _resume_rotation(self):
        """組合插播結束（打完或被取消）：恢復先前的輪替。"""
        st = self.resume_state
        self.resume_state = None
        if not st:
            self.stop_run()
            return
        self.runtime, self.active = st
        self.generation += 1
        self.running.set()
        pi = self.active[1]
        pname = (self.cfg["profiles"][pi].get("name", "")
                 if pi < len(self.cfg["profiles"]) else "")
        self.msg_q.put(("status", f"輪替執行中：{pname}"))
        self.msg_q.put(("btn", self._btn_text_pause()))
        self.log("組合結束，恢復輪替")

    def rebuild_hotkeys(self):
        """依「目前角色」各組合的 hotkey 欄位重建 HotKey 監聽物件。"""
        hks = []
        for i, c in enumerate(self.prof().get("combos", [])):
            spec = normalize_spec(c.get("hotkey"))
            if not spec:
                continue
            try:
                combo = keyboard.HotKey.parse(spec)
            except Exception:
                self.log(f"「{c.get('name')}」的熱鍵 {spec!r} 無法解析，已忽略")
                continue
            hks.append(keyboard.HotKey(
                combo, lambda i=i: self.root.after(0, self.trigger_combo, i)))
        self.macro_hotkeys = hks

    # ---------- 熱鍵擷取（由組合彈窗呼叫） ----------

    def capture_hotkey_for(self, label, callback, reserved=None):
        """開啟擷取視窗；成功按鍵後 callback(spec)，Delete 清除則 callback(None)。
        reserved：{spec: 用途說明}，按到這些鍵會拒絕並提示。"""
        if self.capture_win is not None:
            return
        self.capture_cb = callback
        self.cap_reserved = reserved or {}
        w = ctk.CTkToplevel(self.root, fg_color=COL_CARD)
        w.title("設定熱鍵")
        w.resizable(False, False)
        w.transient(self.root)
        apply_dark_titlebar(w)
        ctk.CTkLabel(w, text=f"為組合「{label}」設定熱鍵",
                     font=self.f_title, text_color=COL_GOLD).pack(padx=28, pady=(20, 6))
        ctk.CTkLabel(w, text="請直接按下想要的按鍵或組合鍵\n（例如 F1、Ctrl+Shift+K）",
                     font=self.f_body, text_color=COL_TEXT,
                     justify="center").pack(padx=28, pady=4)
        ctk.CTkLabel(w, text="Esc 取消　Delete 清除綁定",
                     font=self.f_small, text_color=COL_SUBTEXT).pack(padx=28, pady=(8, 20))
        w.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - w.winfo_reqheight()) // 3
        w.geometry(f"+{max(0, x)}+{max(0, y)}")
        w.protocol("WM_DELETE_WINDOW", self.end_capture)
        self.cap_mods.clear()
        self.capture_win = w

    def end_capture(self):
        if self.capture_win is not None:
            self.capture_win.destroy()
            self.capture_win = None
        self.capture_cb = None
        self.cap_reserved = {}

    def apply_captured(self, spec):
        cb = self.capture_cb
        reserved = self.cap_reserved
        self.end_capture()
        owner = reserved.get(spec)
        if owner:
            self.log(f"{spec_display(spec)} 已被{owner}使用，請換一個熱鍵")
            return
        if "+" not in spec and not spec.startswith("<"):
            self.log(f"提醒：綁定單一字元「{spec.upper()}」，之後在任何地方打這個字都會觸發，"
                     f"建議加上 Ctrl/Shift/Alt")
        if cb:
            cb(spec)

    def _capture_clear(self):
        cb = self.capture_cb
        self.end_capture()
        if cb:
            cb(None)

    # ---------- 座標擷取（由點擊步驟彈窗呼叫） ----------

    def capture_coord_for(self, callback):
        """開啟座標擷取：使用者把游標移到目標位置按 F10，callback((x, y)) 收絕對座標。"""
        if self.coord_win is not None or self.capture_win is not None:
            return
        self.coord_cb = callback
        w = ctk.CTkToplevel(self.root, fg_color=COL_CARD)
        w.title("抓取座標")
        w.resizable(False, False)
        w.attributes("-topmost", True)   # 蓋在遊戲視窗上面也看得到說明
        apply_dark_titlebar(w)
        ctk.CTkLabel(w, text="抓取座標", font=self.f_title,
                     text_color=COL_GOLD).pack(padx=28, pady=(20, 6))
        ctk.CTkLabel(w, text="切到目標視窗，把滑鼠移到要點擊的位置\n然後按 F10",
                     font=self.f_body, text_color=COL_TEXT,
                     justify="center").pack(padx=28, pady=4)
        ctk.CTkLabel(w, text="Esc 取消",
                     font=self.f_small, text_color=COL_SUBTEXT).pack(padx=28, pady=(8, 20))
        w.update_idletasks()
        # 靠螢幕右上角，避免擋到目標視窗中央
        x = self.root.winfo_screenwidth() - w.winfo_reqwidth() - 40
        w.geometry(f"+{max(0, x)}+60")
        w.protocol("WM_DELETE_WINDOW", self.end_coord_capture)
        self.coord_win = w

    def end_coord_capture(self):
        if self.coord_win is not None:
            self.coord_win.destroy()
            self.coord_win = None
        self.coord_cb = None

    def _apply_coord(self, pos):
        cb = self.coord_cb
        self.end_coord_capture()
        if cb:
            cb(pos)

    # ---------- 全域按鍵監聽 ----------

    def on_hotkey(self, key):
        mod = MOD_KEYS.get(key)
        if mod:
            self.cap_mods.add(mod)
        try:
            ck = self.hotkeys.canonical(key)
        except Exception:
            ck = key

        if self.coord_win is not None:        # 座標擷取模式：F10 抓游標位置
            if key == Key.esc:
                self.root.after(0, self.end_coord_capture)
            elif key == Key.f10:
                px, py = self._mouse.position
                self.root.after(0, self._apply_coord, (int(px), int(py)))
            return

        if self.capture_win is not None:      # 擷取模式：這次按鍵拿來當熱鍵
            if mod:
                return
            if key == Key.esc:
                self.root.after(0, self.end_capture)
                return
            if key in (Key.delete, Key.backspace):
                self.root.after(0, self._capture_clear)
                return
            if isinstance(ck, Key):
                token = f"<{ck.name}>"
            else:
                ch = getattr(ck, "char", None)
                token = ch.lower() if (ch and ch.isprintable()) else None
            if token is None:
                self.log("無法辨識這個按鍵，請換一個")
                return
            mods = [m for m in MOD_ORDER if m in self.cap_mods]
            spec = "+".join([f"<{m}>" for m in mods] + [token])
            self.root.after(0, self.apply_captured, spec)
            return

        for hk in self.ctrl_hotkeys + self.macro_hotkeys:
            hk.press(ck)

    def on_hotkey_release(self, key):
        mod = MOD_KEYS.get(key)
        if mod:
            self.cap_mods.discard(mod)
        try:
            ck = self.hotkeys.canonical(key)
        except Exception:
            ck = key
        for hk in self.ctrl_hotkeys + self.macro_hotkeys:
            hk.release(ck)

    # ---------- 背景執行緒 ----------

    def worker(self):
        gen = -1
        timers, step, nxt, rounds = {}, 0, 0.0, 0
        while not self.stopping.is_set():
            time.sleep(0.05)
            if not self.running.is_set() or self.runtime is None:
                gen = -1
                continue
            m, g = self.runtime
            now = time.monotonic()

            focus_ok = (not g["focus"]) or (g["focus"].lower() in active_window_title().lower())
            if gen != self.generation or not focus_ok:
                gen = self.generation
                timers = {i: now + a.get("start_delay", 0.0)
                          for i, a in enumerate(m.get("actions", []))}
                step, nxt, rounds = 0, now, 0
                continue

            try:
                mode = m.get("mode", "cooldown")
                if mode == "cooldown":
                    for i, a in enumerate(m.get("actions", [])):
                        if now >= timers.get(i, now):
                            self.fire(a["key"], g)
                            j = a.get("jitter", 0.0)
                            timers[i] = time.monotonic() + a["interval"] + random.uniform(-j, j)
                            time.sleep(g["global_gap"])
                            break
                else:  # combo：整組照順序執行（按鍵或點擊），步驟間隨機延遲，共 N 輪
                    steps = m.get("combo_steps", [])
                    if steps and now >= nxt:
                        s = steps[step]
                        self.fire_step(s, g)
                        step += 1
                        if step >= len(steps):
                            step = 0
                            rounds += 1
                            repeat = int(m.get("repeat", 0))
                            if repeat and rounds >= repeat:
                                self.msg_q.put(("log", f"── 第 {rounds} 輪完成（共 {repeat} 輪）"))
                                self.running.clear()
                                if self.resume_state is not None:
                                    self.msg_q.put(("resume", None))   # 主執行緒恢復輪替
                                else:
                                    self.msg_q.put(("status", f"組合完成 {rounds} 輪，已自動停止"))
                                    self.msg_q.put(("btn", self._btn_text_start()))
                                continue
                            gmin, gmax = m.get("round_gap", [1.0, 3.0])
                            rest = random.uniform(gmin, gmax)
                            nxt = time.monotonic() + rest
                            self.msg_q.put(("log", f"── 第 {rounds} 輪完成"
                                            + (f"（共 {repeat} 輪）" if repeat else "")
                                            + f"，休息 {rest:.2f} 秒"))
                        else:
                            nxt = time.monotonic() + random.uniform(
                                s.get("wait_min", 0.3), s.get("wait_max", 0.8))
            except Exception as e:
                self.running.clear()
                self.resume_state = None
                self.msg_q.put(("status", "發生錯誤，已暫停"))
                self.msg_q.put(("btn", self._btn_text_start()))
                self.msg_q.put(("log", f"錯誤：{e}"))

    def fire(self, key, g):
        lo, hi = g["hold_range"]
        self.backend.tap(key, random.uniform(lo, hi))
        self.count += 1
        self.msg_q.put(("log", f"{key}  (#{self.count})"))

    def fire_step(self, s, g):
        """組合步驟：按鍵或滑鼠點擊（點擊座標相對於目標視窗左上角）。"""
        if s.get("type") != "click":
            self.fire(s["key"], g)
            return
        dx, dy = s.get("pos", [0, 0])
        rect = window_rect(s.get("window", ""))
        if rect:
            x, y = rect[0] + int(dx), rect[1] + int(dy)
        else:
            x, y = int(dx), int(dy)   # 沒指定視窗或找不到：當絕對座標
        lo, hi = g["hold_range"]
        self.backend.click(x, y, s.get("button", "left"), random.uniform(lo, hi))
        self.count += 1
        wn = s.get("window") or "絕對"
        self.msg_q.put(("log",
                        f"{BTN_DISP.get(s.get('button', 'left'), '左鍵')}點擊 "
                        f"{wn} ({x}, {y})  (#{self.count})"))

    # ---------- 訊息 / 收尾 ----------

    def log(self, msg):
        self.msg_q.put(("log", msg))

    def poll_queue(self):
        try:
            while True:
                kind, val = self.msg_q.get_nowait()
                if kind == "log":
                    self.txt.configure(state="normal")
                    self.txt.insert("end", f"[{time.strftime('%H:%M:%S')}] {val}\n")
                    self.txt.see("end")
                    self.txt.configure(state="disabled")
                elif kind == "status":
                    self.lbl_status.configure(text=val)
                elif kind == "btn":
                    self.btn_start.configure(text=val)
                elif kind == "resume":
                    self._resume_rotation()
                elif kind == "winlist":
                    self._apply_window_list(*val)
        except queue.Empty:
            pass
        if not self.stopping.is_set():
            self.root.after(100, self.poll_queue)

    def on_close(self):
        self.stopping.set()
        self.running.clear()
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        self.root.destroy()


# ---------------- 主題化對話框 ----------------

class BaseModal(ctk.CTkToplevel):
    """黑金風格的 modal 底座：置中於父視窗、深色標題列、grab。"""

    def __init__(self, parent, title):
        super().__init__(parent, fg_color=COL_CARD)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        apply_dark_titlebar(self)

    def run_modal(self, parent, focus_widget=None):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        try:
            pw, ph = parent.winfo_width(), parent.winfo_height()
            if pw < 50:
                raise ValueError("parent not mapped")
            x = parent.winfo_rootx() + (pw - w) // 2
            y = parent.winfo_rooty() + (ph - h) // 3
        except Exception:
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.wait_visibility()
        self.grab_set()
        (focus_widget or self).focus_set()
        parent.wait_window(self)


class AskDialog(BaseModal):
    """多欄位輸入對話框。"""

    def __init__(self, parent, title, fields):
        super().__init__(parent, title)
        self._result = None
        self.vars = []
        f_body = make_font(13)
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(padx=20, pady=(18, 8))
        first_entry = None
        for i, (label, initial) in enumerate(fields):
            ctk.CTkLabel(grid, text=label, font=f_body, text_color=COL_TEXT,
                         anchor="e").grid(row=i, column=0, sticky="e", padx=(0, 10), pady=5)
            v = tk.StringVar(value=str(initial))
            e = ctk.CTkEntry(grid, width=210, height=28, textvariable=v, font=f_body,
                             fg_color=COL_FIELD, border_color=COL_BORDER,
                             text_color=COL_TEXT, corner_radius=6)
            e.grid(row=i, column=1, pady=5)
            if first_entry is None:
                first_entry = e
            self.vars.append(v)
        btnrow = ctk.CTkFrame(self, fg_color="transparent")
        btnrow.pack(fill="x", padx=20, pady=(4, 16))
        make_btn(btnrow, "確定", self.ok, kind="primary", width=88).pack(side="right")
        make_btn(btnrow, "取消", self.destroy, width=88).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.run_modal(parent, focus_widget=first_entry)

    def ok(self):
        self._result = [v.get() for v in self.vars]
        self.destroy()

    def result(self):
        return self._result

    def result_one(self):
        return self._result[0].strip() if self._result else None


class MsgBox(BaseModal):
    """取代原生 messagebox 的黑金訊息框。ask=True 時提供 確定/取消，結果在 .answer。"""

    def __init__(self, parent, title, message, kind="info", ask=False, danger=False):
        super().__init__(parent, title)
        self.answer = False
        accent = COL_DANGER_TEXT if (kind == "error" or danger) else COL_GOLD
        ctk.CTkLabel(self, text=title, font=make_font(15, "bold"),
                     text_color=accent).pack(anchor="w", padx=24, pady=(18, 4))
        ctk.CTkLabel(self, text=message, font=make_font(13), text_color=COL_TEXT,
                     justify="left", wraplength=380).pack(anchor="w", padx=24, pady=4)
        btnrow = ctk.CTkFrame(self, fg_color="transparent")
        btnrow.pack(fill="x", padx=20, pady=(10, 16))
        ok_kind = "danger_solid" if danger else "primary"
        make_btn(btnrow, "確定", self._yes, kind=ok_kind, width=88).pack(side="right")
        if ask:
            make_btn(btnrow, "取消", self.destroy, width=88).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda e: self._yes())
        self.bind("<Escape>", lambda e: self.destroy())
        self.run_modal(parent)

    def _yes(self):
        self.answer = True
        self.destroy()


class ComboDialog(BaseModal):
    """組合的新增／編輯彈窗：名稱、熱鍵、輪數、休息秒數與步驟表全部在這裡。"""

    def __init__(self, app, combo=None):
        super().__init__(app.root, "編輯組合" if combo else "新增組合")
        self.app = app
        self.result = None
        c = combo or {}
        self.hotkey_spec = normalize_spec(c.get("hotkey"))
        f_body, f_bold = app.f_body, app.f_bold

        # 名稱與熱鍵
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(18, 4))
        ctk.CTkLabel(top, text="名稱", font=f_bold, text_color=COL_SUBTEXT,
                     width=36, anchor="w").pack(side="left")
        self.var_name = tk.StringVar(value=c.get("name", ""))
        name_entry = app._entry(top, self.var_name, width=180)
        name_entry.pack(side="left", padx=(2, 14))
        ctk.CTkLabel(top, text="熱鍵", font=f_bold, text_color=COL_SUBTEXT).pack(side="left")
        self.lbl_hotkey = ctk.CTkLabel(top, text=spec_display(self.hotkey_spec),
                                       font=f_body, text_color=COL_GOLD,
                                       fg_color=COL_FIELD, corner_radius=6,
                                       width=104, height=26)
        self.lbl_hotkey.pack(side="left", padx=6)
        make_btn(top, "設定", self._capture, width=52, font=f_body).pack(side="left", padx=2)
        make_btn(top, "清除", self._clear_hotkey, width=52, font=f_body).pack(side="left", padx=2)

        # 輪數與休息
        prow = ctk.CTkFrame(self, fg_color="transparent")
        prow.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(prow, text="重複", font=f_bold, text_color=COL_SUBTEXT,
                     width=36, anchor="w").pack(side="left")
        self.var_repeat = tk.StringVar(value=str(c.get("repeat", 10)))
        app._entry(prow, self.var_repeat, width=56).pack(side="left", padx=(2, 4))
        ctk.CTkLabel(prow, text="輪（0 = 無限）　每輪之間休息", font=f_body,
                     text_color=COL_TEXT).pack(side="left")
        gmin, gmax = c.get("round_gap", [1.0, 3.0])
        self.var_gap_min = tk.StringVar(value=str(gmin))
        self.var_gap_max = tk.StringVar(value=str(gmax))
        app._entry(prow, self.var_gap_min, width=56).pack(side="left", padx=4)
        ctk.CTkLabel(prow, text="～", font=f_body, text_color=COL_SUBTEXT).pack(side="left")
        app._entry(prow, self.var_gap_max, width=56).pack(side="left", padx=4)
        ctk.CTkLabel(prow, text="秒（每輪隨機抽）", font=f_body,
                     text_color=COL_TEXT).pack(side="left")

        # 步驟表（按鍵與滑鼠點擊混排，由上到下依序執行）
        self.steps = json.loads(json.dumps(c.get("steps", [])))
        ctk.CTkLabel(self, text="步驟（由上到下依序執行，步驟間隨機延遲）",
                     font=f_bold, text_color=COL_GOLD).pack(anchor="w", padx=20, pady=(8, 2))
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 6))
        sbtns = ctk.CTkFrame(body, fg_color="transparent")
        sbtns.pack(side="right", fill="y", padx=(10, 0))
        wrap = ctk.CTkFrame(body, fg_color=COL_TREE_BG, corner_radius=8)
        wrap.pack(side="left", fill="both", expand=True)
        self.tree_s = ttk.Treeview(wrap, style="Gold.Treeview", show="headings",
                                   selectmode="browse", height=8)
        ssb = ctk.CTkScrollbar(wrap, command=self.tree_s.yview, fg_color="transparent",
                               button_color="#3A3A3A", button_hover_color="#4E4E4E")
        ssb.pack(side="right", fill="y", padx=(0, 4), pady=8)
        self.tree_s.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self.tree_s.configure(yscrollcommand=ssb.set,
                              columns=("what", "detail", "wmin", "wmax"))
        for cc, h, w in (("what", "動作", 80), ("detail", "內容", 190),
                         ("wmin", "最短等待(秒)", 96), ("wmax", "最長等待(秒)", 96)):
            self.tree_s.heading(cc, text=h)
            self.tree_s.column(cc, width=w, anchor="center")
        self._refresh_steps()
        self.tree_s.bind("<Double-1>", lambda e: self._edit_step())
        make_btn(sbtns, "新增按鍵", self._add_step, kind="primary",
                 width=88, height=28, font=f_body).pack(pady=(8, 2))
        make_btn(sbtns, "新增點擊", self._add_click_step, kind="primary",
                 width=88, height=28, font=f_body).pack(pady=2)
        make_btn(sbtns, "編輯", self._edit_step, width=88, height=28,
                 font=f_body).pack(pady=2)
        make_btn(sbtns, "刪除", self._del_step, kind="danger", width=88, height=28,
                 font=f_body).pack(pady=2)
        make_btn(sbtns, "上移", lambda: self._move_step(-1), width=88, height=28,
                 font=f_body).pack(pady=2)
        make_btn(sbtns, "下移", lambda: self._move_step(1), width=88, height=28,
                 font=f_body).pack(pady=2)

        # 底部按鈕
        brow = ctk.CTkFrame(self, fg_color="transparent")
        brow.pack(fill="x", padx=20, pady=(4, 16))
        make_btn(brow, "儲存", self._save, kind="primary", width=88).pack(side="right")
        make_btn(brow, "取消", self.destroy, width=88).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())
        self.run_modal(app.root, focus_widget=name_entry)

    # ----- 熱鍵 -----

    def _capture(self):
        reserved = {self.app.hk_toggle_spec: "「輪替開關」",
                    self.app.hk_quit_spec: "「結束程式」"}
        self.app.capture_hotkey_for(self.var_name.get().strip() or "組合",
                                    self._on_captured, reserved)

    def _on_captured(self, spec):
        self.hotkey_spec = spec
        self.lbl_hotkey.configure(text=spec_display(spec))

    def _clear_hotkey(self):
        self._on_captured(None)

    # ----- 步驟編輯（子彈窗疊在本彈窗上，關閉後把 grab 拿回來） -----

    def _ask(self, title, fields):
        d = AskDialog(self, title, fields)
        try:
            self.grab_set()
        except Exception:
            pass
        return d.result()

    def _refresh_steps(self, keep=None):
        self.tree_s.delete(*self.tree_s.get_children())
        for s in self.steps:
            if s.get("type") == "click":
                what = BTN_DISP.get(s.get("button", "left"), "左鍵") + "點擊"
                x, y = s.get("pos", [0, 0])
                detail = f"{s.get('window') or '絕對'} ({x}, {y})"
            else:
                what, detail = "按鍵", s.get("key", "")
            self.tree_s.insert("", "end", values=(
                what, detail, s.get("wait_min", 0.3), s.get("wait_max", 0.8)))
        kids = self.tree_s.get_children()
        if keep is not None and kids:
            i = min(keep, len(kids) - 1)
            self.tree_s.selection_set(kids[i])

    def _sel_index(self):
        sel = self.tree_s.selection()
        return self.tree_s.index(sel[0]) if sel else None

    def _add_step(self):
        vals = self._ask("新增按鍵步驟",
                         [("按鍵（如 1、q、space、右鍵）", ""),
                          ("最短等待秒", "0.3"), ("最長等待秒", "0.8")])
        if vals and vals[0].strip():
            try:
                s = {"key": vals[0].strip(),
                     "wait_min": float(vals[1] or 0.3),
                     "wait_max": float(vals[2] or 0.8)}
            except ValueError:
                MsgBox(self, "設定有誤", "等待秒數要是數字。", kind="error")
                self.grab_set()
                return
            self.steps.append(s)
            self._refresh_steps(keep=len(self.steps) - 1)

    def _add_click_step(self):
        d = ClickStepDialog(self, self.app, None)
        try:
            self.grab_set()
        except Exception:
            pass
        if d.result:
            self.steps.append(d.result)
            self._refresh_steps(keep=len(self.steps) - 1)

    def _edit_step(self):
        i = self._sel_index()
        if i is None:
            return
        s = self.steps[i]
        if s.get("type") == "click":
            d = ClickStepDialog(self, self.app, s)
            try:
                self.grab_set()
            except Exception:
                pass
            if d.result:
                self.steps[i] = d.result
                self._refresh_steps(keep=i)
        else:
            vals = self._ask("編輯按鍵步驟",
                             list(zip(["按鍵", "最短等待秒", "最長等待秒"],
                                      [s.get("key", ""), s.get("wait_min", 0.3),
                                       s.get("wait_max", 0.8)])))
            if vals and vals[0].strip():
                try:
                    self.steps[i] = {"key": vals[0].strip(),
                                     "wait_min": float(vals[1] or 0.3),
                                     "wait_max": float(vals[2] or 0.8)}
                except ValueError:
                    MsgBox(self, "設定有誤", "等待秒數要是數字。", kind="error")
                    self.grab_set()
                    return
                self._refresh_steps(keep=i)

    def _del_step(self):
        i = self._sel_index()
        if i is None:
            return
        del self.steps[i]
        self._refresh_steps(keep=i)

    def _move_step(self, d):
        i = self._sel_index()
        if i is None:
            return
        j = max(0, min(len(self.steps) - 1, i + d))
        self.steps[i], self.steps[j] = self.steps[j], self.steps[i]
        self._refresh_steps(keep=j)

    # ----- 儲存 -----

    def _save(self):
        name = self.var_name.get().strip()
        if not name:
            MsgBox(self, "少了名稱", "幫這個組合取個名字吧。")
            self.grab_set()
            return
        try:
            repeat = int(float(self.var_repeat.get() or 0))
            gmin = float(self.var_gap_min.get() or 0)
            gmax = float(self.var_gap_max.get() or 0)
        except ValueError as e:
            MsgBox(self, "設定有誤", f"數字欄位格式不對：{e}", kind="error")
            self.grab_set()
            return
        out = {"name": name, "repeat": repeat, "round_gap": [gmin, gmax],
               "steps": self.steps}
        if self.hotkey_spec:
            out["hotkey"] = self.hotkey_spec
        self.result = out
        self.destroy()


class ClickStepDialog(BaseModal):
    """滑鼠點擊步驟的編輯彈窗：目標視窗、相對座標（F10 抓取）、滑鼠鍵與等待秒數。"""

    def __init__(self, parent, app, step=None):
        super().__init__(parent, "編輯點擊步驟" if step else "新增點擊步驟")
        self.app = app
        self.result = None
        s = step or {}
        f_body, f_bold = app.f_body, app.f_bold

        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(fill="x", padx=20, pady=(18, 4))
        ctk.CTkLabel(r1, text="目標視窗含", font=f_bold,
                     text_color=COL_SUBTEXT).pack(side="left")
        self.var_window = tk.StringVar(value=s.get("window", ""))
        app._entry(r1, self.var_window, width=180).pack(side="left", padx=6)
        ctk.CTkLabel(r1, text="（留空 = 絕對座標）", font=f_body,
                     text_color=COL_SUBTEXT).pack(side="left")

        r2 = ctk.CTkFrame(self, fg_color="transparent")
        r2.pack(fill="x", padx=20, pady=4)
        px, py = s.get("pos", ["", ""])
        ctk.CTkLabel(r2, text="座標 X", font=f_bold,
                     text_color=COL_SUBTEXT).pack(side="left")
        self.var_x = tk.StringVar(value=str(px))
        app._entry(r2, self.var_x, width=70).pack(side="left", padx=(6, 10))
        ctk.CTkLabel(r2, text="Y", font=f_bold, text_color=COL_SUBTEXT).pack(side="left")
        self.var_y = tk.StringVar(value=str(py))
        app._entry(r2, self.var_y, width=70).pack(side="left", padx=(6, 12))
        make_btn(r2, "抓取座標（F10）", self._grab, kind="primary",
                 width=130, height=28, font=f_body).pack(side="left")

        r3 = ctk.CTkFrame(self, fg_color="transparent")
        r3.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(r3, text="滑鼠鍵", font=f_bold,
                     text_color=COL_SUBTEXT).pack(side="left")
        self.seg_btn = ctk.CTkSegmentedButton(
            r3, values=list(BTN_DISP.values()), font=f_body, height=28,
            corner_radius=8, fg_color=COL_FIELD, selected_color=COL_GOLD_DARK,
            selected_hover_color=COL_GOLD_DARK_HOVER,
            unselected_color="#2C2C2C", unselected_hover_color="#383838",
            text_color="#EDEAE0")
        self.seg_btn.set(BTN_DISP.get(s.get("button", "left"), "左鍵"))
        self.seg_btn.pack(side="left", padx=(8, 16))
        ctk.CTkLabel(r3, text="點完等待", font=f_body,
                     text_color=COL_TEXT).pack(side="left")
        self.var_wmin = tk.StringVar(value=str(s.get("wait_min", 0.3)))
        self.var_wmax = tk.StringVar(value=str(s.get("wait_max", 0.8)))
        app._entry(r3, self.var_wmin, width=56).pack(side="left", padx=4)
        ctk.CTkLabel(r3, text="～", font=f_body, text_color=COL_SUBTEXT).pack(side="left")
        app._entry(r3, self.var_wmax, width=56).pack(side="left", padx=4)
        ctk.CTkLabel(r3, text="秒", font=f_body, text_color=COL_TEXT).pack(side="left")

        self.lbl_hint = ctk.CTkLabel(
            self, text="「抓取座標」：切到目標視窗、滑鼠移到位置後按 F10，"
                       "會自動換算成相對於該視窗的座標",
            font=app.f_small, text_color=COL_SUBTEXT, wraplength=430, justify="left")
        self.lbl_hint.pack(anchor="w", padx=20, pady=(6, 0))

        brow = ctk.CTkFrame(self, fg_color="transparent")
        brow.pack(fill="x", padx=20, pady=(10, 16))
        make_btn(brow, "儲存", self._save, kind="primary", width=88).pack(side="right")
        make_btn(brow, "取消", self.destroy, width=88).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())
        self.run_modal(parent)

    def _grab(self):
        self.app.capture_coord_for(self._on_coord)

    def _on_coord(self, pos):
        kw = self.var_window.get().strip()
        if not kw:
            kw = active_window_title()
            self.var_window.set(kw)
        rect = window_rect(kw)
        if rect:
            rx, ry = pos[0] - rect[0], pos[1] - rect[1]
            self.var_x.set(str(rx))
            self.var_y.set(str(ry))
            self.lbl_hint.configure(
                text=f"已抓取：視窗「{kw}」相對座標 ({rx}, {ry})", text_color=COL_GOLD)
        else:
            self.var_window.set("")
            self.var_x.set(str(pos[0]))
            self.var_y.set(str(pos[1]))
            self.lbl_hint.configure(
                text=f"找不到視窗「{kw}」，已存為絕對座標 ({pos[0]}, {pos[1]})",
                text_color=COL_DANGER_TEXT)

    def _save(self):
        try:
            x = int(float(self.var_x.get()))
            y = int(float(self.var_y.get()))
            wmin = float(self.var_wmin.get() or 0.3)
            wmax = float(self.var_wmax.get() or 0.8)
        except ValueError:
            MsgBox(self, "設定有誤", "座標與等待秒數要是數字（可用「抓取座標」自動填入）。",
                   kind="error")
            self.grab_set()
            return
        self.result = {"type": "click",
                       "window": self.var_window.get().strip(),
                       "pos": [x, y],
                       "button": DISP_BTN.get(self.seg_btn.get(), "left"),
                       "wait_min": wmin, "wait_max": wmax}
        self.destroy()


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    root = ctk.CTk(fg_color=COL_BG)
    apply_dark_titlebar(root)
    App(root)
    root.mainloop()
