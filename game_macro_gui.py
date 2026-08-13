#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
game_macro_gui.py — 重複按鍵工具（圖形介面版，黑金主題）

架構：角色 → 一份「技能輪替」＋ 多個「組合」
    技能輪替（冷卻）：主畫面直接編輯，F8 開始／暫停後常駐執行，
        各鍵獨立倒數、冷卻到了就按。
    組合：一次全部列出，各自綁熱鍵；按熱鍵隨時插播（輪替暫停），
        打完 N 輪自動恢復輪替。新增／編輯組合走獨立彈窗。

安裝:
    uv sync                        # 依賴：customtkinter、pynput
    # Windows 建議加裝 pydirectinput（uv 會依平台自動安裝）

執行:
    uv run game_macro_gui.py

全域熱鍵（皆可自訂）：
    開始 / 暫停技能輪替（預設 F8，可於全域設定更改）
    結束程式（預設 F9，可於全域設定更改）
    各組合的插播熱鍵可在組合彈窗中自訂（單鍵或組合鍵，如 F1、Ctrl+Shift+K）

按鍵欄位除了鍵盤鍵（1、q、space、f5...）也支援滑鼠：右鍵、左鍵、中鍵

設定檔為同目錄的 profiles.json（會自動從舊版格式升級）。
"""

import base64
import json
import os
import queue
import zlib
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

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
            log("未安裝 pydirectinput，改用 pynput（目標程式若沒反應請安裝它）")
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


def play_alert():
    """明顯的警示音；非阻塞。"""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["afplay", "/System/Library/Sounds/Sosumi.aiff"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        else:
            sys.stdout.write("\a")
    except Exception:
        pass


# ---------------- 螢幕區域監看（技能消失偵測） ----------------

GRID_N = 24        # 比對取樣格：24×24 點，對縮放（Retina）不敏感
_SCT = None        # mss 實例快取（只在主執行緒使用）


def grab_region(x, y, w, h):
    """抓螢幕區域，回傳 (BGRA bytes, 實際寬, 實際高)。macOS 需要螢幕錄製權限。"""
    global _SCT
    import mss
    if _SCT is None:
        _SCT = getattr(mss, "MSS", mss.mss)()
    img = _SCT.grab({"left": int(x), "top": int(y), "width": int(w), "height": int(h)})
    return bytes(img.raw), img.width, img.height


def sample_grid(raw, w, h, n=GRID_N):
    """把區域畫面取樣成 n×n 個 BGR 點，作為比對指紋。"""
    out = bytearray()
    for j in range(n):
        y = int((j + 0.5) * h / n)
        base = y * w
        for i in range(n):
            x = int((i + 0.5) * w / n)
            off = (base + x) * 4
            out += raw[off:off + 3]
    return bytes(out)


def photo_to_bgr(photo):
    """tk.PhotoImage → (BGR bytes, w, h)，供多圖示模板搜尋使用。"""
    w, h = photo.width(), photo.height()
    out = bytearray()
    for y in range(h):
        for x in range(w):
            r, g, b = photo.get(x, y)[:3]
            out += bytes((b, g, r))
    return bytes(out), w, h


def _np_bgr(raw_bgra, w, h):
    """BGRA 螢幕原始資料 → numpy (h, w, 3) BGR int16 陣列。"""
    import numpy as np
    return (np.frombuffer(raw_bgra, dtype=np.uint8)
            .reshape(h, w, 4)[:, :, :3].astype(np.int16))


def _resize_nn(arr, scale):
    """最近鄰縮放（處理 Retina／圖示尺寸差）。"""
    import numpy as np
    h, w = arr.shape[:2]
    nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
    yi = (np.arange(nh) * h / nh).astype(int)
    xi = (np.arange(nw) * w / nw).astype(int)
    return arr[yi][:, xi]

ICON_SCALES = (1.0, 2.0, 1.5, 1.25, 0.75, 0.5, 1.75, 0.875)   # 2.0 = Retina 常見


def icon_search(region, tmpl):
    """在 region 裡滑動搜尋 tmpl，回傳 (相似度 0~1, (x, y))。
    三段式：自適應步幅粗掃 → 中修 → 逐像素細修，兼顧速度與精度。"""
    import numpy as np
    H, W = region.shape[:2]
    th, tw = tmpl.shape[:2]
    if th > H or tw > W or th < 4 or tw < 4:
        return 0.0, None
    state = [1e18, 0, 0]   # best_d, bx, by

    def scan(x0, x1, y0, y1, step):
        for y in range(max(0, y0), min(H - th, y1) + 1, step):
            row = region[y:y + th]
            for x in range(max(0, x0), min(W - tw, x1) + 1, step):
                d = np.abs(row[:, x:x + tw] - tmpl).mean()
                if d < state[0]:
                    state[0], state[1], state[2] = d, x, y

    stride = max(4, min(th, tw) // 4)
    scan(0, W - tw, 0, H - th, stride)
    if stride > 6:
        scan(state[1] - stride, state[1] + stride,
             state[2] - stride, state[2] + stride, 2)
    scan(state[1] - 3, state[1] + 3, state[2] - 3, state[2] + 3, 1)
    return 1.0 - state[0] / 255.0, (state[1], state[2])


def icon_search_multiscale(region, tmpl, scales=ICON_SCALES):
    """對多個縮放比例搜尋，回傳 (相似度, (x, y), 縮放後模板尺寸, 最佳比例)。"""
    best = (0.0, None, None, None)
    for s in scales:
        t = _resize_nn(tmpl, s)
        sim, loc = icon_search(region, t)
        if sim > best[0]:
            best = (sim, loc, (t.shape[1], t.shape[0]), s)
    return best


def photo_sample_grid(photo, n=GRID_N):
    """tk.PhotoImage → 取樣指紋（與 sample_grid 相同的 BGR 排列），
    供使用者自行上傳圖示檔當基準圖。"""
    w, h = photo.width(), photo.height()
    out = bytearray()
    for j in range(n):
        y = int((j + 0.5) * h / n)
        for i in range(n):
            x = int((i + 0.5) * w / n)
            r, g, b = photo.get(x, y)[:3]
            out += bytes((b, g, r))
    return bytes(out)


def grid_similarity(a, b):
    """兩張取樣指紋的相似度 0.0～1.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    d = sum(abs(p - q) for p, q in zip(a, b))
    return 1.0 - d / (len(a) * 255)


def ocr_text(raw, w, h):
    """對 BGRA 畫面做文字辨識。macOS 用系統 Vision（支援中文）；
    其他平台暫不支援，回傳 None。失敗回傳空字串。"""
    if sys.platform != "darwin":
        return None
    try:
        import Quartz
        import Vision
        provider = Quartz.CGDataProviderCreateWithData(None, bytes(raw), len(raw), None)
        cgimg = Quartz.CGImageCreate(
            w, h, 8, 32, w * 4, Quartz.CGColorSpaceCreateDeviceRGB(),
            Quartz.kCGImageAlphaNoneSkipFirst | Quartz.kCGBitmapByteOrder32Little,
            provider, None, False, Quartz.kCGRenderingIntentDefault)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cgimg, None)
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLanguages_(["zh-Hant", "en-US"])
        req.setUsesLanguageCorrection_(False)
        ok, _err = handler.performRequests_error_([req], None)
        if not ok:
            return ""
        out = []
        for obs in (req.results() or []):
            c = obs.topCandidates_(1)
            if c and len(c):
                out.append(str(c[0].string()))
        return "\n".join(out)
    except Exception:
        return ""


