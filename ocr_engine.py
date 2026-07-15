import os
os.environ['FLAGS_use_mkldnn'] = '0'

from paddleocr import PaddleOCR
from PIL import Image
import numpy as np

_ocr = None


def get_ocr():
    global _ocr
    if _ocr is None:
        _ocr = PaddleOCR(use_angle_cls=True, lang='ch', use_gpu=False, show_log=False)
    return _ocr


def ocr_image(image, confidence_threshold=0.85):
    """OCR an image, returns list of (text, confidence)."""
    ocr = get_ocr()
    img_array = np.array(image)
    results = ocr.ocr(img_array, cls=True)

    texts = []
    if results:
        for page in results:
            if not page:
                continue
            for line in page:
                if len(line) >= 2 and isinstance(line[1], (list, tuple)):
                    text = line[1][0]
                    conf = line[1][1]
                    texts.append((text, conf))
    return texts


def ocr_region_text(image, confidence_threshold=0.85):
    """OCR an image and return concatenated text (filtered by confidence)."""
    results = ocr_image(image, confidence_threshold)
    filtered = [(t, c) for t, c in results if c >= confidence_threshold]
    return ' '.join(t for t, _ in filtered), min((c for _, c in filtered), default=1.0)


def extract_number(text):
    """Extract a number from OCR text (handles % and decimal)."""
    import re
    text = text.replace(' ', '').replace('％', '%').replace(',', '')
    match = re.search(r'(\d+\.?\d*)', text)
    if match:
        return float(match.group(1))
    return None


def merge_split_level_markers(all_lines, level=25, distance_threshold=30):
    """合并被PaddleOCR拆分开的 '+' 和等级数字（如 '+25' → '+' 和 '25'）。

    PaddleOCR 有时会将卡片上的 '+25' 识别为两个独立文本块：'+' 和 '25'，
    导致按完整 '+25' 匹配时漏检。此函数通过距离阈值将相邻的 '+' 和
    等级数字合并回一个文本块。

    Args:
        all_lines: PaddleOCR 原始结果列表，格式为
                   [ [[bbox], (text, conf)], ... ]
        level: 要匹配的等级数字，默认 25
        distance_threshold: 合并距离阈值（像素），默认 30

    Returns:
        合并后的文本行列表，格式与输入相同。
    """
    import math

    level_str = str(level)
    merged = list(all_lines)

    plus_signs = []
    level_nums = []

    for i, line in enumerate(merged):
        text = line[1][0].strip()
        bbox = line[0]
        cx = (bbox[0][0] + bbox[2][0]) / 2
        cy = (bbox[0][1] + bbox[2][1]) / 2

        if text == '+':
            plus_signs.append((i, cx, cy))
        elif text == level_str:
            level_nums.append((i, cx, cy))

    used_plus = set()
    used_num = set()
    new_lines = []

    for pi, px, py in plus_signs:
        best_dist = float('inf')
        best_ni = None
        for ni, nx, ny in level_nums:
            if ni in used_num:
                continue
            dist = math.hypot(px - nx, py - ny)
            if dist < best_dist:
                best_dist = dist
                best_ni = ni

        if best_ni is not None and best_dist <= distance_threshold:
            plus_line = merged[pi]
            num_line = merged[best_ni]

            # 合并两个bbox为最小外接矩形
            all_xs = [plus_line[0][j][0] for j in range(4)] + [num_line[0][j][0] for j in range(4)]
            all_ys = [plus_line[0][j][1] for j in range(4)] + [num_line[0][j][1] for j in range(4)]
            min_x, max_x = min(all_xs), max(all_xs)
            min_y, max_y = min(all_ys), max(all_ys)
            merged_bbox = [
                [min_x, min_y], [max_x, min_y],
                [max_x, max_y], [min_x, max_y]
            ]
            avg_conf = (plus_line[1][1] + num_line[1][1]) / 2

            new_lines.append([merged_bbox, (f'+{level_str}', avg_conf)])
            used_plus.add(pi)
            used_num.add(best_ni)

    for i, line in enumerate(merged):
        if i not in used_plus and i not in used_num:
            new_lines.append(line)

    return new_lines
