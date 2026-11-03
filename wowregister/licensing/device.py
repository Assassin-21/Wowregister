"""Windows installation identity and user-scoped DPAPI storage."""
import ctypes
from ctypes import wintypes as W
import hashlib
import os
import uuid


def fingerprint(machine_guid):
    normalized = str(uuid.UUID(machine_guid.strip().strip("{}")))
    return hashlib.sha256(("wowregister-device-v1:" + normalized).encode("ascii")).hexdigest()


def device_id():
    if os.name != "nt":
        raise RuntimeError("机器码仅支持 Windows")
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        return fingerprint(guid)
    except (OSError, ValueError) as exc:
        raise RuntimeError("无法读取 Windows 机器标识，授权已停止") from exc


class Blob(ctypes.Structure):
    _fields_ = [("size", W.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    if os.name != "nt":
        raise RuntimeError("卡密本地加密仅支持 Windows DPAPI")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    source_buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, result = Blob(len(data), source_buffer), Blob()
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, W.DWORD, ctypes.POINTER(Blob)]
    function.restype = W.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise RuntimeError("卡密加密数据无法处理；请在原 Windows 账号使用或重新激活")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))
