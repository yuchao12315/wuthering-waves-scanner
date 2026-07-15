"""
坐标校准工具 — 完整校验扫描流程

Usage: python -m scanner.calibrate

校准流程：
1. 列表区分析：推算卡片尺寸
2. 详情区分析：视口1词条 + 视口2滚动找套装
3. 端到端校验：点击3个卡片，完整走一遍扫描流程，检查每个字段是否识别到
"""
import os
import sys
import re
import time
import numpy as np
from .game_detector import wait_for_game, find_game_process
from .screen_capture import capture_region
from .config import get_config
from .ocr_engine import get_ocr, ocr_image, merge_split_level_markers, extract_number
from .input_control import click as mouse_click, scroll as mouse_scroll, move_to, init as init_input
from .page_scanner import SONATA_MAP, classify_stat, parse_stat_line

OUTPUT_DIR = 'calibrate_output'


def main():
    print("═══ 声骸扫描坐标校准工具 ═══\n")

    proc = find_game_process()
    if not proc:
        print("✗ 未检测到鸣潮游戏进程，请先启动游戏")
        input("\n按 Enter 退出...")
        sys.exit(1)

    window = wait_for_game(timeout=10)
    if not window:
        print("✗ 无法获取游戏窗口")
        input("\n按 Enter 退出...")
        sys.exit(1)

    hwnd, game_rect = window
    gx, gy, gw, gh = game_rect
    print(f"✓ 游戏窗口: {gw}x{gh} at ({gx},{gy})")

    cfg = get_config((gw, gh))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    init_input(hwnd)

    print("\n请打开声骸仓库界面（确保有满级声骸、按等级排序），然后按 Enter...")
    input()
    print("10秒后开始，请切换到游戏窗口...")
    for i in range(10, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    ocr = get_ocr()
    dx, dy, dw, dh = cfg['detail_area']
    sx, sy = cfg['detail_scroll_pos']
    grid_ox, grid_oy = cfg['card_grid_origin']
    card_w = cfg['card_width']
    card_h = cfg['card_height']

    # ═══ 1. 全屏截图 ═══
    print("\n═══ 1. 全屏截图 ═══")
    full_img = capture_region(gx, gy, gw, gh)
    full_img.save(os.path.join(OUTPUT_DIR, 'full_screen.png'))
    print(f"  ✓ 保存: {OUTPUT_DIR}/full_screen.png")

    # ═══ 2. 列表区域分析 ═══
    print("\n═══ 2. 列表区域分析 ═══")
    lx, ly, lw, lh = cfg['list_region']
    list_img = capture_region(gx + lx, gy + ly, lw, lh)
    list_img.save(os.path.join(OUTPUT_DIR, 'list_region.png'))
    print(f"  当前配置: list_region=({lx},{ly},{lw},{lh})")

    img_array = np.array(list_img)
    results = ocr.ocr(img_array, cls=True)
    all_lines = merge_split_level_markers(results[0] if results and results[0] else [])

    level_positions = []
    for line in all_lines:
        bbox = line[0]
        text = line[1][0]
        nums = re.findall(r'\d+', text)
        if any(int(n) == 25 for n in nums) and len(text) <= 6:
            cx = int((bbox[0][0] + bbox[2][0]) / 2)
            cy = int((bbox[0][1] + bbox[2][1]) / 2)
            level_positions.append((cx, cy))

    print(f"  找到 {len(level_positions)} 个'+25'标记")

    # 推算卡片尺寸
    avg_height = cfg['card_height']
    avg_width = cfg['card_width']
    if len(level_positions) >= 2:
        level_positions.sort(key=lambda p: p[1])
        rows_y = []
        current_row = [level_positions[0][1]]
        for i in range(1, len(level_positions)):
            if level_positions[i][1] - current_row[-1] > 50:
                rows_y.append(int(sum(current_row) / len(current_row)))
                current_row = [level_positions[i][1]]
            else:
                current_row.append(level_positions[i][1])
        rows_y.append(int(sum(current_row) / len(current_row)))

        print(f"  行y坐标: {rows_y}")
        if len(rows_y) >= 2:
            heights = [rows_y[i+1] - rows_y[i] for i in range(len(rows_y)-1)]
            min_h = min(heights)
            avg_height = int(sum(heights) / len(heights))
            if min_h > 300:
                avg_height = min_h // 2
                print(f"  间距{min_h}过大，推测隔行 → card_height = {avg_height}")
            else:
                print(f"  → card_height = {avg_height}")

        row_with_most = []
        for ry in rows_y:
            items = sorted([(cx, cy) for cx, cy in level_positions if abs(cy - ry) < 50], key=lambda p: p[0])
            if len(items) > len(row_with_most):
                row_with_most = items
        if len(row_with_most) >= 2:
            widths = [row_with_most[i+1][0] - row_with_most[i][0] for i in range(len(row_with_most)-1)]
            avg_width = int(sum(widths) / len(widths))
            print(f"  → card_width = {avg_width}")

    scroll_steps = max(1, avg_height * 3 // 40)
    print(f"  → list_scroll_amount = -{scroll_steps}")

    # ═══ 3. 端到端校验：点击3个卡片完整扫描 ═══
    print(f"\n═══ 3. 端到端校验（点击前3个卡片）═══")
    print(f"  模拟实际扫描流程: 点击卡片 → 回顶 → OCR视口1 → 滚动 → OCR视口2")

    sonata_names = list(SONATA_MAP.keys())
    all_ok = True

    for card_idx in range(3):
        col = card_idx % cfg['card_cols']
        row = card_idx // cfg['card_cols']
        click_x = gx + grid_ox + col * card_w + card_w // 2
        click_y = gy + grid_oy + row * card_h + card_h // 2

        print(f"\n  --- 卡片#{card_idx+1} [{row},{col}] 点击({click_x},{click_y}) ---")

        # 回顶部（只移动光标，不点击详情区，避免触发游戏交互）
        move_to(gx + sx, gy + sy)
        time.sleep(0.1)
        for _ in range(30):
            mouse_scroll(gx + sx, gy + sy, 1)
            time.sleep(0.03)
        time.sleep(0.5)

        # 点击卡片
        mouse_click(click_x, click_y)
        time.sleep(1.0)

        # 回顶部
        move_to(gx + sx, gy + sy)
        time.sleep(0.1)
        for _ in range(30):
            mouse_scroll(gx + sx, gy + sy, 1)
            time.sleep(0.03)
        time.sleep(0.5)

        # OCR视口1
        detail_img = capture_region(gx + dx, gy + dy, dw, dh)
        detail_img.save(os.path.join(OUTPUT_DIR, f'verify_{card_idx+1}_vp1.png'))
        img_arr = np.array(detail_img)
        vp1_results = ocr.ocr(img_arr, cls=True)
        vp1_lines = sorted(
            vp1_results[0] if vp1_results and vp1_results[0] else [],
            key=lambda l: (l[0][0][1] + l[0][2][1]) / 2
        )

        # 打印OCR原始结果（含x,y双坐标）
        print(f"    OCR原始结果 ({len(vp1_lines)}条):")
        for line in vp1_lines:
            text = line[1][0]
            conf = line[1][1]
            cx = int((line[0][0][0] + line[0][2][0]) / 2)
            cy = int((line[0][0][1] + line[0][2][1]) / 2)
            print(f"      [{conf:.2f}] x={cx:4d} y={cy:4d} '{text}'")

        # 用zone合并策略解析（与page_scanner一致）
        fields = {'名称': None, '等级': None, 'Cost': None, '主词条': None, '副属性': None, '副词条': [], '套装': None}

        zones = {
            'name': (110, 180, []),
            'level': (180, 250, []),
            'cost': (250, 370, []),
            'main': (445, 496, []),
            'all_subs': (496, 810, []),
        }

        for line in vp1_lines:
            text = line[1][0]
            conf = line[1][1]
            cy = int((line[0][0][1] + line[0][2][1]) / 2)
            if conf < 0.6:
                continue
            # 清理OCR噪声
            noise_prefixes = ['艾', '袋', '众', '必', 'X', '我X', '我']
            cleaned = text.strip()
            for prefix in noise_prefixes:
                if cleaned.startswith(prefix) and len(cleaned) > len(prefix):
                    rest = cleaned[len(prefix):]
                    if rest and rest[0] in '攻生防暴共普重治':
                        cleaned = rest
                        break
            for zone_name, (y_min, y_max, texts) in zones.items():
                if y_min <= cy <= y_max:
                    texts.append(cleaned)
                    break

        # 名称
        for t in zones['name'][2]:
            if len(t) >= 2 and not t.isdigit():
                fields['名称'] = t
                break

        # 等级
        for t in zones['level'][2]:
            nums = re.findall(r'\d+', t)
            for n in nums:
                v = int(n)
                if 1 <= v <= 25:
                    fields['等级'] = v

        # Cost
        all_cost = ' '.join(zones['cost'][2])
        if 'COST' in all_cost.upper():
            nums = re.findall(r'\d+', all_cost)
            for n in nums:
                if int(n) in (1, 3, 4):
                    fields['Cost'] = int(n)
                    break

        # 主词条（合并后解析）
        main_text = ' '.join(zones['main'][2])
        if main_text:
            stat = parse_stat_line(main_text)
            if stat:
                fields['主词条'] = stat

        # 副属性 + 副词条 — 从 all_subs 大区用 Y 近邻聚类自动分行
        all_subs_lines = []
        for line in vp1_lines:
            text = line[1][0]
            conf = line[1][1]
            cy = int((line[0][0][1] + line[0][2][1]) / 2)
            if conf < 0.6:
                continue
            y_min, y_max = zones['all_subs'][0], zones['all_subs'][1]
            if y_min <= cy <= y_max:
                # 清理OCR噪声
                noise_prefixes = ['艾', '袋', '众', '必', 'X', '我X', '我']
                cleaned = text.strip()
                for prefix in noise_prefixes:
                    if cleaned.startswith(prefix) and len(cleaned) > len(prefix):
                        rest = cleaned[len(prefix):]
                        if rest and rest[0] in '攻生防暴共普重治':
                            cleaned = rest
                            break
                all_subs_lines.append((cy, cleaned))

        all_subs_lines.sort(key=lambda x: x[0])
        groups = []
        for cy, text in all_subs_lines:
            if groups and cy - groups[-1][1] <= 20:
                groups[-1][0].append(text)
                groups[-1][1] = max(groups[-1][1], cy)
            else:
                groups.append([[text], cy])

        secondary_stat = None
        for texts, _ in groups:
            combined = ' '.join(texts)
            stat = parse_stat_line(combined)
            if stat:
                if secondary_stat is None:
                    secondary_stat = stat
                    fields['副属性'] = stat
                else:
                    fields['副词条'].append(stat)

        # 视口2: 滚动找套装
        move_to(gx + sx, gy + sy)
        time.sleep(0.1)
        for scroll_round in range(4):
            scroll_count = cfg.get('detail_scroll_down_steps', 15)
            for _ in range(scroll_count):
                mouse_scroll(gx + sx, gy + sy, -1)
                time.sleep(0.03)
            time.sleep(0.4)

            vp2_img = capture_region(gx + dx, gy + dy, dw, dh)
            vp2_img.save(os.path.join(OUTPUT_DIR, f'verify_{card_idx+1}_vp2_s{scroll_round+1}.png'))
            vp2_arr = np.array(vp2_img)
            vp2_results = ocr.ocr(vp2_arr, cls=True)
            vp2_sorted = sorted(
                vp2_results[0] if vp2_results and vp2_results[0] else [],
                key=lambda l: (l[0][0][1] + l[0][2][1]) / 2
            )

            # 搜索套装
            for i, line in enumerate(vp2_sorted):
                text = line[1][0]
                for cn_name in sonata_names:
                    if cn_name in text:
                        fields['套装'] = cn_name
                        break
                if fields['套装']:
                    break
                # 合鸣效果下一行
                if '合鸣效果' in text or '合鸣' in text:
                    if i + 1 < len(vp2_sorted):
                        next_text = vp2_sorted[i + 1][1][0].strip()
                        for cn_name in sonata_names:
                            if cn_name in next_text:
                                fields['套装'] = cn_name
                                break
                        if not fields['套装'] and len(next_text) >= 2:
                            fields['套装'] = next_text
                    break

            if fields['套装']:
                break

        # 回顶部
        move_to(gx + sx, gy + sy)
        time.sleep(0.1)
        for _ in range(30):
            mouse_scroll(gx + sx, gy + sy, 1)
            time.sleep(0.03)

        # 打印结果
        checks = [
            ('名称', fields['名称']),
            ('等级', fields['等级']),
            ('Cost', fields['Cost']),
            ('主词条', fields['主词条']),
            ('副属性', fields['副属性']),
            ('副词条', fields['副词条'] if fields['副词条'] else None),
            ('套装', fields['套装']),
        ]

        for label, value in checks:
            if value is not None:
                if label == '副词条':
                    print(f"    ✓ {label}: {len(value)}条")
                    for j, sub in enumerate(value):
                        print(f"        [{j+1}] {sub['type']} = {sub['value']}")
                    if len(value) < 5:
                        print(f"        ⚠ 预期5条，实际{len(value)}条")
                        all_ok = False
                else:
                    print(f"    ✓ {label}: {value}")
            else:
                print(f"    ✗ {label}: 未识别")
                all_ok = False

    # ═══ 4. 底部栏 ═══
    print(f"\n═══ 4. 底部控制栏 ═══")
    bx, by, bw, bh = cfg['bottom_bar']
    bar_img = capture_region(gx + bx, gy + by, bw, bh)
    bar_img.save(os.path.join(OUTPUT_DIR, 'bottom_bar.png'))
    bar_results = ocr_image(bar_img)
    print(f"  OCR: {[t for t, c in bar_results]}")

    # ═══ 总结 ═══
    print(f"\n{'═'*50}")
    if all_ok:
        print(f"  ✓ 校准完成！所有字段均能正确识别")
    else:
        print(f"  ⚠ 校准完成，部分字段识别失败")
        print(f"    请检查截图并调整 config.py 中的坐标")
    print(f"{'═'*50}")

    print(f"\n  推荐配置:")
    print(f"    card_width = {avg_width}")
    print(f"    card_height = {avg_height}")
    print(f"    list_scroll_amount = -{scroll_steps}")

    print(f"\n  截图保存在: {os.path.abspath(OUTPUT_DIR)}/")
    print(f"    full_screen.png       — 全屏")
    print(f"    list_region.png       — 列表区")
    print(f"    verify_N_vp1.png      — 第N个卡片视口1")
    print(f"    verify_N_vp2_sM.png   — 第N个卡片视口2第M次滚动")
    print(f"    bottom_bar.png        — 底部栏")

    input("\n按 Enter 退出...")


if __name__ == '__main__':
    main()
