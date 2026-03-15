import subprocess
import webbrowser
import os
import shutil
import urllib.parse
import asyncio
import difflib
import pyautogui
import pyperclip
import psutil
import time
import ctypes
import re
import socket
import warnings
import numpy as np

from datetime import datetime
from pathlib import Path
from ..memory import MemoryService, MemoryServiceError

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

# Suppress repeated third-party warnings that do not affect behavior in this app.
warnings.filterwarnings(
    "ignore",
    message=r".*pin_memory.*no accelerator is found.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"Revert to STA COM threading mode",
    category=UserWarning,
)

def get_tools():
    tools = [{"function_declarations": [
        {"name": "open_application", "description": "Open any application on the computer by name", "parameters": {"type": "object", "properties": {"app_name": {"type": "string", "description": "App to open: chrome, firefox, notepad, calculator, terminal, powershell, explorer, vscode, spotify, discord, slack, word, excel, paint, task_manager"}}, "required": ["app_name"]}},
        {"name": "close_application", "description": "Close/kill a running application by name", "parameters": {"type": "object", "properties": {"app_name": {"type": "string", "description": "Process name to kill e.g. chrome, notepad, spotify"}}, "required": ["app_name"]}},
        {"name": "list_running_apps", "description": "List all currently running applications", "parameters": {"type": "object", "properties": {}}},
        {"name": "list_open_windows", "description": "List visible top-level window titles", "parameters": {"type": "object", "properties": {}}},
        {"name": "window_focus", "description": "Bring an OS window to focus by its title. Use browser_switch_tab instead for switching browser tabs.", "parameters": {"type": "object", "properties": {"title": {"type": "string", "description": "Partial window title to search for"}}, "required": ["title"]}},
        {"name": "ui_click", "description": "Click a UI element by text. Requires pywinauto OR Chrome CDP at 127.0.0.1:9222. If unavailable, this tool will fail fast.", "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "Visible label/text of the target UI element"}, "window_title": {"type": "string", "description": "Optional target window title hint"}, "control_type": {"type": "string", "description": "Optional UIA control type e.g. Button, Hyperlink, MenuItem"}, "x": {"type": "integer", "description": "Optional coordinate fallback x"}, "y": {"type": "integer", "description": "Optional coordinate fallback y"}}, "required": ["text"]}},
        {"name": "window_minimize", "description": "Minimize the current active window", "parameters": {"type": "object", "properties": {}}},
        {"name": "window_maximize", "description": "Maximize the current active window", "parameters": {"type": "object", "properties": {}}},
        {"name": "window_close", "description": "Close the current active window with Alt+F4", "parameters": {"type": "object", "properties": {}}},
        {"name": "switch_window", "description": "Switch between open OS windows using Alt+Tab", "parameters": {"type": "object", "properties": {"times": {"type": "integer", "description": "How many times to tab (default 1)"}}}},
        {"name": "mouse_click", "description": "Raw coordinate click only. Executes click at x,y but cannot verify target identity.", "parameters": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "description": "left, right, or middle (default: left)"}, "double": {"type": "boolean", "description": "Double click if true"}}, "required": ["x", "y"]}},
        {"name": "mouse_move", "description": "Move mouse to coordinates without clicking", "parameters": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}},
        {"name": "mouse_scroll", "description": "Scroll up or down on the page. Clicks center of screen first to ensure focus. Use amount 30+ for large jumps.", "parameters": {"type": "object", "properties": {"direction": {"type": "string", "description": "up or down"}, "amount": {"type": "integer", "description": "Scroll clicks (default 10). Use 30+ for large page jumps."}}, "required": ["direction"]}},
        {"name": "mouse_drag", "description": "Click and drag from one position to another", "parameters": {"type": "object", "properties": {"x1": {"type": "integer"}, "y1": {"type": "integer"}, "x2": {"type": "integer"}, "y2": {"type": "integer"}}, "required": ["x1", "y1", "x2", "y2"]}},
        {"name": "type_text", "description": "Type text at the current cursor position", "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "press_enter": {"type": "boolean", "description": "Press Enter after typing (default false)"}}, "required": ["text"]}},
        {"name": "key_press", "description": "Press a single key: enter, escape, tab, space, backspace, delete, up, down, left, right, home, end, pageup, pagedown, f1-f12", "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}},
        {"name": "hotkey", "description": "Press a keyboard shortcut e.g. ctrl+c, ctrl+v, alt+f4, ctrl+shift+t, win+d", "parameters": {"type": "object", "properties": {"keys": {"type": "string", "description": "Keys separated by + e.g. ctrl+c"}}, "required": ["keys"]}},
        {"name": "browser_navigate", "description": "Navigate the CURRENT tab to a NEW URL. IMPORTANT: Only use for opening new URLs. To switch between existing tabs use browser_switch_tab. Do NOT use this to switch to an already open tab.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
        {"name": "browser_search", "description": "Search Google, YouTube, or any site", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "site": {"type": "string", "description": "google (default), youtube, github, reddit, amazon, wikipedia"}}, "required": ["query"]}},
        {"name": "browser_switch_tab", "description": "Switch to an existing browser tab by position. Use this when asked to click on a tab or switch to a tab. Tab 1=first from left, 2=second, etc.", "parameters": {"type": "object", "properties": {"position": {"type": "integer", "description": "Tab position from left: 1=first, 2=second, max 8"}}, "required": ["position"]}},
        {"name": "browser_tab_bar_click", "description": "Click directly on a tab in the tab bar by position. Fallback if browser_switch_tab does not work.", "parameters": {"type": "object", "properties": {"position": {"type": "integer", "description": "Tab number from left starting at 1"}}, "required": ["position"]}},
        {"name": "browser_new_tab", "description": "Open a new empty browser tab", "parameters": {"type": "object", "properties": {}}},
        {"name": "browser_close_tab", "description": "Close the currently active browser tab", "parameters": {"type": "object", "properties": {}}},
        {"name": "browser_close_tab_by_position", "description": "Switch to a tab by position then close it", "parameters": {"type": "object", "properties": {"position": {"type": "integer", "description": "Tab position from left to close"}}, "required": ["position"]}},
        {"name": "browser_back", "description": "Go back in browser history", "parameters": {"type": "object", "properties": {}}},
        {"name": "browser_forward", "description": "Go forward in browser history", "parameters": {"type": "object", "properties": {}}},
        {"name": "browser_refresh", "description": "Refresh the current browser page", "parameters": {"type": "object", "properties": {}}},
        {"name": "browser_zoom", "description": "Zoom browser in, out, or reset", "parameters": {"type": "object", "properties": {"direction": {"type": "string", "description": "in, out, or reset"}}, "required": ["direction"]}},
        {"name": "clipboard_copy", "description": "Copy selected text (Ctrl+C)", "parameters": {"type": "object", "properties": {}}},
        {"name": "clipboard_paste", "description": "Paste clipboard content (Ctrl+V)", "parameters": {"type": "object", "properties": {}}},
        {"name": "clipboard_set", "description": "Set clipboard to specific text", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
        {"name": "clipboard_get", "description": "Read current clipboard content", "parameters": {"type": "object", "properties": {}}},
        {"name": "memory_save", "description": "Save a grounded memory for later recall. Use when the user says remember this, save this, bookmark this, or keep this for later.", "parameters": {"type": "object", "properties": {"title": {"type": "string", "description": "Short memory title"}, "summary": {"type": "string", "description": "Compact grounded summary of what should be remembered"}, "content": {"type": "string", "description": "Optional longer content, notes, quote, or details"}, "source": {"type": "string", "description": "Where this came from, e.g. browser, meeting, screen, voice"}, "url": {"type": "string", "description": "Optional source URL"}, "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"}}, "required": ["summary"]}},
        {"name": "memory_search", "description": "Search saved memories by meaning, topic, person, source, or time hint before answering from memory.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "What to look up from saved memory"}, "limit": {"type": "integer", "description": "Max results to return, default 5"}}, "required": ["query"]}},
        {"name": "memory_recent", "description": "List the most recent saved memories.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "description": "Max results to return, default 5"}}}},
        {"name": "memory_delete", "description": "Delete a saved memory by id when the user explicitly asks to forget or remove it.", "parameters": {"type": "object", "properties": {"memory_id": {"type": "string", "description": "The id of the saved memory to delete"}}, "required": ["memory_id"]}},
        {"name": "open_folder", "description": "Open a folder in File Explorer. Shortcuts: desktop, downloads, documents, pictures, music, videos", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "file_create", "description": "Create a new file with optional content", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path"]}},
        {"name": "file_read", "description": "Read a text file content", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "file_delete", "description": "Delete a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "file_copy", "description": "Copy a file from src to dst", "parameters": {"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"]}},
        {"name": "list_files", "description": "List files in a directory", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "volume_set", "description": "Set system volume 0-100", "parameters": {"type": "object", "properties": {"level": {"type": "integer", "description": "Volume 0-100"}}, "required": ["level"]}},
        {"name": "volume_mute", "description": "Mute or unmute system volume", "parameters": {"type": "object", "properties": {}}},
        {"name": "system_sleep", "description": "Put the computer to sleep", "parameters": {"type": "object", "properties": {}}},
        {"name": "system_shutdown", "description": "Shutdown the computer", "parameters": {"type": "object", "properties": {"delay_seconds": {"type": "integer", "description": "Delay before shutdown (default 0)"}}}},
        {"name": "system_restart", "description": "Restart the computer", "parameters": {"type": "object", "properties": {}}},
        {"name": "lock_screen", "description": "Lock the computer screen", "parameters": {"type": "object", "properties": {}}},
        {"name": "show_desktop", "description": "Minimize all windows and show desktop", "parameters": {"type": "object", "properties": {}}},
        {"name": "scroll_to", "description": "Instantly jump to the very top or bottom of the current page. More reliable than mouse_scroll for full-page jumps.", "parameters": {"type": "object", "properties": {"position": {"type": "string", "description": "top or bottom"}}, "required": ["position"]}},
        {"name": "scroll_continuous", "description": "Scroll continuously until told to stop. Use when user says 'keep scrolling', 'scroll until I say stop', 'infinitely scroll'.", "parameters": {"type": "object", "properties": {"direction": {"type": "string", "description": "up or down"}, "speed": {"type": "string", "description": "slow, medium (default), fast"}}, "required": ["direction"]}},
        {"name": "get_time", "description": "Get current time and date", "parameters": {"type": "object", "properties": {}}},
        {"name": "get_system_info", "description": "Get CPU, RAM, disk usage and battery status", "parameters": {"type": "object", "properties": {}}},
        {"name": "run_command", "description": "Run a shell command and return output", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "wait", "description": "Wait for a page or action to complete before checking screen", "parameters": {"type": "object", "properties": {"seconds": {"type": "number", "description": "Seconds to wait (default 1.5)"}}}},    ]}]
    if not (_has_pywinauto() or _has_cdp_9222() or _has_easyocr()):
        tools[0]["function_declarations"] = [
            d for d in tools[0]["function_declarations"] if d.get("name") != "ui_click"
        ]
    return tools


FOLDER_SHORTCUTS = {
    "desktop":   os.path.join(os.path.expanduser("~"), "Desktop"),
    "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),
    "documents": os.path.join(os.path.expanduser("~"), "Documents"),
    "pictures":  os.path.join(os.path.expanduser("~"), "Pictures"),
    "music":     os.path.join(os.path.expanduser("~"), "Music"),
    "videos":    os.path.join(os.path.expanduser("~"), "Videos"),
}

SEARCH_URLS = {
    "google":    "https://www.google.com/search?q={}",
    "youtube":   "https://www.youtube.com/results?search_query={}",
    "github":    "https://github.com/search?q={}",
    "reddit":    "https://www.reddit.com/search/?q={}",
    "amazon":    "https://www.amazon.com/s?k={}",
    "wikipedia": "https://en.wikipedia.org/wiki/Special:Search?search={}",
}

APP_MAP = {
    "chrome": "chrome", "google chrome": "chrome", "firefox": "firefox",
    "edge": "msedge", "notepad": "notepad", "calculator": "calc",
    "terminal": "cmd", "cmd": "cmd", "powershell": "powershell",
    "explorer": "explorer", "file explorer": "explorer",
    "vscode": "code", "visual studio code": "code",
    "spotify": "spotify", "discord": "discord", "slack": "slack",
    "word": "winword", "excel": "excel", "paint": "mspaint",
    "task manager": "taskmgr", "control panel": "control",
    "settings": "ms-settings:", "snipping tool": "snippingtool",
    "teams": "teams", "zoom": "zoom",
}



# Win32 helpers for reliable window management
def _window_title(hwnd):
    user32 = ctypes.windll.user32
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value.strip()

def _foreground_hwnd():
    return int(ctypes.windll.user32.GetForegroundWindow() or 0)

def _foreground_title():
    return _window_title(_foreground_hwnd())

def _enum_windows():
    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    windows = []

    def _callback(hwnd, _lparam):
        try:
            hwnd = int(hwnd)
            if not user32.IsWindowVisible(hwnd):
                return True
            title = _window_title(hwnd)
            if title:
                windows.append((hwnd, title))
            return True
        except Exception:
            return True

    user32.EnumWindows(enum_proc(_callback), 0)
    return windows

def _find_windows(query):
    q = (query or "").strip().lower()
    if not q:
        return []
    matches = []
    for hwnd, title in _enum_windows():
        if q in title.lower():
            matches.append((hwnd, title))
    return matches

def _activate_window(hwnd):
    user32 = ctypes.windll.user32
    SW_RESTORE = 9
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002
    hwnd = int(hwnd)
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.08)
    return _foreground_hwnd() == hwnd

def _launch_command(cmd):
    if not cmd:
        return False
    try:
        if os.path.isabs(cmd):
            if not os.path.exists(cmd):
                return False
            subprocess.Popen([cmd], shell=False)
            return True

        resolved = shutil.which(cmd)
        if not resolved:
            return False
        subprocess.Popen([resolved], shell=False)
        return True
    except Exception:
        return False


_UIA_AVAILABLE = None
_CDP_9222_AVAILABLE = None


def _has_pywinauto():
    global _UIA_AVAILABLE
    if _UIA_AVAILABLE is not None:
        return _UIA_AVAILABLE
    try:
        import pywinauto  # noqa: F401
        _UIA_AVAILABLE = True
    except Exception:
        _UIA_AVAILABLE = False
    return _UIA_AVAILABLE


def _has_cdp_9222():
    global _CDP_9222_AVAILABLE
    if _CDP_9222_AVAILABLE is not None:
        return _CDP_9222_AVAILABLE
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=0.15):
            pass
        _CDP_9222_AVAILABLE = True
    except Exception:
        _CDP_9222_AVAILABLE = False
    return _CDP_9222_AVAILABLE


