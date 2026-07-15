import psutil
import time

GAME_PROCESSES = ['Client-Win64-Shipping.exe', 'Wuthering Waves.exe']


def find_game_process():
    """查找游戏进程，优先返回Client-Win64-Shipping.exe。"""
    found = []
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            if proc.info['name'] in GAME_PROCESSES:
                found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not found:
        return None

    # 优先返回实际游戏进程（Client-Win64-Shipping.exe）
    for proc in found:
        if proc.info['name'] == 'Client-Win64-Shipping.exe':
            return proc
    return found[0]


def get_game_window():
    """遍历所有游戏相关进程，找到有大窗口的那个。返回 (hwnd, (x, y, w, h)) 或 None。"""
    try:
        import win32gui
        import win32process

        # 收集所有游戏进程的PID
        game_pids = set()
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                if proc.info['name'] in GAME_PROCESSES:
                    game_pids.add(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not game_pids:
            return None

        result = None

        def callback(hwnd, _):
            nonlocal result
            if result:
                return
            if win32gui.IsWindowVisible(hwnd):
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid in game_pids:
                    rect = win32gui.GetWindowRect(hwnd)
                    w = rect[2] - rect[0]
                    h = rect[3] - rect[1]
                    if w > 800 and h > 600:
                        result = (hwnd, (rect[0], rect[1], w, h))

        win32gui.EnumWindows(callback, None)
        return result
    except ImportError:
        return None


def wait_for_game(timeout=60):
    """等待检测到游戏窗口。返回 (hwnd, (x, y, w, h)) 或 None。"""
    print("正在检测鸣潮游戏窗口...")
    start = time.time()
    while time.time() - start < timeout:
        window = get_game_window()
        if window:
            hwnd, (x, y, w, h) = window
            print(f"✓ 检测到鸣潮窗口: {w}x{h} at ({x},{y})")
            return window
        time.sleep(1)
    print("✗ 未检测到鸣潮游戏窗口，请确认游戏已启动且非最小化")
    return None
