import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

def enum_windows():
    windows = []
    def callback(hwnd, extra):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            
            cls_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls_buff, 256)
            cls_name = cls_buff.value
            
            windows.append((hwnd, title, cls_name))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return windows

print("=== Visible Windows ===")
wins = enum_windows()
for hwnd, title, cls in wins:
    print(f"HWND: {hex(hwnd)} | Title: '{title}' | Class: '{cls}'")
    # If it's a dialog (#32770) or has title like "Open an Account" or "Trading Platform"
    if cls == "#32770" or "Open an Account" in title or "Registration" in title:
        print(f"--> Sending WM_CLOSE to {hex(hwnd)} ('{title}')")
        user32.PostMessageW(hwnd, 0x0010, 0, 0) # WM_CLOSE

print("=== Finished scanning windows ===")