_EASYOCR_AVAILABLE = None
_OCR_READER = None
_OCR_CLICK_CACHE = {}
_OCR_CACHE_TTL_SEC = 20.0
_MEMORY_SERVICE = None
_MEMORY_SERVICE_ERROR = None
try:
    import torch as _torch
    _EASYOCR_USE_GPU = bool(_torch.cuda.is_available())
except (ImportError, RuntimeError, OSError):
    _EASYOCR_USE_GPU = False


def _has_easyocr():
    global _EASYOCR_AVAILABLE
    if _EASYOCR_AVAILABLE is not None:
        return _EASYOCR_AVAILABLE
    try:
        import easyocr  # noqa: F401
        _EASYOCR_AVAILABLE = True
    except Exception:
        _EASYOCR_AVAILABLE = False
    return _EASYOCR_AVAILABLE


def _get_memory_service():
    global _MEMORY_SERVICE, _MEMORY_SERVICE_ERROR
    if _MEMORY_SERVICE is not None:
        return _MEMORY_SERVICE, None
    if _MEMORY_SERVICE_ERROR is not None:
        return None, _MEMORY_SERVICE_ERROR
    try:
        _MEMORY_SERVICE = MemoryService.from_env()
        return _MEMORY_SERVICE, None
    except Exception as e:
        _MEMORY_SERVICE_ERROR = str(e)
        return None, _MEMORY_SERVICE_ERROR


