"""
分辨率坐标配置 — 基于技术方案中的游戏界面布局规则
坐标单位：像素，左上角(0,0)
"""

BASE_RESOLUTION = (1920, 1080)


BASE_CONFIG = {
        # ═══ 整体屏幕分区 ═══
        # 列表区: 左上(150,125) 右下(1220,910) → 宽1070 高785
        'sidebar': (0, 0, 150, 1080),              # 侧边导航栏
        'top_bar': (150, 0, 1070, 125),            # 顶部无效区域 y:0~125
        'list_area': (150, 125, 1070, 785),        # 声骸卡片列表 x:150~1220, y:125~910
        'list_scrollbar': (1220, 125, 20, 785),    # 列表滚动条
        'bottom_bar': (150, 910, 1070, 170),       # 底部控制栏(排序等) y:910~1080
        'detail_area': (1235, 0, 685, 1080),       # 右侧详情区 x:1235~1920

        # ═══ 列表卡片网格 ═══
        # calibrate日志(commit fc59de6): 行y=[175,385,598] 间距=[210,213] → card_height=211
        # 列x=[142,317,493,670,847,1023] 间距=[175,176,177,177,176] → card_width=176
        # card_grid_origin: calibrate推荐=(163,125)
        'card_cols': 6,
        'card_rows': 4,
        'card_width': 176,
        'card_height': 211,
        'card_grid_origin': (163, 125),

        # 卡片内等级文字ROI — 右下角"+N", 相对卡片左上角
        'level_roi_offset': (125, 170, 45, 25),  # (x, y, w, h)

        # 卡片内Cost文字ROI — 左下角, 相对卡片左上角
        'cost_roi_offset': (5, 170, 35, 25),

        # 列表区域截图(用于滚动检测)
        'list_region': (150, 125, 1070, 785),

        # ═══ 右侧详情区 ═══
        # 整区域OCR后按Y坐标zone分配。
        # calibrate日志实测y坐标:
        #   名称 y≈143, COST y≈264, 主词条 y≈474, 副属性 y≈519
        #   副词条1 y≈564, 副词条2 y≈609, 副词条3 y≈654, 副词条4 y≈699, 副词条5 y≈743
        'detail_area': (1235, 0, 685, 1080),       # 右侧详情区 x:1235~1920
        'detail_zones': {
            'name': (110, 180),
            'level': (180, 250),
            'cost': (250, 370),
            'main': (445, 496),
            'all_subs': (496, 810),
        },
        'detail_row_merge_threshold': 20,

        # 右侧详情区滚动（鼠标须在详情区内，用SetCursorPos真移光标）
        'detail_scroll_pos': (1580, 540),          # 详情区中央 x=1235+685/2≈1580
        'detail_scroll_down_steps': 25,            # 向下滚动次数（约800-1000px，确保一轮就能滚过技能描述）
        'detail_scroll_up_steps': 30,              # 向上滚回顶部次数（多滚确保到顶）

        # 底部排序按钮区域
        'sort_button': (250, 1010, 120, 40),
        'sort_menu_area': (200, 850, 200, 150),

        # 操作坐标 — 列表滚动（鼠标须在声骸列表区域内，用SetCursorPos真移光标）
        'list_scroll_pos': (685, 518),             # 列表区中央 x≈150+1070/2=685, y≈125+785/2=518
        'list_scroll_amount': -12,                 # 约2-3行，靠去重处理重叠；不够时images_similar检测到会再滚

        # 选中态检测
        'selection_border_color': (255, 215, 0),
        'selection_check_offset': (0, 0, 3, 210),
}


COMMON_RESOLUTIONS = (
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
)


CONFIGS = {
    BASE_RESOLUTION: BASE_CONFIG,
}

# 操作时序常量
TIMING = {
    'scroll_wait': 0.5,        # 滚动后等待稳定
    'click_wait': 0.3,         # 点击后等待加载
    'sort_wait': 1.0,          # 排序切换后等待重排
    'detail_scroll_wait': 0.3, # 详情区滚动后等待
}


