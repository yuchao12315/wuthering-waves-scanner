"""
鼠标和键盘输入控制 — 使用 PostMessage 直接向游戏窗口发送消息
参考 ok-ww (ok-script) 的 PostMessageInteraction 实现

PostMessage 直接将消息投递到目标窗口的消息队列，
不受 UIPI 权限隔离限制（不需要管理员权限），
也不受 DirectX 全屏独占模式影响。
"""
import time
import ctypes

try:
    import win32api
    import win32con
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

_hwnd = None


def init(hwnd):
    """初始化，传入游戏窗口句柄。"""
    global _hwnd
    _hwnd = hwnd


def ensure_admin():
    """PostMessage方案不强制需要管理员权限，直接返回True。"""
    if not HAS_WIN32:
        print("✗ 缺少 pywin32 模块，请安装: pip install pywin32")
        return False
    return True


def activate_window(hwnd=None):
    """激活游戏窗口。"""
    if not HAS_WIN32:
        return
    target = hwnd or _hwnd
    if target:
        try:
            win32gui.PostMessage(target, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)
        except Exception:
            pass


def _make_lparam(x, y):
    """将(x,y)客户区坐标打包为lParam。"""
    return win32api.MAKELONG(int(x), int(y))


def _screen_to_client(x, y):
    """将屏幕绝对坐标转换为窗口客户区坐标。"""
    if not _hwnd:
        return int(x), int(y)
    try:
        client_x, client_y = win32gui.ScreenToClient(_hwnd, (int(x), int(y)))
        return client_x, client_y
    except Exception:
        return int(x), int(y)


def move_to(x, y):
    """真正移动系统光标到屏幕坐标(x,y)。游戏根据光标位置判断滚轮作用区域。"""
    if not HAS_WIN32:
        return
    # 用SetCursorPos真正移动光标（不只是发消息）
    win32api.SetCursorPos((int(x), int(y)))


def click(x, y, down_time=0.02):
    """在屏幕坐标(x,y)处模拟左键点击。先移动真实光标再发消息。"""
    if not HAS_WIN32 or not _hwnd:
        return

    # 移动真实光标
    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(0.02)

    cx, cy = _screen_to_client(x, y)
    lparam = _make_lparam(cx, cy)

    # 发 WM_MOUSEMOVE
    win32gui.PostMessage(_hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
    time.sleep(0.01)

    # 按下
    win32gui.PostMessage(_hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(down_time)

    # 释放
    win32gui.PostMessage(_hwnd, win32con.WM_LBUTTONUP, 0, lparam)


def scroll(x, y, amount):
    """
    在屏幕坐标(x,y)处发送滚轮消息。
    amount: 正值向上滚，负值向下滚。每单位=WHEEL_DELTA(120)。
    先用SetCursorPos移动真实光标，再发滚轮消息。
    """
    if not HAS_WIN32 or not _hwnd:
        return

    # 真正移动系统光标到目标位置（游戏用光标位置判断滚哪个区域）
    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(0.02)

    # WM_MOUSEWHEEL 的 lParam 是屏幕坐标
    screen_lparam = _make_lparam(int(x), int(y))

    sign = 1 if amount > 0 else -1
    for _ in range(abs(amount)):
        wparam = win32api.MAKELONG(0, sign * win32con.WHEEL_DELTA)
        win32gui.PostMessage(_hwnd, win32con.WM_MOUSEWHEEL, wparam, screen_lparam)
        time.sleep(0.02)