def _get_easyocr_reader():
    global _OCR_READER
    if _OCR_READER is not None:
        return _OCR_READER, None
    if not _has_easyocr():
        return None, "easyocr unavailable"
    try:
        import easyocr
        allow_download = os.getenv("JAVPI_OCR_AUTO_DOWNLOAD", "0").strip().lower() in ("1", "true", "yes", "on")
        try:
            _OCR_READER = easyocr.Reader(["en"], gpu=_EASYOCR_USE_GPU, verbose=False, download_enabled=allow_download)
        except TypeError:
            _OCR_READER = easyocr.Reader(["en"], gpu=_EASYOCR_USE_GPU, download_enabled=allow_download)
        return _OCR_READER, None
    except Exception as e:
        hint = ""
        if "download" in str(e).lower() or "model" in str(e).lower():
            hint = " (set JAVPI_OCR_AUTO_DOWNLOAD=1 once to fetch models)"
        return None, f"easyocr init failed: {e}{hint}"




def _is_probably_browser_context(window_title=None):
    title = (window_title or _foreground_title() or "").lower()
    return any(k in title for k in ("chrome", "firefox", "edge", "brave", "opera", "safari"))


def _ocr_cache_key(text):
    ctx = (_foreground_title() or "").lower()
    return f"{ctx}|{_normalize_ui_text(text)}"
