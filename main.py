"""
鸣潮声骸OCR扫描工具
自动检测游戏 → 排序设置 → 逐页扫描+识别 → 导出JSON

Usage: python -m scanner [--debug]
"""
import sys
import time
from .game_detector import wait_for_game, find_game_process
from .page_scanner import PageScanner
from .progress import ScanProgress
from .export import LiveExporter
from .models import Echo
from .screen_capture import capture_region
from .ocr_engine import ocr_image
from . import input_control
from .input_control import ensure_admin, activate_window
from .config import get_config, get_resolution_support, TIMING


def ensure_sort_by_level(game_rect):
    """
    阶段零：检测并切换排序方式为"等级顺序"
    确保满级声骸集中在列表顶部，整页无满级时可提前终止。
    """
    gx, gy, gw, gh = game_rect
    cfg = get_config((gw, gh))

    print("\n═══ 排序检测 ═══")

    bx, by, bw, bh = cfg['bottom_bar']
    bar_img = capture_region(gx + bx, gy + by, bw, bh)
    results = ocr_image(bar_img)

    current_sort = None
    for text, conf in results:
        if '等级' in text:
            current_sort = '等级'
            break
        if '获取时间' in text or '时间' in text:
            current_sort = '时间'
        if '稀有度' in text:
            current_sort = '稀有度'

    if current_sort == '等级':
        print("  ✓ 当前已按等级排序")
        return True

    print(f"  当前排序: {current_sort or '未识别'}")
    print("  建议手动切换为「等级顺序」排序以加速扫描")
    print("  （等级排序下满级声骸集中在顶部，整页无满级即停止）")
    choice = input("  是否继续当前排序扫描? [Y/n]: ").strip().lower()
    if choice == 'n':
        print("  请在游戏中切换排序后重新运行工具")
        return False
    return True


def main():
    print("=" * 50)
    print("  鸣潮声骸OCR扫描工具 v1.0")
    print("=" * 50)
    print()

    debug = '--debug' in sys.argv

    # Step 1: Detect game
    proc = find_game_process()
    if not proc:
        print("未检测到鸣潮游戏进程。")
        print("请先启动鸣潮游戏，然后重新运行本工具。")
        print("\n支持的进程: Wuthering Waves.exe / Client-Win64-Shipping.exe")
        input("\n按 Enter 退出...")
        sys.exit(1)

    print(f"✓ 检测到鸣潮进程: {proc.info['name']} (PID: {proc.pid})")

    # 检查依赖
    if not ensure_admin():
        input("\n按 Enter 退出...")
        sys.exit(1)

    # Get window
    window = wait_for_game(timeout=10)
    if not window:
        print("✗ 无法获取游戏窗口，请确保游戏以全屏或无边框模式运行")
        input("\n按 Enter 退出...")
        sys.exit(1)

    hwnd, game_rect = window
    gx, gy, gw, gh = game_rect
    print(f"  窗口分辨率: {gw}x{gh}")
    support = get_resolution_support((gw, gh))
    print(f"  分辨率适配: {support['message']}")

    # 初始化输入控制（传入游戏窗口句柄）
    input_control.init(hwnd)
    activate_window(hwnd)
    print("✓ 输入控制已初始化（PostMessage模式）")

    # Step 2: Check for incomplete scan
    progress = ScanProgress()
    if progress.has_incomplete():
        count = progress.get_scanned_count()
        print(f"\n发现未完成的扫描记录 (已完成 {count} 个)")
        choice = input("是否继续上次扫描? [Y/n]: ").strip().lower()
        if choice == 'n':
            progress.reset()
        else:
            return resume_scan(game_rect, progress, debug)

    # Step 3: Guide user
    print("\n" + "-" * 50)
    print("请执行以下操作：")
    print("  1. 切换到鸣潮游戏窗口")
    print("  2. 打开 声骸仓库 界面")
    print("  3. 将排序方式设为「等级顺序」")
    print("  4. 滚动到列表最顶部")
    print("-" * 50)
    input("\n准备好后按 Enter 开始扫描...")

    # Give user time to switch to game
    print("\n20秒后开始扫描，请立即切换到游戏窗口...")
    for i in range(20, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    # Sort detection
    if not ensure_sort_by_level(game_rect):
        input("\n按 Enter 退出...")
        sys.exit(0)

    # Step 4: Single-pass scan
    print("\n═══ 开始扫描（逐页识别）═══")
    print("  每页：OCR列表找满级 → 点击卡片读详情 → 翻页")
    print("  整页无满级声骸时自动停止\n")

    progress.set_phase('scanning')

    scanner = PageScanner(game_rect, debug=debug)
    exporter = LiveExporter()
    start_time = time.time()

    print(f"  实时输出文件: {exporter.filepath} (每识别一个立即写入)\n")

    def on_echo_found(echo):
        exporter.add(echo)
        progress.add_echo(echo.to_dict())

    echoes = scanner.scan_all(
        progress_callback=lambda page, total: print(
            f"  第{page+1}页 | 已识别 {total} 个声骸", end='\r'
        ),
        on_echo=on_echo_found,
    )

    total_time = time.time() - start_time

    if not echoes:
        print("\n未识别到任何声骸。")
        print("  提示: 添加 --debug 参数查看详细输出:")
        print("  python -m scanner --debug")
        input("\n按 Enter 退出...")
        sys.exit(0)

    # Finalize
    print(f"\n✓ 扫描完成，共识别 {len(echoes)} 个声骸 (耗时 {int(total_time)}秒)")

    issues_count = sum(1 for e in echoes if hasattr(e, 'validation_issues') and e.validation_issues)
    if issues_count:
        print(f"  ⚠ {issues_count} 个声骸存在校验警告（建议人工检查）")

    filepath = exporter.finalize()
    progress.mark_complete()

    print(f"\n请在Web端导入文件: {filepath}")
    input("\n按 Enter 退出...")


def resume_scan(game_rect, progress, debug=False):
    """从进度文件恢复扫描。"""
    already = [Echo.from_dict(d) for d in progress.data.get('scanned_echoes', [])]
    print(f"\n已恢复 {len(already)} 个声骸，继续扫描新页面...")
    print("20秒后开始，请切换到游戏窗口...")
    for i in range(20, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    exporter = LiveExporter()
    for e in already:
        exporter.add(e)

    scanner = PageScanner(game_rect, debug=debug)
    new_echoes = scanner.scan_all(
        on_echo=lambda echo: (exporter.add(echo), progress.add_echo(echo.to_dict())),
    )

    filepath = exporter.finalize()
    progress.mark_complete()
    print(f"\n导出完成！共 {len(exporter.echoes)} 个声骸，文件: {filepath}")
    input("\n按 Enter 退出...")


if __name__ == '__main__':
    main()