def notify(title, message):
    """macOS 通知中心橫幅；其他平台靜默略過。非阻塞。"""
    if sys.platform != "darwin":
        return
    try:
        esc = lambda s: str(s).replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(
            ["osascript", "-e",
             f'display notification "{esc(message)}" with title "{esc(title)}"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


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
        self.watch_on = False        # 技能監看中
        self.watch_ref = b""         # 監看基準指紋（單一區域比對模式）
        self.watch_missing = {}      # {名稱: 消失起算時間}（兩種模式共用）
        self.watch_snooze = False    # 按過「知道了」，全部恢復前不再警報
        self.alarm = None            # 警報視窗
        self._watch_black_warned = False
        self.watch_thread = None     # 圖示搜尋模式的背景執行緒
        self._watch_icon_locs = {}   # {名稱: 找到的邏輯座標框}（覆蓋層顯示）
        self._watch_found = (0, 0)   # (找到數, 總數)（覆蓋層顯示）
        self.chat_on = False         # 聊天文字觸發中
        self.chat_thread = None
        self._chat_present = {}      # 各關鍵字目前是否在畫面上（出現的瞬間才觸發）
        self._chat_last = {}         # 各關鍵字上次觸發時間（冷卻用）
        self.overlay = None          # 監看範圍覆蓋層（透明、點擊穿透）
        self._watch_last_sim = None  # 最近一次技能比對相似度（覆蓋層顯示用）
        self._chat_last_text = ""    # 最近一次聊天辨識結果（覆蓋層顯示用）

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
        g["notify_events"] = bool(self.var_notify.get())
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
        r1.pack(fill="x", padx=12, pady=(10, 3))
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
        r1b = ctk.CTkFrame(sel, fg_color="transparent")
        r1b.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(r1b, text="技能監看", font=self.f_small,
                     text_color=COL_SUBTEXT).pack(side="left")
        make_btn(r1b, "監看設定", self.open_watch_dialog, width=84, height=28,
                 font=self.f_body).pack(side="left", padx=(6, 2))
        self.btn_watch = make_btn(r1b, "開始監看", self.toggle_watch, width=84,
                                  height=28, font=self.f_body)
        self.btn_watch.pack(side="left", padx=2)
        ctk.CTkLabel(r1b, text="　聊天觸發", font=self.f_small,
                     text_color=COL_SUBTEXT).pack(side="left")
        make_btn(r1b, "觸發設定", self.open_chat_dialog, width=84, height=28,
                 font=self.f_body).pack(side="left", padx=(6, 2))
        self.btn_chat = make_btn(r1b, "開始觸發", self.toggle_chat, width=84,
                                 height=28, font=self.f_body)
        self.btn_chat.pack(side="left", padx=2)
        self.btn_overlay = make_btn(r1b, "顯示範圍", self.toggle_overlay, width=84,
                                    height=28, font=self.f_body)
        self.btn_overlay.pack(side="left", padx=(14, 2))

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
        ckrow = ctk.CTkFrame(opt, fg_color="transparent")
        ckrow.pack(fill="x", padx=14, pady=4)
        ck_style = dict(onvalue=True, offvalue=False, font=self.f_body,
                        text_color=COL_TEXT, fg_color=COL_GOLD,
                        hover_color=COL_GOLD_HOVER, checkmark_color=COL_ON_GOLD,
                        border_color="#4A4A4A", checkbox_width=20,
                        checkbox_height=20, corner_radius=5)
        self.var_di = tk.BooleanVar(value=self.cfg["global"].get("use_directinput", True))
        ctk.CTkCheckBox(ckrow, text="使用 DirectInput（Windows 建議勾選）",
                        variable=self.var_di, **ck_style).pack(side="left")
        self.var_notify = tk.BooleanVar(value=self.cfg["global"].get("notify_events", True))
        ctk.CTkCheckBox(ckrow, text="開始／結束時發送系統通知",
                        variable=self.var_notify, **ck_style).pack(side="left", padx=(24, 0))
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
        if self.watch_on:
            self._stop_watch("切換角色，監看已停止")   # 監看/觸發設定隨角色走
        if self.chat_on:
            self._stop_chat("切換角色，聊天觸發已停止")
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

    # ---------- 技能監看 ----------

    def open_watch_dialog(self):
        was_on = self.watch_on
        if was_on:
            self._stop_watch("設定期間暫停監看")
        d = WatchDialog(self, self.prof().get("watch"))
        if d.result:
            self.prof()["watch"] = d.result
            self.log("監看設定已更新（記得按「儲存設定」）")
            if was_on or d.start_now:
                self.toggle_watch()
        elif was_on:
            self.toggle_watch()   # 取消設定 → 恢復原本的監看

    def toggle_watch(self):
        if self.watch_on:
            self._stop_watch("已停止監看")
            return
        w = self.prof().get("watch") or {}
        mode = w.get("mode") or ("icons" if w.get("icons") else "snapshot")
        if not w.get("region"):
            self.msg_info("技能監看", "還沒設定監看區域，先按「監看設定」。")
            return
        if mode == "icons":
            if not w.get("icons"):
                self.msg_info("技能監看", "圖示搜尋模式還沒上傳任何圖示。")
                return
        else:
            if not w.get("ref"):
                self.msg_info("技能監看",
                              "還沒設定基準圖。\n技能存在時拍攝，或上傳圖示檔。")
                return
            try:
                self.watch_ref = base64.b64decode(w["ref"])
            except Exception:
                self.msg_error("技能監看", "基準圖資料損壞，請重拍。")
                return
        self.watch_on = True
        self.watch_missing = {}
        self.watch_snooze = False
        self._watch_black_warned = False
        self._watch_icon_locs = {}
        self.btn_watch.configure(text="停止監看")
        if mode == "icons":
            self.log(f"技能監看開始：搜尋 {len(w['icons'])} 個圖示"
                     f"（門檻 {int(float(w.get('threshold', 0.8))*100)}%、"
                     f"每 {w.get('interval', 0.5)} 秒）")
            self.watch_thread = threading.Thread(target=self._watch_worker_icons,
                                                 daemon=True)
            self.watch_thread.start()
        else:
            self.log(f"技能監看開始（門檻 {int(float(w.get('threshold', 0.85))*100)}%、"
                     f"每 {w.get('interval', 0.5)} 秒檢查）")
            self._watch_tick()

    def _stop_watch(self, msg):
        self.watch_on = False
        self.watch_missing = {}
        self.watch_snooze = False
        self._watch_icon_locs = {}
        self._watch_found = (0, 0)
        if self.alarm is not None:
            self.alarm.close()
            self.alarm = None
        self.btn_watch.configure(text="開始監看")
        self.log(msg)

    def _watch_grab(self, w):
        """依設定擷取監看區域，回傳 (raw, gw, gh, 絕對區域) 或 None。"""
        kw = (w.get("window") or "").strip()
        rx, ry, rw, rh = w.get("region", [0, 0, 0, 0])
        if kw:
            rect = window_rect(kw)
            if rect is None:
                return None          # 目標視窗不在：不判定消失，等它回來
            ax, ay = rect[0] + rx, rect[1] + ry
        else:
            ax, ay = rx, ry
        raw, gw, gh = grab_region(ax, ay, rw, rh)
        return raw, gw, gh, (ax, ay, rw, rh)

    # ----- 單一區域比對模式（主執行緒輪詢） -----

    def _watch_tick(self):
        if self.watch_on and not self.stopping.is_set():
            w = self.prof().get("watch") or {}
            self._watch_check(w)
            self.root.after(int(float(w.get("interval", 0.5)) * 1000), self._watch_tick)

    def _watch_check(self, w):
        try:
            grabbed = self._watch_grab(w)
        except Exception as e:
            self._stop_watch(f"監看中止：畫面擷取失敗（{e}）")
            return
        if grabbed is None:
            return
        raw, gw, gh, _ = grabbed
        if not self._watch_black_warned and raw and raw.count(0) >= len(raw) * 0.97:
            self._watch_black_warned = True
            self.log("⚠ 擷取畫面幾乎全黑：macOS 請到 系統設定→隱私權與安全性→螢幕錄製 允許終端機")
        sim = grid_similarity(sample_grid(raw, gw, gh), self.watch_ref)
        self._watch_last_sim = sim
        found = sim >= float(w.get("threshold", 0.85))
        self._apply_watch_results({"技能": found},
                                  note=f"（相似度 {sim:.0%}）" if not found else "")

    # ----- 多圖示搜尋模式（背景執行緒） -----

    def _watch_worker_icons(self):
        import mss
        try:
            import numpy as np  # noqa: F401
            sct = getattr(mss, "MSS", mss.mss)()
        except Exception as e:
            self.msg_q.put(("log", f"圖示搜尋初始化失敗：{e}"))
            self.msg_q.put(("watch_stop", None))
            return
        w0 = self.prof().get("watch") or {}
        templates = []
        for ic in w0.get("icons", []):
            try:
                raw = zlib.decompress(base64.b64decode(ic["bgr"]))
                arr = (__import__("numpy").frombuffer(raw, dtype="uint8")
                       .reshape(ic["h"], ic["w"], 3).astype("int16"))
                templates.append({"name": ic.get("name", "圖示"), "arr": arr,
                                  "scale": None})
            except Exception:
                self.msg_q.put(("log", f"圖示「{ic.get('name')}」資料損壞，已略過"))
        if not templates:
            self.msg_q.put(("watch_stop", None))
            return
        warned_black = False
        while self.watch_on and not self.stopping.is_set():
            w = self.prof().get("watch") or {}
            iv = max(0.3, float(w.get("interval", 0.5)))
            thr = float(w.get("threshold", 0.8))
            try:
                kw = (w.get("window") or "").strip()
                rx, ry, rw, rh = w.get("region", [0, 0, 0, 0])
                if kw:
                    rect = window_rect(kw)
                    if rect is None:
                        time.sleep(iv)
                        continue
                    ax, ay = rect[0] + rx, rect[1] + ry
                else:
                    ax, ay = rx, ry
                img = sct.grab({"left": int(ax), "top": int(ay),
                                "width": int(rw), "height": int(rh)})
                raw = bytes(img.raw)
                region = _np_bgr(raw, img.width, img.height)
            except Exception as e:
                self.msg_q.put(("log", f"圖示搜尋擷取失敗：{e}"))
                time.sleep(iv)
                continue
            if not warned_black and raw.count(0) >= len(raw) * 0.97:
                warned_black = True
                self.msg_q.put(("log", "⚠ 擷取畫面幾乎全黑：請確認螢幕錄製權限"))
            ratio = img.width / max(1, rw)     # 實體像素/邏輯點（Retina=2）
            results, locs = {}, {}
            for t in templates:
                if t["scale"] is not None:
                    tm = _resize_nn(t["arr"], t["scale"])
                    sim, loc = icon_search(region, tm)
                    size = (tm.shape[1], tm.shape[0])
                    if sim < thr:   # 鎖定比例找不到 → 全比例重找一次
                        sim, loc, size, sc = icon_search_multiscale(region, t["arr"])
                        if sim >= thr:
                            t["scale"] = sc
                else:
                    sim, loc, size, sc = icon_search_multiscale(region, t["arr"])
                    if sim >= thr:
                        t["scale"] = sc
                found = sim >= thr
                results[t["name"]] = found
                if found and loc is not None:
                    locs[t["name"]] = (ax + loc[0] / ratio, ay + loc[1] / ratio,
                                       size[0] / ratio, size[1] / ratio)
            self.msg_q.put(("watch_icons", (results, locs)))
            time.sleep(iv)

    def _apply_watch_results(self, results, locs=None, note=""):
        """主執行緒：更新各目標的消失狀態、管理警報視窗。results = {名稱: 是否找到}"""
        now = time.monotonic()
        self._watch_icon_locs = locs or {}
        self._watch_found = (sum(1 for v in results.values() if v), len(results))
        for name, found in results.items():
            if found:
                if name in self.watch_missing:
                    gone = now - self.watch_missing.pop(name)
                    self.log(f"「{name}」已恢復（共消失 {gone:.0f} 秒）")
            else:
                if name not in self.watch_missing:
                    self.watch_missing[name] = now
                    self.log(f"⚠ 「{name}」消失！{note}")
        if self.watch_missing:
            if self.alarm is None and not self.watch_snooze:
                self.alarm = AlarmWindow(self)
        else:
            self.watch_snooze = False
            if self.alarm is not None:
                self.alarm.close()
                self.alarm = None

    # ---------- 聊天文字觸發 ----------

    def open_chat_dialog(self):
        was_on = self.chat_on
        if was_on:
            self._stop_chat("設定期間暫停聊天觸發")
        d = ChatDialog(self, self.prof().get("chat"))
        if d.result:
            self.prof()["chat"] = d.result
            self.log("聊天觸發設定已更新（記得按「儲存設定」）")
            if was_on or d.start_now:
                self.toggle_chat()
        elif was_on:
            self.toggle_chat()

    def toggle_chat(self):
        if self.chat_on:
            self._stop_chat("已停止聊天觸發")
            return
        c = self.prof().get("chat") or {}
        if not (c.get("region") and c.get("rules")):
            self.msg_info("聊天觸發",
                          "還沒設定辨識區域或規則。\n"
                          "先按「觸發設定」框選聊天視窗的區域，並新增觸發規則。")
            return
        if sys.platform != "darwin":
            self.msg_info("聊天觸發", "文字辨識目前僅支援 macOS（Windows 版待開發）。")
            return
        self.chat_on = True
        self._chat_present = {}
        self._chat_last = {}
        self.btn_chat.configure(text="停止觸發")
        self.log(f"聊天觸發開始（{len(c['rules'])} 條規則、每 {c.get('interval', 1.0)} 秒辨識）")
        self.chat_thread = threading.Thread(target=self._chat_worker, daemon=True)
        self.chat_thread.start()

    def _stop_chat(self, msg):
        self.chat_on = False
        self.btn_chat.configure(text="開始觸發")
        self.log(msg)

    def _chat_worker(self):
        """背景執行緒：定時擷取聊天區域＋OCR，辨識文字丟回主執行緒比對。"""
        import mss
        try:
            sct = getattr(mss, "MSS", mss.mss)()   # mss 不跨執行緒共用，這裡開自己的
        except Exception as e:
            self.msg_q.put(("log", f"聊天辨識初始化失敗：{e}"))
            self.msg_q.put(("chat_stop", None))
            return
        warned_black = False
        while self.chat_on and not self.stopping.is_set():
            c = self.prof().get("chat") or {}
            iv = max(0.5, float(c.get("interval", 1.0)))
            kw = (c.get("window") or "").strip()
            rx, ry, rw, rh = c.get("region", [0, 0, 0, 0])
            try:
                if kw:
                    rect = window_rect(kw)
                    if rect is None:
                        time.sleep(iv)
                        continue
                    ax, ay = rect[0] + rx, rect[1] + ry
                else:
                    ax, ay = rx, ry
                img = sct.grab({"left": int(ax), "top": int(ay),
                                "width": int(rw), "height": int(rh)})
                raw = bytes(img.raw)
                text = ocr_text(raw, img.width, img.height)
            except Exception as e:
                self.msg_q.put(("log", f"聊天辨識失敗：{e}"))
                time.sleep(iv)
                continue
            if text is None:
                self.msg_q.put(("log", "此平台不支援文字辨識"))
                self.msg_q.put(("chat_stop", None))
                return
            if not warned_black and raw and raw.count(0) >= len(raw) * 0.97:
                warned_black = True
                self.msg_q.put(("log", "⚠ 聊天區域擷取全黑：請確認螢幕錄製權限"))
            self.msg_q.put(("chat_text", text))
            time.sleep(iv)

    def _chat_match(self, text):
        """主執行緒：關鍵字「出現的瞬間」觸發（持續在畫面上不重複觸發），附冷卻。"""
        if not self.chat_on:
            return
        c = self.prof().get("chat") or {}
        now = time.monotonic()
        for rule in c.get("rules", []):
            kws = rule.get("text", "")
            if not kws:
                continue
            present = kws in text
            was = self._chat_present.get(kws, False)
            self._chat_present[kws] = present
            if not present or was:
                continue
            if now - self._chat_last.get(kws, -1e9) < float(rule.get("cooldown", 5.0)):
                continue
            self._chat_last[kws] = now
            if rule.get("combo"):
                combos = self.prof().get("combos", [])
                idx = next((i for i, cb in enumerate(combos)
                            if cb.get("name") == rule["combo"]), None)
                if idx is None:
                    self.log(f"聊天觸發：「{kws}」對應的組合「{rule['combo']}」不存在，已略過")
                    continue
                self.log(f"聊天觸發：「{kws}」→ 組合「{rule['combo']}」")
                self.trigger_combo(idx)
            elif rule.get("key"):
                self._ensure_backend()
                lo, hi = self.cfg["global"].get("hold_range", [0.04, 0.09])
                try:
                    self.backend.tap(rule["key"], random.uniform(lo, hi))
                    self.count += 1
                    self.log(f"聊天觸發：「{kws}」→ 按 {rule['key']}  (#{self.count})")
                except Exception as e:
                    self.log(f"聊天觸發按鍵失敗：{e}")

    # ---------- 監看範圍覆蓋層 ----------

    def _abs_region(self, cfg):
        """把「視窗相對區域」換算成螢幕絕對座標；視窗不在或未設定回傳 None。"""
        if not cfg or not cfg.get("region"):
            return None
        rx, ry, rw, rh = cfg["region"]
        kw = (cfg.get("window") or "").strip()
        if kw:
            rect = window_rect(kw)
            if rect is None:
                return None
            return rect[0] + rx, rect[1] + ry, rw, rh
        return rx, ry, rw, rh

    def toggle_overlay(self):
        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None
            self.btn_overlay.configure(text="顯示範圍")
            return
        self.overlay = OverlayWindow(self)
        self.btn_overlay.configure(text="隱藏範圍")
        self.log("監看範圍覆蓋層已開啟（透明、點擊穿透，不影響底下操作）")

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

    def notify_evt(self, msg):
        """開始／結束事件的系統通知（可在全域設定關閉）。"""
        if getattr(self, "var_notify", None) is not None and self.var_notify.get():
            notify("按鍵助手", msg)

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
        self.notify_evt(reason)

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
        self.notify_evt(f"輪替開始：{pname}")

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
        started_from_idle = not self.running.is_set()
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
        if started_from_idle:   # 插播不通知（打遊戲時太吵），單獨執行才通知
            self.notify_evt(f"組合開始：{c.get('name')}")

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

    def capture_coord_for(self, callback, message=None):
        """開啟座標擷取：使用者把游標移到目標位置按 F10，callback((x, y)) 收絕對座標。"""
        if self.coord_win is not None or self.capture_win is not None:
            return
        self.coord_cb = callback
        w = ctk.CTkToplevel(self.root, fg_color=COL_CARD)
        w.title("抓取座標")
        w.resizable(False, False)
        w.attributes("-topmost", True)   # 蓋在目標視窗上面也看得到說明
        apply_dark_titlebar(w)
        ctk.CTkLabel(w, text="抓取座標", font=self.f_title,
                     text_color=COL_GOLD).pack(padx=28, pady=(20, 6))
        ctk.CTkLabel(w, text=message or "切到目標視窗，把滑鼠移到要點擊的位置\n然後按 F10",
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
                                    self.msg_q.put(("notify", f"組合完成 {rounds} 輪，已自動停止"))
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
                self.msg_q.put(("notify", "發生錯誤，已暫停"))

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
                elif kind == "notify":
                    self.notify_evt(val)
                elif kind == "chat_text":
                    self._chat_last_text = val
                    self._chat_match(val)
                elif kind == "chat_stop":
                    self._stop_chat("聊天觸發已停止")
                elif kind == "watch_icons":
                    if self.watch_on:
                        self._apply_watch_results(val[0], val[1])
                elif kind == "watch_stop":
                    self._stop_watch("技能監看已停止")
        except queue.Empty:
            pass
        if not self.stopping.is_set():
            self.root.after(100, self.poll_queue)

    def on_close(self):
        self.notify_evt("程式已結束")
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


class AlarmWindow(ctk.CTkToplevel):
    """技能消失警報：最上層紅色視窗＋重複警示音＋消失秒數即時更新。"""

    def __init__(self, app):
        super().__init__(app.root, fg_color="#2A1412")
        self.app = app
        self._alive = True
        self.title("技能消失")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        apply_dark_titlebar(self)
        ctk.CTkLabel(self, text="⚠ 技能已消失", font=make_font(22, "bold"),
                     text_color=COL_DANGER_TEXT).pack(padx=48, pady=(26, 4))
        self.lbl_sec = ctk.CTkLabel(self, text="偵測中…", font=make_font(24, "bold"),
                                    text_color=COL_GOLD, justify="left")
        self.lbl_sec.pack(padx=48, pady=6)
        make_btn(self, "知道了", self._ack, kind="danger_solid",
                 width=120, height=36, font=make_font(14, "bold")).pack(pady=(10, 22))
        self.update_idletasks()
        # 螢幕右上角（技能列附近，最容易注意到）
        x = self.winfo_screenwidth() - self.winfo_reqwidth() - 40
        self.geometry(f"+{max(0, x)}+60")
        self.protocol("WM_DELETE_WINDOW", self._ack)
        self.lift()
        self._tick()
        self._beep()

    def _tick(self):
        if not self._alive:
            return
        missing = self.app.watch_missing
        if missing:
            now = time.monotonic()
            lines = [f"「{n}」已消失 {int(now - t)} 秒"
                     for n, t in sorted(missing.items(), key=lambda kv: kv[1])]
            self.lbl_sec.configure(text="\n".join(lines))
        self.after(250, self._tick)

    def _beep(self):
        if not self._alive:
            return
        play_alert()
        self.after(2000, self._beep)

    def _ack(self):
        """知道了：關掉這次警報，技能恢復前不再吵。"""
        self.app.watch_snooze = True
        if self.app.alarm is self:
            self.app.alarm = None
        self.close()

    def close(self):
        self._alive = False
        try:
            self.destroy()
        except Exception:
            pass


class WatchDialog(BaseModal):
    """技能監看設定：目標視窗、監看區域（F10×2 框選）、門檻/間隔、基準圖拍攝。"""

    def __init__(self, app, cfg=None):
        super().__init__(app.root, "技能監看設定")
        self.app = app
        self.result = None
        self.start_now = False
        c = cfg or {}
        self.ref_b64 = c.get("ref", "")
        self.icons = json.loads(json.dumps(c.get("icons", [])))
        self._corner1 = None
        f_body, f_bold = app.f_body, app.f_bold
        self.f_body = f_body

        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(fill="x", padx=20, pady=(18, 4))
        ctk.CTkLabel(r1, text="目標視窗含", font=f_bold,
                     text_color=COL_SUBTEXT).pack(side="left")
        self.var_window = tk.StringVar(value=c.get("window", ""))
        app._entry(r1, self.var_window, width=180).pack(side="left", padx=6)
        ctk.CTkLabel(r1, text="（留空 = 絕對座標）", font=f_body,
                     text_color=COL_SUBTEXT).pack(side="left")

        r2 = ctk.CTkFrame(self, fg_color="transparent")
        r2.pack(fill="x", padx=20, pady=4)
        rx, ry, rw, rh = c.get("region", ["", "", "", ""])
        self.var_x = tk.StringVar(value=str(rx))
        self.var_y = tk.StringVar(value=str(ry))
        self.var_w = tk.StringVar(value=str(rw))
        self.var_h = tk.StringVar(value=str(rh))
        for lbl, var in (("區域 X", self.var_x), ("Y", self.var_y),
                         ("寬", self.var_w), ("高", self.var_h)):
            ctk.CTkLabel(r2, text=lbl, font=f_bold,
                         text_color=COL_SUBTEXT).pack(side="left")
            app._entry(r2, var, width=60).pack(side="left", padx=(4, 10))
        make_btn(r2, "框選範圍（F10×2）", self._grab_corners, kind="primary",
                 width=140, height=28, font=f_body).pack(side="left")

        r3 = ctk.CTkFrame(self, fg_color="transparent")
        r3.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(r3, text="相似度低於", font=f_bold,
                     text_color=COL_SUBTEXT).pack(side="left")
        self.var_thr = tk.StringVar(value=str(int(float(c.get("threshold", 0.85)) * 100)))
        app._entry(r3, self.var_thr, width=56).pack(side="left", padx=4)
        ctk.CTkLabel(r3, text="% 視為消失　每", font=f_body,
                     text_color=COL_TEXT).pack(side="left")
        self.var_iv = tk.StringVar(value=str(c.get("interval", 0.5)))
        app._entry(r3, self.var_iv, width=56).pack(side="left", padx=4)
        ctk.CTkLabel(r3, text="秒檢查一次", font=f_body,
                     text_color=COL_TEXT).pack(side="left")

        # 基準方式切換：區域比對（拍攝單張）或 圖示搜尋（上傳多張、位置可移動）
        mrow = ctk.CTkFrame(self, fg_color="transparent")
        mrow.pack(fill="x", padx=20, pady=(6, 4))
        ctk.CTkLabel(mrow, text="基準方式", font=f_bold,
                     text_color=COL_SUBTEXT).pack(side="left")
        self.seg_mode = ctk.CTkSegmentedButton(
            mrow, values=["區域比對（拍攝）", "圖示搜尋（上傳多張）"],
            command=self._on_mode, font=f_body, height=28, corner_radius=8,
            fg_color=COL_FIELD, selected_color=COL_GOLD_DARK,
            selected_hover_color=COL_GOLD_DARK_HOVER,
            unselected_color="#2C2C2C", unselected_hover_color="#383838",
            text_color="#EDEAE0")
        self.seg_mode.pack(side="left", padx=8)

        # ── 區域比對模式的控制 ──
        self.snap_frame = ctk.CTkFrame(self, fg_color="transparent")
        make_btn(self.snap_frame, "拍攝基準圖（3 秒後）", self._shoot_ref, kind="primary",
                 width=160, height=28, font=f_body).pack(side="left")
        make_btn(self.snap_frame, "上傳圖示…", self._load_ref_file, width=96, height=28,
                 font=f_body).pack(side="left", padx=6)
        self.lbl_ref = ctk.CTkLabel(
            self.snap_frame, text="已有基準圖 ✓" if self.ref_b64 else "尚未設定基準圖",
            font=f_body,
            text_color=COL_GOLD if self.ref_b64 else COL_DANGER_TEXT)
        self.lbl_ref.pack(side="left", padx=10)

        # ── 圖示搜尋模式的控制 ──
        self.icons_frame = ctk.CTkFrame(self, fg_color="transparent")
        ibtns = ctk.CTkFrame(self.icons_frame, fg_color="transparent")
        ibtns.pack(side="right", fill="y", padx=(10, 0))
        iwrap = ctk.CTkFrame(self.icons_frame, fg_color=COL_TREE_BG, corner_radius=8)
        iwrap.pack(side="left", fill="both", expand=True)
        self.tree_i = ttk.Treeview(iwrap, style="Gold.Treeview", show="headings",
                                   selectmode="browse", height=4)
        self.tree_i.pack(side="left", fill="both", expand=True, padx=8, pady=6)
        self.tree_i.configure(columns=("name", "size"))
        for cc, h, w in (("name", "圖示名稱", 220), ("size", "尺寸", 90)):
            self.tree_i.heading(cc, text=h)
            self.tree_i.column(cc, width=w, anchor="center")
        make_btn(ibtns, "上傳圖示(可多選)", self._add_icons, kind="primary",
                 width=120, height=28, font=f_body).pack(pady=(6, 2))
        make_btn(ibtns, "移除", self._del_icon, kind="danger", width=120, height=28,
                 font=f_body).pack(pady=2)
        self._refresh_icons()

        self.lbl_hint = ctk.CTkLabel(
            self, text="", font=app.f_small, text_color=COL_SUBTEXT,
            wraplength=470, justify="left")
        self.lbl_hint.pack(anchor="w", padx=20, pady=(6, 0))
        init_mode = c.get("mode") or ("icons" if self.icons else "snapshot")
        self.seg_mode.set("圖示搜尋（上傳多張）" if init_mode == "icons"
                          else "區域比對（拍攝）")
        self._on_mode(self.seg_mode.get())

        brow = ctk.CTkFrame(self, fg_color="transparent")
        brow.pack(fill="x", padx=20, pady=(12, 16))
        make_btn(brow, "儲存並開始監看", self._save_start, kind="primary",
                 width=130).pack(side="right")
        make_btn(brow, "儲存", self._save, width=72).pack(side="right", padx=(0, 8))
        make_btn(brow, "取消", self.destroy, width=72).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())
        self.run_modal(app.root)

    # ----- 框選範圍：F10 兩次 -----

    def _grab_corners(self):
        self._corner1 = None
        self.app.capture_coord_for(
            self._on_corner1, message="框選範圍 1/2：\n滑鼠移到區域【左上角】按 F10")

    def _on_corner1(self, pos):
        self._corner1 = pos
        self.after(150, lambda: self.app.capture_coord_for(
            self._on_corner2, message="框選範圍 2/2：\n滑鼠移到區域【右下角】按 F10"))

    def _on_corner2(self, pos):
        c1 = self._corner1
        if c1 is None:
            return
        kw = self.var_window.get().strip()
        if not kw:
            kw = active_window_title()
            self.var_window.set(kw)
        rect = window_rect(kw)
        if rect:
            x1, y1 = c1[0] - rect[0], c1[1] - rect[1]
            x2, y2 = pos[0] - rect[0], pos[1] - rect[1]
        else:
            self.var_window.set("")
            x1, y1 = c1
            x2, y2 = pos
        self.var_x.set(str(min(x1, x2)))
        self.var_y.set(str(min(y1, y2)))
        self.var_w.set(str(max(8, abs(x2 - x1))))
        self.var_h.set(str(max(8, abs(y2 - y1))))
        self.ref_b64 = ""   # 區域變了，舊基準圖作廢
        self.lbl_ref.configure(text="區域已更新，請重拍基準圖", text_color=COL_DANGER_TEXT)

    # ----- 基準圖 -----

    def _region_abs(self):
        x = int(float(self.var_x.get()))
        y = int(float(self.var_y.get()))
        w = int(float(self.var_w.get()))
        h = int(float(self.var_h.get()))
        kw = self.var_window.get().strip()
        if kw:
            rect = window_rect(kw)
            if rect is None:
                raise ValueError(f"找不到視窗「{kw}」")
            return rect[0] + x, rect[1] + y, w, h
        return x, y, w, h

    def _shoot_ref(self, countdown=3):
        if countdown > 0:
            self.lbl_ref.configure(text=f"{countdown} 秒後拍攝，請確認技能圖示在畫面上…",
                                   text_color=COL_GOLD)
            self.after(1000, lambda: self._shoot_ref(countdown - 1))
            return
        try:
            ax, ay, w, h = self._region_abs()
            raw, gw, gh = grab_region(ax, ay, w, h)
        except Exception as e:
            self.lbl_ref.configure(text=f"拍攝失敗：{e}", text_color=COL_DANGER_TEXT)
            return
        self.ref_b64 = base64.b64encode(sample_grid(raw, gw, gh)).decode()
        if raw.count(0) >= len(raw) * 0.97:
            self.lbl_ref.configure(text="拍到全黑畫面：請確認螢幕錄製權限",
                                   text_color=COL_DANGER_TEXT)
        else:
            self.lbl_ref.configure(text="基準圖已拍攝 ✓", text_color=COL_GOLD)

    def _load_ref_file(self):
        path = filedialog.askopenfilename(
            parent=self, title="選擇技能圖示",
            filetypes=[("圖片（PNG/GIF）", "*.png *.gif"), ("所有檔案", "*.*")])
        try:
            self.grab_set()   # 系統檔案框會放掉 modal grab，拿回來
        except Exception:
            pass
        if not path:
            return
        try:
            photo = tk.PhotoImage(master=self, file=path)
            grid = photo_sample_grid(photo)
        except Exception as e:
            self.lbl_ref.configure(text=f"讀取失敗：{e}（僅支援 PNG/GIF）",
                                   text_color=COL_DANGER_TEXT)
            return
        self.ref_b64 = base64.b64encode(grid).decode()
        self.lbl_ref.configure(
            text=f"已載入圖示 ✓（{os.path.basename(path)}，{photo.width()}×{photo.height()}）",
            text_color=COL_GOLD)
        self.lbl_hint.configure(
            text="提醒：上傳的圖示和實際畫面可能有縮放/色差，若誤判請把「相似度低於」調低"
                 "（例如 70%），或改用「拍攝基準圖」以實際畫面為準。",
            text_color=COL_SUBTEXT)

    # ----- 模式切換與多圖示管理 -----

    def _on_mode(self, choice=None):
        icons_mode = "圖示搜尋" in (choice or self.seg_mode.get())
        self.snap_frame.pack_forget()
        self.icons_frame.pack_forget()
        if icons_mode:
            self.icons_frame.pack(fill="x", padx=20, pady=(2, 4), before=self.lbl_hint)
            self.lbl_hint.configure(
                text="圖示搜尋：框一整條技能／buff 區域（圖示位置會移動也沒關係），"
                     "上傳切好的圖示檔（PNG/GIF、可多張），程式在區域內搜尋每張圖示，"
                     "找不到就警報。門檻建議 75～85%。\n"
                     "macOS 首次使用需在 系統設定→隱私權與安全性→螢幕錄製 允許終端機。",
                text_color=COL_SUBTEXT)
        else:
            self.snap_frame.pack(fill="x", padx=20, pady=(2, 4), before=self.lbl_hint)
            self.lbl_hint.configure(
                text="區域比對：框選單一技能圖示的固定位置 → 技能存在時按「拍攝基準圖」"
                     "（3 秒內切回目標視窗），或上傳單張圖示檔 → 儲存並開始監看。\n"
                     "macOS 首次使用需在 系統設定→隱私權與安全性→螢幕錄製 允許終端機。",
                text_color=COL_SUBTEXT)

    def _refresh_icons(self):
        self.tree_i.delete(*self.tree_i.get_children())
        for ic in self.icons:
            self.tree_i.insert("", "end", values=(ic.get("name", "圖示"),
                                                  f"{ic.get('w')}×{ic.get('h')}"))

    def _add_icons(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="選擇技能圖示（可多選）",
            filetypes=[("圖片（PNG/GIF）", "*.png *.gif"), ("所有檔案", "*.*")])
        try:
            self.grab_set()
        except Exception:
            pass
        if not paths:
            return
        added, failed = 0, []
        for p in paths:
            try:
                photo = tk.PhotoImage(master=self, file=p)
                raw, w, h = photo_to_bgr(photo)
                name = os.path.splitext(os.path.basename(p))[0]
                base_name, i = name, 2
                while any(ic.get("name") == name for ic in self.icons):
                    name = f"{base_name} ({i})"
                    i += 1
                self.icons.append({"name": name, "w": w, "h": h,
                                   "bgr": base64.b64encode(zlib.compress(raw)).decode()})
                added += 1
            except Exception:
                failed.append(os.path.basename(p))
        self._refresh_icons()
        msg = f"已加入 {added} 張圖示，共 {len(self.icons)} 張"
        if failed:
            msg += f"；讀取失敗：{'、'.join(failed)}（僅支援 PNG/GIF）"
        self.lbl_hint.configure(text=msg,
                                text_color=COL_DANGER_TEXT if failed else COL_GOLD)

    def _del_icon(self):
        sel = self.tree_i.selection()
        if not sel:
            return
        del self.icons[self.tree_i.index(sel[0])]
        self._refresh_icons()

    # ----- 儲存 -----

    def _collect(self):
        try:
            region = [int(float(self.var_x.get())), int(float(self.var_y.get())),
                      int(float(self.var_w.get())), int(float(self.var_h.get()))]
            thr = max(0.3, min(0.99, float(self.var_thr.get() or 85) / 100.0))
            iv = max(0.2, float(self.var_iv.get() or 0.5))
        except ValueError:
            MsgBox(self, "設定有誤", "區域、門檻與間隔要是數字（區域可用「框選範圍」自動填）。",
                   kind="error")
            self.grab_set()
            return None
        out = {"window": self.var_window.get().strip(), "region": region,
               "threshold": thr, "interval": iv}
        if "圖示搜尋" in self.seg_mode.get():
            if not self.icons:
                MsgBox(self, "還差一步", "至少上傳一張切好的圖示（PNG/GIF）。")
                self.grab_set()
                return None
            out["mode"] = "icons"
            out["icons"] = self.icons
        else:
            if not self.ref_b64:
                MsgBox(self, "還差一步", "尚未設定基準圖：拍攝或上傳單張圖示。")
                self.grab_set()
                return None
            out["mode"] = "snapshot"
            out["ref"] = self.ref_b64
        return out

    def _save(self):
        out = self._collect()
        if out:
            self.result = out
            self.destroy()

    def _save_start(self):
        out = self._collect()
        if out:
            self.result = out
            self.start_now = True
            self.destroy()


class OverlayWindow(tk.Toplevel):
    """全螢幕透明覆蓋層：框出技能監看與聊天辨識的區域並顯示即時狀態。
    點擊穿透——完全不影響底下視窗的操作。"""

    WATCH_COLOR = COL_GOLD
    CHAT_COLOR = "#5FB0D0"

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self._alive = True
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")
        if sys.platform == "darwin":
            bg = "systemTransparent"
            try:
                self.attributes("-transparent", True)
                self.config(bg=bg)
            except Exception:
                bg = "#010101"
                self.attributes("-alpha", 0.35)
        elif sys.platform == "win32":
            bg = "#010101"
            self.config(bg=bg)
            try:
                self.attributes("-transparentcolor", bg)   # 該色像素透明且可點穿
            except Exception:
                self.attributes("-alpha", 0.35)
        else:
            bg = "#010101"
            self.attributes("-alpha", 0.35)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=bg)
        self.canvas.pack(fill="both", expand=True)
        self.update_idletasks()
        self._make_click_through()
        self._tick()

    def _make_click_through(self):
        """讓整個覆蓋層無視滑鼠事件（點擊直接落到底下的視窗）。"""
        self.click_through_ok = False
        try:
            if sys.platform == "darwin":
                # 從 NSApp 的視窗清單裡找覆蓋層（唯一的全螢幕無邊框視窗）
                from AppKit import NSApplication
                sw = self.winfo_screenwidth()
                sh = self.winfo_screenheight()
                for win in NSApplication.sharedApplication().windows():
                    fr = win.frame()
                    if int(fr.size.width) == sw and int(fr.size.height) >= sh - 1:
                        win.setIgnoresMouseEvents_(True)
                        win.setHidesOnDeactivate_(False)   # 切到別的 app 也不隱藏
                        win.setLevel_(25)                  # NSStatusWindowLevel，高於一般視窗
                        # 跨 Space＋固定不動＋全螢幕輔助（全螢幕遊戲上也顯示）
                        win.setCollectionBehavior_(1 | 16 | 256)
                        self.click_through_ok = True
            elif sys.platform == "win32":
                import ctypes
                GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
                self.click_through_ok = True
        except Exception:
            pass

    def _draw_region(self, box, color, label):
        x, y, w, h = box
        # 框線畫在區域「外側」3px，避免被監看擷取拍進去影響比對
        self.canvas.create_rectangle(x - 3, y - 3, x + w + 3, y + h + 3,
                                     outline=color, width=2)
        tx, ty = x - 3, max(2, y - 24)
        tid = self.canvas.create_text(tx + 6, ty + 9, text=label, anchor="w",
                                      fill="#181818", font=("", 12, "bold"))
        bbox = self.canvas.bbox(tid)
        if bbox:
            self.canvas.create_rectangle(bbox[0] - 6, bbox[1] - 3,
                                         bbox[2] + 6, bbox[3] + 3,
                                         fill=color, outline=color)
            self.canvas.tag_raise(tid)

    def _tick(self):
        if not self._alive:
            return
        app = self.app
        self.canvas.delete("all")
        prof = app.prof()
        box = app._abs_region(prof.get("watch"))
        if box:
            if app.watch_on:
                if app.watch_missing:
                    oldest = min(app.watch_missing.values())
                    names = "、".join(app.watch_missing)
                    st = f"⚠ {names} 消失 {int(time.monotonic() - oldest)} 秒"
                elif (prof.get("watch") or {}).get("icons"):
                    st = f"監看中 {app._watch_found[0]}/{app._watch_found[1]} 個圖示"
                else:
                    sim = app._watch_last_sim
                    st = f"監看中 {sim:.0%}" if sim is not None else "監看中"
            else:
                st = "未啟動"
            self._draw_region(box, self.WATCH_COLOR, f"技能監看　{st}")
            # 圖示搜尋模式：把每個找到的圖示位置也框出來
            for name, (ix, iy, iw, ih) in list(app._watch_icon_locs.items()):
                self.canvas.create_rectangle(ix, iy, ix + iw, iy + ih,
                                             outline=self.WATCH_COLOR, width=1)
                self.canvas.create_text(ix + 2, iy - 8, text=name, anchor="w",
                                        fill=self.WATCH_COLOR, font=("", 10))
        cbox = app._abs_region(prof.get("chat"))
        if cbox:
            if app.chat_on:
                t = app._chat_last_text.replace("\n", " ")
                st = "辨識中：" + (t[:24] + "…" if len(t) > 24 else (t or "（無文字）"))
            else:
                st = "未啟動"
            self._draw_region(cbox, self.CHAT_COLOR, f"聊天觸發　{st}")
        self.after(500, self._tick)

    def close(self):
        self._alive = False
        try:
            self.destroy()
        except Exception:
            pass


class ChatDialog(BaseModal):
    """聊天文字觸發設定：辨識區域（F10×2 框選）、辨識間隔、規則列表、測試辨識。"""

    def __init__(self, app, cfg=None):
        super().__init__(app.root, "聊天觸發設定")
        self.app = app
        self.result = None
        self.start_now = False
        c = cfg or {}
        self.rules = json.loads(json.dumps(c.get("rules", [])))
        self._corner1 = None
        f_body, f_bold = app.f_body, app.f_bold

        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(fill="x", padx=20, pady=(18, 4))
        ctk.CTkLabel(r1, text="目標視窗含", font=f_bold,
                     text_color=COL_SUBTEXT).pack(side="left")
        self.var_window = tk.StringVar(value=c.get("window", ""))
        app._entry(r1, self.var_window, width=170).pack(side="left", padx=6)
        ctk.CTkLabel(r1, text="（留空 = 絕對座標）", font=f_body,
                     text_color=COL_SUBTEXT).pack(side="left")

        r2 = ctk.CTkFrame(self, fg_color="transparent")
        r2.pack(fill="x", padx=20, pady=4)
        rx, ry, rw, rh = c.get("region", ["", "", "", ""])
        self.var_x = tk.StringVar(value=str(rx))
        self.var_y = tk.StringVar(value=str(ry))
        self.var_w = tk.StringVar(value=str(rw))
        self.var_h = tk.StringVar(value=str(rh))
        for lbl, var in (("區域 X", self.var_x), ("Y", self.var_y),
                         ("寬", self.var_w), ("高", self.var_h)):
            ctk.CTkLabel(r2, text=lbl, font=f_bold,
                         text_color=COL_SUBTEXT).pack(side="left")
            app._entry(r2, var, width=58).pack(side="left", padx=(4, 8))
        make_btn(r2, "框選範圍（F10×2）", self._grab_corners, kind="primary",
                 width=140, height=28, font=f_body).pack(side="left")

        r3 = ctk.CTkFrame(self, fg_color="transparent")
        r3.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(r3, text="每", font=f_bold, text_color=COL_SUBTEXT).pack(side="left")
        self.var_iv = tk.StringVar(value=str(c.get("interval", 1.0)))
        app._entry(r3, self.var_iv, width=56).pack(side="left", padx=4)
        ctk.CTkLabel(r3, text="秒辨識一次（文字辨識較耗時，建議 ≥ 1 秒）",
                     font=f_body, text_color=COL_TEXT).pack(side="left")
        make_btn(r3, "測試辨識", self._test_ocr, width=88, height=28,
                 font=f_body).pack(side="left", padx=12)

        # 規則列表
        ctk.CTkLabel(self, text="觸發規則（文字出現的瞬間觸發，持續顯示不重複）",
                     font=f_bold, text_color=COL_GOLD).pack(anchor="w", padx=20, pady=(8, 2))
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 6))
        rbtns = ctk.CTkFrame(body, fg_color="transparent")
        rbtns.pack(side="right", fill="y", padx=(10, 0))
        wrap = ctk.CTkFrame(body, fg_color=COL_TREE_BG, corner_radius=8)
        wrap.pack(side="left", fill="both", expand=True)
        self.tree_r = ttk.Treeview(wrap, style="Gold.Treeview", show="headings",
                                   selectmode="browse", height=6)
        rsb = ctk.CTkScrollbar(wrap, command=self.tree_r.yview, fg_color="transparent",
                               button_color="#3A3A3A", button_hover_color="#4E4E4E")
        rsb.pack(side="right", fill="y", padx=(0, 4), pady=8)
        self.tree_r.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self.tree_r.configure(yscrollcommand=rsb.set,
                              columns=("text", "action", "cd"))
        for cc, h, w in (("text", "觸發文字", 170), ("action", "動作", 150),
                         ("cd", "冷卻(秒)", 70)):
            self.tree_r.heading(cc, text=h)
            self.tree_r.column(cc, width=w, anchor="center")
        self._refresh_rules()
        self.tree_r.bind("<Double-1>", lambda e: self._edit_rule())
        make_btn(rbtns, "新增規則", self._add_rule, kind="primary",
                 width=88, height=28, font=f_body).pack(pady=(8, 2))
        make_btn(rbtns, "編輯", self._edit_rule, width=88, height=28,
                 font=f_body).pack(pady=2)
        make_btn(rbtns, "刪除", self._del_rule, kind="danger", width=88, height=28,
                 font=f_body).pack(pady=2)

        self.lbl_hint = ctk.CTkLabel(
            self, text="流程：框選聊天視窗的文字區域 → 按「測試辨識」確認讀得到 → 新增規則 → 儲存並開始。",
            font=app.f_small, text_color=COL_SUBTEXT, wraplength=500, justify="left")
        self.lbl_hint.pack(anchor="w", padx=20, pady=(4, 0))

        brow = ctk.CTkFrame(self, fg_color="transparent")
        brow.pack(fill="x", padx=20, pady=(10, 16))
        make_btn(brow, "儲存並開始", self._save_start, kind="primary",
                 width=110).pack(side="right")
        make_btn(brow, "儲存", self._save, width=72).pack(side="right", padx=(0, 8))
        make_btn(brow, "取消", self.destroy, width=72).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())
        self.run_modal(app.root)

    # ----- 區域框選（F10×2） -----

    def _grab_corners(self):
        self._corner1 = None
        self.app.capture_coord_for(
            self._on_corner1, message="框選範圍 1/2：\n滑鼠移到聊天區域【左上角】按 F10")

    def _on_corner1(self, pos):
        self._corner1 = pos
        self.after(150, lambda: self.app.capture_coord_for(
            self._on_corner2, message="框選範圍 2/2：\n滑鼠移到聊天區域【右下角】按 F10"))

    def _on_corner2(self, pos):
        c1 = self._corner1
        if c1 is None:
            return
        kw = self.var_window.get().strip()
        if not kw:
            kw = active_window_title()
            self.var_window.set(kw)
        rect = window_rect(kw)
        if rect:
            x1, y1 = c1[0] - rect[0], c1[1] - rect[1]
            x2, y2 = pos[0] - rect[0], pos[1] - rect[1]
        else:
            self.var_window.set("")
            x1, y1 = c1
            x2, y2 = pos
        self.var_x.set(str(min(x1, x2)))
        self.var_y.set(str(min(y1, y2)))
        self.var_w.set(str(max(16, abs(x2 - x1))))
        self.var_h.set(str(max(16, abs(y2 - y1))))
        self.lbl_hint.configure(text="區域已更新，按「測試辨識」確認讀得到文字。",
                                text_color=COL_GOLD)

    # ----- 測試辨識 -----

    def _region_abs(self):
        x = int(float(self.var_x.get()))
        y = int(float(self.var_y.get()))
        w = int(float(self.var_w.get()))
        h = int(float(self.var_h.get()))
        kw = self.var_window.get().strip()
        if kw:
            rect = window_rect(kw)
            if rect is None:
                raise ValueError(f"找不到視窗「{kw}」")
            return rect[0] + x, rect[1] + y, w, h
        return x, y, w, h

    def _test_ocr(self):
        try:
            ax, ay, w, h = self._region_abs()
        except Exception as e:
            self.lbl_hint.configure(text=f"測試失敗：{e}", text_color=COL_DANGER_TEXT)
            return
        self.lbl_hint.configure(text="辨識中…", text_color=COL_GOLD)

        def work():
            try:
                raw, gw, gh = grab_region(ax, ay, w, h)
                text = ocr_text(raw, gw, gh)
            except Exception as e:
                text = f"（擷取失敗：{e}）"
            self.app.msg_q.put(("log", "測試辨識完成"))
            self.after(0, lambda: self._show_test(text))
        threading.Thread(target=work, daemon=True).start()

    def _show_test(self, text):
        if text is None:
            shown = "此平台不支援文字辨識"
        elif not text:
            shown = "（沒讀到文字：確認區域、字體大小與螢幕錄製權限）"
        else:
            t = text.replace("\n", " ／ ")
            shown = ("辨識結果：" + (t[:80] + "…" if len(t) > 80 else t))
        self.lbl_hint.configure(text=shown, text_color=COL_TEXT)

    # ----- 規則 -----

    def _refresh_rules(self, keep=None):
        self.tree_r.delete(*self.tree_r.get_children())
        for r in self.rules:
            act = (f"組合「{r['combo']}」" if r.get("combo") else f"按 {r.get('key', '')}")
            self.tree_r.insert("", "end", values=(r.get("text", ""), act,
                                                  r.get("cooldown", 5.0)))
        kids = self.tree_r.get_children()
        if keep is not None and kids:
            self.tree_r.selection_set(kids[min(keep, len(kids) - 1)])

    def _sel_rule(self):
        sel = self.tree_r.selection()
        return self.tree_r.index(sel[0]) if sel else None

    def _add_rule(self):
        d = ChatRuleDialog(self, self.app, None)
        try:
            self.grab_set()
        except Exception:
            pass
        if d.result:
            self.rules.append(d.result)
            self._refresh_rules(keep=len(self.rules) - 1)

    def _edit_rule(self):
        i = self._sel_rule()
        if i is None:
            return
        d = ChatRuleDialog(self, self.app, self.rules[i])
        try:
            self.grab_set()
        except Exception:
            pass
        if d.result:
            self.rules[i] = d.result
            self._refresh_rules(keep=i)

    def _del_rule(self):
        i = self._sel_rule()
        if i is None:
            return
        del self.rules[i]
        self._refresh_rules(keep=i)

    # ----- 儲存 -----

    def _collect(self):
        try:
            region = [int(float(self.var_x.get())), int(float(self.var_y.get())),
                      int(float(self.var_w.get())), int(float(self.var_h.get()))]
            iv = max(0.5, float(self.var_iv.get() or 1.0))
        except ValueError:
            MsgBox(self, "設定有誤", "區域與間隔要是數字（區域可用「框選範圍」自動填）。",
                   kind="error")
            self.grab_set()
            return None
        if not self.rules:
            MsgBox(self, "還差一步", "至少新增一條觸發規則。")
            self.grab_set()
            return None
        return {"window": self.var_window.get().strip(), "region": region,
                "interval": iv, "rules": self.rules}

    def _save(self):
        out = self._collect()
        if out:
            self.result = out
            self.destroy()

    def _save_start(self):
        out = self._collect()
        if out:
            self.result = out
            self.start_now = True
            self.destroy()


