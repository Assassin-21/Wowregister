"""Windows desktop adapter. Win32 APIs are initialized only by the CLI."""
import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import time

from PIL import ImageGrab


class PlaybackStopped(RuntimeError):
    pass


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("data", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("extra", ctypes.c_size_t)]


class KeyInput(ctypes.Structure):
    _fields_ = [("vk", W.WORD), ("scan", W.WORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("extra", ctypes.c_size_t)]


class InputUnion(ctypes.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyInput)]


class Input(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", W.DWORD), ("value", InputUnion)]


class Desktop:
    def __init__(self, stop_event=None, report=print, license_guard=None):
        self.stop_event, self.report = stop_event, report
        self.license_guard = license_guard
        if os.name != "nt":
            raise RuntimeError("录制和真实回放仅支持 Windows")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        self.user.GetForegroundWindow.restype = W.HWND
        self.user.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
        self.user.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
        self.user.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
        self.user.GetDpiForWindow.argtypes = [W.HWND]
        self.user.GetDpiForWindow.restype = W.UINT
        self.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user.GetAsyncKeyState.restype = W.SHORT
        self.user.SendInput.argtypes = [W.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user.SendInput.restype = W.UINT
        self.kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.kernel.OpenProcess.restype = W.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        self.hwnd = None

    def down(self, key):
        return bool(self.user.GetAsyncKeyState(key) & 0x8000)

    def geometry(self):
        rect, origin = W.RECT(), W.POINT()
        if not self.user.GetClientRect(self.hwnd, ctypes.byref(rect)) or not self.user.ClientToScreen(self.hwnd, ctypes.byref(origin)):
            raise RuntimeError("无法读取目标窗口")
        return origin.x, origin.y, rect.right, rect.bottom

    def bind(self, macro=None, allow_game_path_change=False):
        self.hwnd = self.user.GetForegroundWindow()
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            raise RuntimeError("请切到注册页面后再按 F6")
        handle = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not handle:
            raise RuntimeError("无法读取目标程序路径")
        try:
            buffer, size = ctypes.create_unicode_buffer(32768), W.DWORD(32768)
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                raise RuntimeError("无法读取目标程序路径")
            self.executable = buffer.value
        finally:
            self.kernel.CloseHandle(handle)
        if Path(self.executable).name.lower() in {
            "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe", "windowsterminal.exe",
            "openconsole.exe", "python.exe", "pythonw.exe", "py.exe",
        }:
            raise RuntimeError("当前是终端或 Python 窗口；请切到注册页面后再按 F6")
        self.initial_geometry = self.geometry()
        self.dpi = self.user.GetDpiForWindow(self.hwnd)
        if min(self.initial_geometry[2:]) <= 0:
            raise RuntimeError("目标窗口不可用")
        same_program = not macro or os.path.normcase(self.executable) == os.path.normcase(macro["executable"])
        if macro and allow_game_path_change:
            same_program = Path(self.executable).name.lower() == Path(macro["executable"]).name.lower() == "wow.exe"
        if macro and (not same_program
                      or list(self.initial_geometry[2:]) != macro["client_size"]
                      or self.dpi != macro.get("dpi", self.dpi)):
            raise RuntimeError("目标程序、窗口尺寸或 DPI 与录制不同，请恢复布局或重新录制")
        self.report(f"已绑定：{Path(self.executable).name}，客户区 {self.initial_geometry[2:]}，DPI {self.dpi}")

    def check_cancelled(self):
        if getattr(self, "stop_event", None) is not None and self.stop_event.is_set():
            raise PlaybackStopped("已按停止按钮，操作已停止")
        if getattr(self, "license_guard", None):
            self.license_guard()

    def guard(self):
        self.check_cancelled()
        if self.down(0x79):
            raise PlaybackStopped("已按 F10 停止")
        if self.user.GetForegroundWindow() != self.hwnd:
            raise RuntimeError("目标窗口失去焦点，已停止")
        if self.geometry() != self.initial_geometry or self.user.GetDpiForWindow(self.hwnd) != self.dpi:
            raise RuntimeError("目标窗口移动、缩放或尺寸改变，已停止")

    @staticmethod
    def now():
        return time.monotonic()

    def wait(self, seconds):
        end = self.now() + seconds
        while True:
            self.guard()
            remaining = end - self.now()
            if remaining <= 0:
                return
            time.sleep(min(.02, remaining))

    def position(self):
        point = W.POINT()
        if not self.user.GetCursorPos(ctypes.byref(point)):
            raise RuntimeError("无法读取鼠标位置")
        ox, oy, width, height = self.geometry()
        x, y = point.x - ox, point.y - oy
        if not (0 <= x < width and 0 <= y < height):
            raise RuntimeError("鼠标超出目标窗口客户区，已停止")
        return x, y

    def capture(self, box):
        self.guard()
        ox, oy, _, _ = self.geometry()
        x1, y1, x2, y2 = box
        with ImageGrab.grab(bbox=(ox + x1, oy + y1, ox + x2, oy + y2), all_screens=True) as image:
            return image.convert("RGB")

    def send(self, event):
        if self.user.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
            raise RuntimeError("Windows 拒绝了模拟输入；请检查目标程序与脚本的权限级别")

    def key(self, vk=0, scan=0, flags=0):
        self.send(Input(type=1, ki=KeyInput(vk=vk, scan=scan, flags=flags)))

    def move_to(self, x, y):
        """Smooth eased cursor movement; checks cancellation throughout."""
        sx, sy = self.position()
        ox, oy, _, _ = self.geometry()
        distance = ((x-sx)**2 + (y-sy)**2)**.5
        duration = min(.8, max(.18, distance / 1800))
        steps = max(2, int(duration / .015))
        for i in range(1, steps + 1):
            self.guard()
            t = i / steps
            t = t*t*(3-2*t)
            if not self.user.SetCursorPos(ox + round(sx+(x-sx)*t), oy + round(sy+(y-sy)*t)):
                raise RuntimeError("无法移动鼠标")
            self.wait(duration / steps)

    def click(self, action):
        self.guard()
        self.ensure_modifiers_released()
        self.move_to(action["x"], action["y"])
        self.guard()
        down, up = (2, 4) if action["button"] == "left" else (8, 16)
        try:
            self.send(Input(type=0, mi=MouseInput(flags=down)))
            self.wait(max(.04, action["hold"]))
        finally:
            self.send(Input(type=0, mi=MouseInput(flags=up)))

    def ensure_modifiers_released(self):
        if any(self.down(vk) for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C, 1, 2)):
            raise RuntimeError("请松开 Shift/Ctrl/Alt/Win 和鼠标按钮后再运行")

    def press_enter(self):
        self.guard()
        self.ensure_modifiers_released()
        try:
            self.key(0x0D)
            self.wait(.05)
        finally:
            self.key(0x0D, flags=2)

    def type_name(self, name):
        self.guard()
        self.ensure_modifiers_released()
        # Explicit text action only; no raw keyboard recording or clipboard use.
        try:
            self.key(0x11)
            self.key(0x41)
        finally:
            try:
                self.key(0x41, flags=2)
            finally:
                self.key(0x11, flags=2)
        self.wait(.08)
        self.guard()
        try:
            self.key(0x08)
        finally:
            self.key(0x08, flags=2)
        for character in name:
            self.guard()
            encoded = character.encode("utf-16-le")
            for offset in range(0, len(encoded), 2):
                unit = int.from_bytes(encoded[offset:offset + 2], "little")
                try:
                    self.key(scan=unit, flags=4)
                finally:
                    self.key(scan=unit, flags=6)
            self.wait(.03)


def wait_for_start(desktop, report=print):
    report("切回游戏角色列表，松开其他按键，再按 F6 开始。F10 取消。")
    previous = desktop.down(0x75)
    while True:
        desktop.check_cancelled()
        if desktop.down(0x79):
            raise PlaybackStopped("已按 F10 取消")
        current = desktop.down(0x75)
        if current and not previous:
            return
        previous = current
        time.sleep(.01)