def get_config(resolution):
    """Get config for a resolution, scaling from the 1080p baseline if needed."""
    normalized = normalize_resolution(resolution)
    if normalized in CONFIGS:
        return _copy_config(CONFIGS[normalized])

    sx, sy = get_scale(normalized)
    config = _scale_config(BASE_CONFIG, sx, sy)
    config['_resolution'] = normalized
    config['_scale'] = (sx, sy)
    config['_scaled_from'] = BASE_RESOLUTION
    config['_is_exact_config'] = False
    return config


def get_scale(resolution):
    """Return x/y scale factors from the baseline resolution."""
    width, height = resolution
    base_width, base_height = BASE_RESOLUTION
    return width / base_width, height / base_height


def normalize_resolution(resolution):
    """Normalize window rect sizes that are off by 1-2 px because of borders."""
    width, height = int(resolution[0]), int(resolution[1])
    for known_width, known_height in COMMON_RESOLUTIONS:
        if abs(width - known_width) <= 2 and abs(height - known_height) <= 2:
            return known_width, known_height
    return width, height


def get_resolution_support(resolution):
    """Return a human-readable support status for startup logs."""
    normalized = normalize_resolution(resolution)
    if normalized == BASE_RESOLUTION:
        return {
            'resolution': normalized,
            'mode': 'exact',
            'message': f'使用已验证 1080p 精确坐标配置: {normalized[0]}x{normalized[1]}',
        }

    sx, sy = get_scale(normalized)
    aspect = normalized[0] / normalized[1]
    common = normalized in COMMON_RESOLUTIONS
    if common:
        mode = 'experimental-scaled'
        message = (
            f'使用 1080p 已验证坐标等比派生: {normalized[0]}x{normalized[1]} '
            f'(sx={sx:.3f}, sy={sy:.3f})；该分辨率未实机验证，建议先 --debug 小样本校准'
        )
    else:
        mode = 'auto-scaled'
        message = (
            f'使用 1920x1080 基准自动缩放: {normalized[0]}x{normalized[1]} '
            f'(sx={sx:.3f}, sy={sy:.3f})'
        )

    if not common and not (1.55 <= aspect <= 2.45):
        message += '；当前比例不常见，建议先 --debug 小样本校准'
    elif not common:
        message += '；非内置常见分辨率，建议先 --debug 小样本校准'
    return {
        'resolution': normalized,
        'mode': mode,
        'message': message,
    }


def list_supported_resolutions():
    """Return built-in resolutions that are expected to work with auto-scaling."""
    return list(COMMON_RESOLUTIONS)


def _scale_config(cfg, sx, sy):
    """Recursively scale a config dict."""
    scaled = {}
    for key, value in cfg.items():
        if isinstance(value, tuple):
            if len(value) == 4:
                scaled[key] = (
                    int(value[0] * sx), int(value[1] * sy),
                    int(value[2] * sx), int(value[3] * sy)
                )
            elif len(value) == 2:
                scaled[key] = (int(value[0] * sx), int(value[1] * sy))
            elif len(value) == 3:
                # RGB color, don't scale
                scaled[key] = value
            else:
                scaled[key] = value
        elif isinstance(value, dict):
            if key == 'detail_zones':
                scaled[key] = {
                    zone_name: (
                        max(0, int(round(zone[0] * sy))),
                        max(0, int(round(zone[1] * sy))),
                    )
                    for zone_name, zone in value.items()
                }
            else:
                scaled[key] = _scale_config(value, sx, sy)
        elif isinstance(value, int) and key in ('card_width', 'card_height', 'card_cols', 'card_rows', 'detail_row_merge_threshold'):
            if key in ('card_width',):
                scaled[key] = max(1, int(round(value * sx)))
            elif key in ('card_height',):
                scaled[key] = max(1, int(round(value * sy)))
            elif key in ('detail_row_merge_threshold',):
                scaled[key] = max(8, int(round(value * sy)))
            else:
                scaled[key] = value
        else:
            scaled[key] = value
    return scaled


def _copy_config(cfg):
    copied = {key: _copy_value(value) for key, value in cfg.items()}
    copied['_resolution'] = BASE_RESOLUTION
    copied['_scale'] = (1.0, 1.0)
    copied['_scaled_from'] = BASE_RESOLUTION
    copied['_is_exact_config'] = True
    return copied


def _copy_value(value):
    if isinstance(value, dict):
        return {key: _copy_value(child) for key, child in value.items()}
    return value