class ChatRuleDialog(BaseModal):
    """單條觸發規則：觸發文字 → 按單鍵或觸發組合，附冷卻秒數。"""

    def __init__(self, parent, app, rule=None):
        super().__init__(parent, "編輯規則" if rule else "新增規則")
        self.app = app
        self.result = None
        r = rule or {}
        f_body, f_bold = app.f_body, app.f_bold

        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(fill="x", padx=20, pady=(18, 4))
        ctk.CTkLabel(r1, text="觸發文字", font=f_bold,
                     text_color=COL_SUBTEXT).pack(side="left")
        self.var_text = tk.StringVar(value=r.get("text", ""))
        app._entry(r1, self.var_text, width=200).pack(side="left", padx=6)
        ctk.CTkLabel(r1, text="（比對「包含」即可）", font=f_body,
                     text_color=COL_SUBTEXT).pack(side="left")

        r2 = ctk.CTkFrame(self, fg_color="transparent")
        r2.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(r2, text="動作", font=f_bold,
                     text_color=COL_SUBTEXT).pack(side="left")
        self.seg_act = ctk.CTkSegmentedButton(
            r2, values=["按單鍵", "觸發組合"], font=f_body, height=28,
            corner_radius=8, fg_color=COL_FIELD, selected_color=COL_GOLD_DARK,
            selected_hover_color=COL_GOLD_DARK_HOVER,
            unselected_color="#2C2C2C", unselected_hover_color="#383838",
            text_color="#EDEAE0")
        self.seg_act.set("觸發組合" if r.get("combo") else "按單鍵")
        self.seg_act.pack(side="left", padx=(8, 14))
        ctk.CTkLabel(r2, text="按鍵", font=f_body, text_color=COL_TEXT).pack(side="left")
        self.var_key = tk.StringVar(value=r.get("key", ""))
        app._entry(r2, self.var_key, width=70).pack(side="left", padx=(4, 12))
        ctk.CTkLabel(r2, text="組合", font=f_body, text_color=COL_TEXT).pack(side="left")
        combo_names = [c.get("name", "") for c in app.prof().get("combos", [])]
        self.cmb_combo = ctk.CTkComboBox(
            r2, width=140, height=28, state="readonly",
            values=combo_names or ["（無組合）"],
            font=f_body, dropdown_font=f_body,
            fg_color=COL_FIELD, border_color=COL_BORDER,
            button_color="#303030", button_hover_color="#3C3C3C",
            dropdown_fg_color="#232323", dropdown_hover_color="#333333",
            dropdown_text_color=COL_TEXT, text_color=COL_TEXT)
        self.cmb_combo.set(r.get("combo") or (combo_names[0] if combo_names else "（無組合）"))
        self.cmb_combo.pack(side="left", padx=4)

        r3 = ctk.CTkFrame(self, fg_color="transparent")
        r3.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(r3, text="冷卻", font=f_bold,
                     text_color=COL_SUBTEXT).pack(side="left")
        self.var_cd = tk.StringVar(value=str(r.get("cooldown", 5.0)))
        app._entry(r3, self.var_cd, width=56).pack(side="left", padx=6)
        ctk.CTkLabel(r3, text="秒（觸發後這段時間內不再重複觸發）", font=f_body,
                     text_color=COL_TEXT).pack(side="left")

        brow = ctk.CTkFrame(self, fg_color="transparent")
        brow.pack(fill="x", padx=20, pady=(12, 16))
        make_btn(brow, "儲存", self._save, kind="primary", width=88).pack(side="right")
        make_btn(brow, "取消", self.destroy, width=88).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())
        self.run_modal(parent)

    def _save(self):
        text = self.var_text.get().strip()
        if not text:
            MsgBox(self, "少了觸發文字", "填入要監看的聊天文字（比對「包含」）。")
            self.grab_set()
            return
        try:
            cd = max(0.0, float(self.var_cd.get() or 5.0))
        except ValueError:
            MsgBox(self, "設定有誤", "冷卻秒數要是數字。", kind="error")
            self.grab_set()
            return
        out = {"text": text, "cooldown": cd}
        if self.seg_act.get() == "觸發組合":
            name = self.cmb_combo.get()
            if not name or name == "（無組合）":
                MsgBox(self, "設定有誤", "這個角色還沒有組合可以觸發，先建組合或改用「按單鍵」。",
                       kind="error")
                self.grab_set()
                return
            out["combo"] = name
        else:
            key = self.var_key.get().strip()
            if not key:
                MsgBox(self, "設定有誤", "填入要按的按鍵（如 f、1、space、右鍵）。",
                       kind="error")
                self.grab_set()
                return
            out["key"] = key
        self.result = out
        self.destroy()


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    root = ctk.CTk(fg_color=COL_BG)
    apply_dark_titlebar(root)
    App(root)
    root.mainloop()
