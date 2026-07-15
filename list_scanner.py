"""
阶段一：列表快扫 — 识别所有满级(Lv.25)声骸的位置

策略：截取整个列表区域做一次OCR，根据识别出的"+25"文字坐标
定位到对应卡片位置。避免逐卡片小区域截图（太小OCR识别不了）。
"""
import time
import os
import numpy as np
from .screen_capture import capture_region, images_similar
from .ocr_engine import get_ocr, merge_split_level_markers
from .input_control import scroll as mouse_scroll, move_to
from .config import get_config, TIMING


class ListScanner:
    def __init__(self, game_rect, debug=False):
        self.game_rect = game_rect
        gx, gy, gw, gh = game_rect
        self.config = get_config((gw, gh))
        self.max_level_positions = []
        self.debug = debug

    def scan(self, progress_callback=None):
        """Scan list pages, return positions of Lv.25 echoes."""
        page_idx = 0
        no_new_count = 0
        no_scroll_count = 0
        prev_screenshot = None

        while no_scroll_count < 3:
            cfg = self.config
            gx, gy = self.game_rect[0], self.game_rect[1]
            lx, ly, lw, lh = cfg['list_region']
            screenshot = capture_region(gx + lx, gy + ly, lw, lh)

            if prev_screenshot and images_similar(prev_screenshot, screenshot):
                no_scroll_count += 1
                if self.debug:
                    print(f"  [debug] 页面未变化 ({no_scroll_count}/3)")
            else:
                no_scroll_count = 0
                found_before = len(self.max_level_positions)

                self._scan_page_full_ocr(page_idx, screenshot)

                found_new = len(self.max_level_positions) - found_before
                if found_new == 0:
                    no_new_count += 1
                else:
                    no_new_count = 0

                if progress_callback:
                    progress_callback(page_idx, len(self.max_level_positions))

                if no_new_count >= 2 and len(self.max_level_positions) > 0:
                    if self.debug:
                        print(f"  [debug] 连续{no_new_count}页无新增满级，提前终止")
                    break

            prev_screenshot = screenshot
            page_idx += 1

            self._scroll_list()
            time.sleep(TIMING['scroll_wait'])

        scanned_pages = page_idx - no_scroll_count
        print(f"阶段一完成: 共扫描{scanned_pages}页，发现{len(self.max_level_positions)}个满级声骸")
        return self.max_level_positions

    def _scan_page_full_ocr(self, page_idx, list_img):
        """
        对整个列表区域做一次OCR，找出所有含"+25"或"25"的文字，
        根据文字在图片中的坐标位置确定属于哪张卡片。
        """
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]
        grid_ox, grid_oy = cfg['card_grid_origin']
        lx, ly, lw, lh = cfg['list_region']
        card_w = cfg['card_width']
        card_h = cfg['card_height']
        cols = cfg['card_cols']
        rows = cfg['card_rows']

        # 保存debug截图
        if self.debug:
            os.makedirs('debug_output', exist_ok=True)
            list_img.save(f'debug_output/page_{page_idx}.png')

        # 对整个列表区域做OCR
        ocr = get_ocr()
        img_array = np.array(list_img)
        results = ocr.ocr(img_array, cls=True)

        if self.debug:
            print(f"  [debug] 页{page_idx} OCR结果数: {len(results[0]) if results and results[0] else 0}")

        if not results or not results[0]:
            if self.debug:
                print(f"  [debug] 页{page_idx} OCR无结果")
            return

        # 合并被OCR拆分的 '+' 和 '25'
        ocr_lines = merge_split_level_markers(results[0])

        found_cards = set()

        for line in ocr_lines:
            # line = [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], (text, conf)]
            bbox = line[0]
            text = line[1][0]
            conf = line[1][1]

            # 查找含有"25"的文本（等级显示为"+25"或"25"）
            if '25' not in text:
                continue

            # 检查是否确实是等级标记（排除其他含25的文本）
            clean = text.replace('+', '').replace(' ', '')
            if clean != '25':
                # 可能是"125"之类的，跳过
                try:
                    num = int(clean)
                    if num != 25:
                        continue
                except ValueError:
                    continue

            if self.debug:
                print(f"  [debug] 发现 '{text}' conf={conf:.2f} at bbox={bbox}")

            # bbox中心坐标（相对于列表区域图片）
            cx = (bbox[0][0] + bbox[2][0]) / 2
            cy = (bbox[0][1] + bbox[2][1]) / 2

            # 判断属于哪张卡片
            col = int(cx // card_w)
            row = int(cy // card_h)

            if col >= cols or row >= rows:
                continue

            card_key = (row, col)
            if card_key in found_cards:
                continue
            found_cards.add(card_key)

            # 计算卡片中心点击坐标（屏幕绝对坐标）
            click_x = gx + grid_ox + col * card_w + card_w // 2
            click_y = gy + grid_oy + row * card_h + card_h // 2

            self.max_level_positions.append({
                'page': page_idx,
                'row': row,
                'col': col,
                'click_pos': (click_x, click_y),
                'level': 25,
            })

            if self.debug:
                print(f"  [debug] → 卡片[{row},{col}] 点击坐标({click_x},{click_y})")

    def _scroll_list(self):
        """在列表区域内模拟鼠标滚轮翻页。"""
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]
        sx, sy = cfg['list_scroll_pos']
        mouse_scroll(gx + sx, gy + sy, cfg['list_scroll_amount'])