def _normalize_ui_text(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _ui_text_score(query, candidate):
    q = _normalize_ui_text(query)
    c = _normalize_ui_text(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.9
    q_tokens = set(q.split())
    c_tokens = set(c.split())
    overlap = 0.0
    if q_tokens:
        overlap = len(q_tokens & c_tokens) / len(q_tokens)
    seq = difflib.SequenceMatcher(None, q, c).ratio()
    return max(seq, (0.55 * overlap) + (0.45 * seq))


def _try_ocr_click(text):
    q = (text or "").strip()
    if not q:
        return False, "text is required"

    reader, err = _get_easyocr_reader()
    if not reader:
        return False, (err or "easyocr unavailable")

    try:
        frame = np.array(pyautogui.screenshot())
    except Exception as e:
        return False, f"ocr screenshot failed: {e}"

    def _pick_best(results):
        best_local = None
        best_score_local = 0.0
        for item in results:
            try:
                bbox, label, conf = item
                score = _ui_text_score(q, label)
                if float(conf) < 0.15 and score < 0.9:
                    continue
                if score > best_score_local:
                    best_score_local = score
                    best_local = (bbox, label, float(conf), score)
            except Exception:
                continue
        return best_local, best_score_local

    key = _ocr_cache_key(q)
    now = time.monotonic()
    cached = _OCR_CLICK_CACHE.get(key)

    if cached and (now - float(cached.get("ts", 0.0))) <= _OCR_CACHE_TTL_SEC:
        h, w = frame.shape[:2]
        cx, cy = int(cached.get("x", 0)), int(cached.get("y", 0))
        half_w, half_h = 260, 180
        left = max(0, cx - half_w)
        top = max(0, cy - half_h)
        right = min(w, cx + half_w)
        bottom = min(h, cy + half_h)

        if (right - left) >= 64 and (bottom - top) >= 64:
            roi = frame[top:bottom, left:right]
            try:
                roi_results = reader.readtext(roi, detail=1, paragraph=False)
                best, best_score = _pick_best(roi_results)
                if best and best_score >= 0.60:
                    bbox, label, conf, score = best
                    xs = [float(p[0]) for p in bbox]
                    ys = [float(p[1]) for p in bbox]
                    x = int(sum(xs) / max(1, len(xs))) + left
                    y = int(sum(ys) / max(1, len(ys))) + top
                    pyautogui.moveTo(x, y, duration=0.08)
                    pyautogui.click(x, y)
                    _OCR_CLICK_CACHE[key] = {"x": x, "y": y, "ts": time.monotonic()}
                    return True, f"ocr cached-roi match: '{label}' score={score:.2f} conf={conf:.2f} at ({x},{y})"
            except Exception:
                pass

    try:
        results = reader.readtext(frame, detail=1, paragraph=False)
    except Exception as e:
        return False, f"ocr read failed: {e}"

    best, best_score = _pick_best(results)
    if not best or best_score < 0.62:
        return False, "ocr target not found"

    bbox, label, conf, score = best
    xs = [float(p[0]) for p in bbox]
    ys = [float(p[1]) for p in bbox]
    x = int(sum(xs) / max(1, len(xs)))
    y = int(sum(ys) / max(1, len(ys)))

    pyautogui.moveTo(x, y, duration=0.08)
    pyautogui.click(x, y)
    _OCR_CLICK_CACHE[key] = {"x": x, "y": y, "ts": time.monotonic()}
    return True, f"ocr match: '{label}' score={score:.2f} conf={conf:.2f} at ({x},{y})"

def _try_uia_click(text, window_title=None, control_type=None):
    q = (text or "").strip()
    if not q:
        return False, "text is required"
    if not _has_pywinauto():
        return False, "pywinauto unavailable"
    try:
        from pywinauto import Desktop
    except Exception as e:
        return False, f"pywinauto unavailable: {e}"

    try:
        desktop = Desktop(backend="uia")
        if window_title:
            win = desktop.window(title_re=f".*{re.escape(window_title)}.*")
        else:
            win = desktop.active_window()

        try:
            win.set_focus()
        except Exception:
            pass

        kwargs = {"title_re": f".*{re.escape(q)}.*"}
        if control_type:
            kwargs["control_type"] = control_type

        try:
            target = win.child_window(**kwargs).wrapper_object()
            target.click_input()
            return True, "uia direct match"
        except Exception:
            pass

        deadline = time.monotonic() + 1.2
        for ctrl in win.descendants():
            if time.monotonic() > deadline:
                return False, "uia scan timeout"
            try:
                name = (ctrl.window_text() or "").strip()
                if name and q.lower() in name.lower():
                    ctrl.click_input()
                    return True, f"uia descendant match: {name}"
            except Exception:
                continue

        return False, "uia target not found"
    except Exception as e:
        return False, f"uia click failed: {e}"

async def _try_dom_click(text):
    q = (text or "").strip()
    if not q:
        return False, "text is required"
    if not _has_cdp_9222():
        return False, "cdp unavailable at 127.0.0.1:9222"
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        return False, f"playwright unavailable: {e}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            pages = []
            for ctx in browser.contexts:
                pages.extend(ctx.pages)
            if not pages:
                return False, "no browser pages available"

            page = None
            for cand in reversed(pages):
                url = (cand.url or "").lower()
                if url and not url.startswith("about:blank"):
                    page = cand
                    break
            if page is None:
                page = pages[-1]

            try:
                await page.get_by_role("button", name=q, exact=False).first.click(timeout=900)
                return True, "dom role button"
            except Exception:
                pass

            try:
                await page.get_by_role("link", name=q, exact=False).first.click(timeout=900)
                return True, "dom role link"
            except Exception:
                pass

            await page.get_by_text(q, exact=False).first.click(timeout=1200)
            return True, "dom text"
    except Exception as e:
        return False, f"dom click failed: {e}"

def _focus_content_area():
    """Click center of screen to ensure content has keyboard+scroll focus."""
    w, h = pyautogui.size()
    pyautogui.click(w // 2, h // 2)
    time.sleep(0.1)


async def execute_tool(function_call):
    name = function_call.name
    args = dict(function_call.args) if function_call.args else {}
    
    try:
        if name == "open_application":
            app = args.get("app_name", "").strip().lower()
            if not app:
                return {"status": "error", "message": "app_name is required"}

            cmd = APP_MAP.get(app, app)
            focus_terms = [app, cmd]
            if app == "google chrome":
                focus_terms.append("chrome")

            for term in focus_terms:
                matches = _find_windows(term)
                if matches:
                    hwnd, title = matches[0]
                    if _activate_window(hwnd):
                        return {"status": "success", "message": f"Focused existing window: {title}"}

            launch_candidates = []
            if cmd.startswith("ms-"):
                launch_candidates.append(cmd)
            else:
                which_cmd = shutil.which(cmd)
                if which_cmd:
                    launch_candidates.append(which_cmd)
                launch_candidates.append(cmd)
                if app in ("chrome", "google chrome"):
                    launch_candidates.extend([
                        r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                        r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
                    ])
                elif app == "edge":
                    launch_candidates.extend([
                        r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
                        r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
                    ])
                elif app == "firefox":
                    launch_candidates.extend([
                        r"C:\\Program Files\\Mozilla Firefox\\firefox.exe",
                        r"C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe",
                    ])

            seen = set()
            for candidate in launch_candidates:
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                if candidate.startswith("ms-"):
                    try:
                        os.startfile(candidate)
                        return {"status": "success", "message": f"Opened {app}"}
                    except Exception:
                        continue
                if _launch_command(candidate):
                    return {"status": "success", "message": f"Opened {app}"}

            return {"status": "error", "message": f"Could not open or focus {app}"}

        elif name == "close_application":
            app = args.get("app_name", "").lower()
            proc_map = {
                "chrome": "chrome.exe", "firefox": "firefox.exe", "edge": "msedge.exe",
                "notepad": "notepad.exe", "spotify": "spotify.exe",
                "discord": "discord.exe", "code": "code.exe", "vscode": "code.exe",
            }
            proc = proc_map.get(app, f"{app}.exe")
            subprocess.run(f"taskkill /f /im {proc}", shell=True, capture_output=True)
            return {"status": "success", "message": f"Closed {app}"}
        elif name == "wait":
            await asyncio.sleep(float(args.get("seconds", 1.5)))
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}
        
        elif name == "list_running_apps":
            procs = set()
            for p in psutil.process_iter(['name']):
                try:
                    n = p.info['name']
                    if n and not n.startswith(('svchost', 'System', 'Registry')):
                        procs.add(n)
                except Exception:
                    pass
            return {"apps": sorted(procs)}

        elif name == "list_open_windows":
            windows = [title for _, title in _enum_windows()]
            return {"status": "success", "windows": windows}

        elif name == "window_focus":
            title = args.get("title", "").strip()
            if not title:
                return {"status": "error", "message": "title is required"}

            matches = _find_windows(title)
            if not matches:
                return {"status": "error", "message": f"No window found: {title}"}

            # Prefer tighter matches first for better focus targeting.
            matches.sort(key=lambda it: (0 if it[1].lower() == title.lower() else 1, len(it[1])))
            hwnd, matched_title = matches[0]
            if _activate_window(hwnd):
                return {"status": "success", "message": f"Focused: {matched_title}"}

            return {
                "status": "error",
                "message": f"Focus failed for: {matched_title}",
                "foreground": _foreground_title(),
            }

        elif name == "window_minimize":
            hwnd = _foreground_hwnd()
            if not hwnd:
                return {"status": "error", "message": "No active window to minimize"}
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "window_maximize":
            hwnd = _foreground_hwnd()
            if not hwnd:
                return {"status": "error", "message": "No active window to maximize"}
            ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "window_close":
            hwnd = _foreground_hwnd()
            if not hwnd:
                return {"status": "error", "message": "No active window to close"}
            WM_CLOSE = 0x0010
            ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "switch_window":
            times = max(1, int(args.get("times", 1)))
            before = _foreground_title()
            pyautogui.keyDown("alt")
            for _ in range(times):
                pyautogui.press("tab")
                time.sleep(0.12)
            pyautogui.keyUp("alt")
            time.sleep(0.12)
            after = _foreground_title()
            return {"status": "success", "from": before, "to": after}
        elif name == "ui_click":
            text = args.get("text", "")
            window_title = args.get("window_title")
            control_type = args.get("control_type")

            has_uia = _has_pywinauto()
            has_cdp = _has_cdp_9222()
            has_ocr = _has_easyocr()

            if (not has_uia) and (not has_cdp) and (not has_ocr) and not ("x" in args and "y" in args):
                return {
                    "status": "error",
                    "message": "ui_click unavailable: install pywinauto or easyocr, or launch Chrome with --remote-debugging-port=9222"
                }

            browser_ctx = _is_probably_browser_context(window_title)
            detail = "uia skipped"
            dom_detail = "dom skipped"
            ocr_detail = "ocr skipped"

            if browser_ctx:
                if has_cdp:
                    ok, dom_detail = await _try_dom_click(text)
                    if ok:
                        return {"status": "success", "method": "dom", "message": dom_detail}
                if has_ocr:
                    ok, ocr_detail = _try_ocr_click(text)
                    if ok:
                        return {"status": "success", "method": "ocr", "message": ocr_detail, "target_verified": True, "requires_visual_confirmation": True}
                if has_uia:
                    ok, detail = _try_uia_click(text=text, window_title=window_title, control_type=control_type)
                    if ok:
                        return {"status": "success", "method": "uia", "message": detail}
            else:
                if has_uia:
                    ok, detail = _try_uia_click(text=text, window_title=window_title, control_type=control_type)
                    if ok:
                        return {"status": "success", "method": "uia", "message": detail}
                if has_cdp:
                    ok, dom_detail = await _try_dom_click(text)
                    if ok:
                        return {"status": "success", "method": "dom", "message": dom_detail}
                if has_ocr:
                    ok, ocr_detail = _try_ocr_click(text)
                    if ok:
                        return {"status": "success", "method": "ocr", "message": ocr_detail, "target_verified": True, "requires_visual_confirmation": True}

            if "x" in args and "y" in args:
                x, y = int(args["x"]), int(args["y"])
                pyautogui.click(x, y)
                return {"status": "success", "method": "coords", "message": f"Fallback click at ({x},{y})", "target_verified": False, "requires_visual_confirmation": True}

            return {
                "status": "error",
                "message": "ui_click failed",
                "uia": detail,
                "dom": dom_detail,
                "ocr": ocr_detail,
            }
        elif name == "mouse_click":
            x, y = int(args["x"]), int(args["y"])
            button = args.get("button", "left")
            if args.get("double", False):
                pyautogui.doubleClick(x, y, button=button)
            else:
                pyautogui.click(x, y, button=button)
            return {"status": "success", "message": f"Clicked ({x},{y})", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "mouse_move":
            pyautogui.moveTo(int(args["x"]), int(args["y"]), duration=0.2)
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}
        elif name == "mouse_scroll":
            direction = args.get("direction", "down")
            amount = int(args.get("amount", 120))
            amount = max(1, min(amount, 2000))
            _focus_content_area()
            pyautogui.scroll(amount if direction == "up" else -amount)
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "mouse_drag":
            x1, y1 = int(args["x1"]), int(args["y1"])
            x2, y2 = int(args["x2"]), int(args["y2"])
            pyautogui.moveTo(x1, y1, duration=0.08)
            pyautogui.dragTo(x2, y2, duration=0.25, button="left")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}
        elif name == "type_text":
            pyautogui.write(args.get("text", ""), interval=0.03)
            if args.get("press_enter", False):
                pyautogui.press("enter")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "key_press":
            pyautogui.press(args.get("key", ""))
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "hotkey":
            keys = [k.strip() for k in args.get("keys", "").split("+")]
            pyautogui.hotkey(*keys)
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "browser_navigate":
            url = args.get("url", "")
            if not url.startswith("http"):
                url = "https://" + url
            webbrowser.open(url)
            return {"status": "success", "message": f"Navigated to {url}", "requires_visual_confirmation": True}

        elif name == "browser_search":
            query = args.get("query", "")
            site = args.get("site", "google").lower()
            template = SEARCH_URLS.get(site, SEARCH_URLS["google"])
            webbrowser.open(template.format(urllib.parse.quote(query)))
            return {"status": "success", "message": f"Searched {site} for: {query}", "requires_visual_confirmation": True}

        elif name == "browser_switch_tab":
            pos = max(1, min(int(args.get("position", 1)), 8))
            pyautogui.hotkey("ctrl", str(pos))
            time.sleep(0.2)
            return {"status": "success", "message": f"Switched to tab {pos}", "requires_visual_confirmation": True}

        elif name == "browser_tab_bar_click":
            pos = int(args.get("position", 1))
            x = 50 + (pos - 1) * 200 + 100
            pyautogui.click(x, 35)
            time.sleep(0.2)
            return {"status": "success", "message": f"Clicked tab {pos}", "requires_visual_confirmation": True}

        elif name == "browser_new_tab":
            pyautogui.hotkey("ctrl", "t")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "browser_close_tab":
            pyautogui.hotkey("ctrl", "w")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "browser_close_tab_by_position":
            pos = max(1, min(int(args.get("position", 1)), 8))
            pyautogui.hotkey("ctrl", str(pos))
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "w")
            return {"status": "success", "message": f"Closed tab {pos}"}

        elif name == "browser_back":
            pyautogui.hotkey("alt", "left")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "browser_forward":
            pyautogui.hotkey("alt", "right")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "browser_refresh":
            pyautogui.hotkey("ctrl", "r")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "browser_zoom":
            d = args.get("direction", "in")
            pyautogui.hotkey("ctrl", "+" if d == "in" else "-" if d == "out" else "0")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "clipboard_copy":
            pyautogui.hotkey("ctrl", "c")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "clipboard_paste":
            pyautogui.hotkey("ctrl", "v")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "clipboard_set":
            pyperclip.copy(args.get("text", ""))
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "clipboard_get":
            return {"status": "success", "content": pyperclip.paste()}

        elif name == "memory_save":
            service, err = _get_memory_service()
            if not service:
                return {"status": "error", "message": f"memory unavailable: {err}"}

            def _save_memory():
                return service.save(
                    title=args.get("title", ""),
                    summary=args.get("summary", ""),
                    content=args.get("content", ""),
                    source=args.get("source", "agent"),
                    url=args.get("url", ""),
                    tags=args.get("tags", []),
                )

            try:
                record = await asyncio.get_running_loop().run_in_executor(None, _save_memory)
            except MemoryServiceError as e:
                return {"status": "error", "message": str(e)}

            return {
                "status": "success",
                "memory": {
                    "id": record.memory_id,
                    "title": record.title,
                    "summary": record.summary,
                    "source": record.source,
                    "url": record.url,
                    "tags": list(record.tags),
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                },
                "message": f"Saved memory '{record.title}'",
            }

        elif name == "memory_search":
            service, err = _get_memory_service()
            if not service:
                return {"status": "error", "message": f"memory unavailable: {err}"}

            def _search_memories():
                return service.search(
                    query=args.get("query", ""),
                    limit=int(args.get("limit", 5)),
                )

            try:
                hits = await asyncio.get_running_loop().run_in_executor(None, _search_memories)
            except MemoryServiceError as e:
                return {"status": "error", "message": str(e)}

            return {
                "status": "success",
                "query": args.get("query", ""),
                "results": [hit.to_dict() for hit in hits],
                "count": len(hits),
                "message": f"Found {len(hits)} memory result(s)",
            }

        elif name == "memory_recent":
            service, err = _get_memory_service()
            if not service:
                return {"status": "error", "message": f"memory unavailable: {err}"}

            def _recent_memories():
                return service.recent(limit=int(args.get("limit", 5)))

            hits = await asyncio.get_running_loop().run_in_executor(None, _recent_memories)
            return {
                "status": "success",
                "results": [hit.to_dict() for hit in hits],
                "count": len(hits),
                "message": f"Loaded {len(hits)} recent memory item(s)",
            }

        elif name == "memory_delete":
            service, err = _get_memory_service()
            if not service:
                return {"status": "error", "message": f"memory unavailable: {err}"}

            def _delete_memory():
                return service.delete(args.get("memory_id", ""))

            try:
                deleted = await asyncio.get_running_loop().run_in_executor(None, _delete_memory)
            except MemoryServiceError as e:
                return {"status": "error", "message": str(e)}

            if not deleted:
                return {"status": "error", "message": "Memory not found"}
            return {"status": "success", "message": "Memory deleted"}

        elif name == "open_folder":
            path = args.get("path", "")
            resolved = FOLDER_SHORTCUTS.get(path.lower(), path)
            subprocess.Popen(f'explorer "{resolved}"', shell=True)
            return {"status": "success", "message": f"Opened {resolved}"}

        elif name == "file_create":
            path = args.get("path", "")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(args.get("content", ""))
            return {"status": "success", "message": f"Created {path}"}

        elif name == "file_read":
            with open(args.get("path", ""), "r", encoding="utf-8") as f:
                return {"status": "success", "content": f.read(4000)}

        elif name == "file_delete":
            os.remove(args.get("path", ""))
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "file_copy":
            shutil.copy2(args["src"], args["dst"])
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "list_files":
            path = args.get("path", "")
            resolved = FOLDER_SHORTCUTS.get(path.lower(), path)
            return {"status": "success", "files": os.listdir(resolved)[:50], "path": resolved}

        elif name == "volume_set":
            level = max(0, min(100, int(args.get("level", 50))))
            r = subprocess.run(f'nircmd setsysvolume {int(level * 655.35)}',
                               shell=True, capture_output=True)
            if r.returncode != 0:
                subprocess.run(
                    f'powershell -c "$s = New-Object -ComObject WScript.Shell; '
                    f'1..50 | % {{ $s.SendKeys([char]174) }}; '
                    f'1..{level // 2} | % {{ $s.SendKeys([char]175) }}"',
                    shell=True, capture_output=True)
            return {"status": "success", "message": f"Volume set to {level}%"}

        elif name == "volume_mute":
            pyautogui.press("volumemute")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "system_sleep":
            subprocess.run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "system_shutdown":
            delay = int(args.get("delay_seconds", 0))
            subprocess.run(f"shutdown /s /t {delay}", shell=True)
            return {"status": "success", "message": f"Shutting down in {delay}s"}

        elif name == "system_restart":
            subprocess.run("shutdown /r /t 0", shell=True)
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "lock_screen":
            subprocess.run("rundll32.exe user32.dll,LockWorkStation", shell=True)
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "show_desktop":
            pyautogui.hotkey("win", "d")
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}

        elif name == "scroll_to":
            _focus_content_area()
            key = "home" if args.get("position") == "top" else "end"
            pyautogui.hotkey("ctrl", key)
            return {"status": "success", "target_verified": False, "requires_visual_confirmation": True}
        elif name == "scroll_continuous":
            direction = args.get("direction", "down")
            speed_name = args.get("speed", "medium")
            # Keep each call short to avoid session keepalive timeouts.
            # Agent can call this repeatedly for longer scrolling.
            scroll_profiles = {
                "slow": {"delta": 90, "interval": 0.08, "duration": 1.2},
                "medium": {"delta": 140, "interval": 0.05, "duration": 1.4},
                "fast": {"delta": 220, "interval": 0.03, "duration": 1.6},
            }
            profile = scroll_profiles.get(speed_name, scroll_profiles["medium"])
            _focus_content_area()
            end_time = time.monotonic() + profile["duration"]
            steps = 0
            delta = profile["delta"] if direction == "up" else -profile["delta"]
            while time.monotonic() < end_time:
                pyautogui.scroll(delta)
                steps += 1
                await asyncio.sleep(profile["interval"])
            return {
                "status": "success",
                "direction": direction,
                "speed": speed_name,
                "steps": steps,
            }

        elif name == "get_time":
            now = datetime.now()
            return {"time": now.strftime("%I:%M %p"), "date": now.strftime("%B %d, %Y"), "day": now.strftime("%A")}

        elif name == "get_system_info":
            info = {
                "cpu_percent": psutil.cpu_percent(interval=0.5),
                "ram_percent": psutil.virtual_memory().percent,
                "ram_used_gb": round(psutil.virtual_memory().used / 1e9, 1),
                "ram_total_gb": round(psutil.virtual_memory().total / 1e9, 1),
            }
            try:
                info["disk_percent"] = psutil.disk_usage("C:\\").percent
            except Exception:
                pass
            try:
                b = psutil.sensors_battery()
                if b:
                    info["battery_percent"] = b.percent
                    info["plugged_in"] = b.power_plugged
            except Exception:
                pass
            return info

        elif name == "run_command":
            r = subprocess.run(args.get("command", ""), shell=True,
                               capture_output=True, text=True, timeout=10)
            return {"stdout": r.stdout[:2000], "stderr": r.stderr[:500], "returncode": r.returncode}

        else:
            return {"status": "error", "message": f"Unknown tool: {name}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}

