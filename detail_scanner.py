"""
阶段二：详情精扫 — 逐个点击满级声骸，OCR右侧详情区

流程（每个声骸）：
1. 点击卡片中心 → 等待加载
2. 截取右侧视口1 → OCR: 名称/等级/Cost/副属性/主词条/副词条
3. 模拟右侧详情区向下滚动
4. 截取右侧视口2 → OCR: 套装名称
5. 点击下一个卡片（详情页自动刷新到顶部）
"""
import os
import time
import numpy as np
from .screen_capture import capture_region
from .ocr_engine import get_ocr, ocr_image, ocr_region_text, extract_number
from .input_control import click as mouse_click, scroll as mouse_scroll, move_to
from .config import get_config, TIMING
from .models import Echo
from .validator import validate_echo

# 词条类型映射
STAT_TYPE_MAP = {
    '攻击': 'FLAT_ATK', '生命': 'FLAT_HP', '防御': 'FLAT_DEF',
    '暴击率': 'CRIT_RATE', '暴击伤害': 'CRIT_DMG',
    '共鸣效率': 'ENERGY_REGEN', '治疗效果加成': 'HEAL_BONUS',
    '气动伤害加成': 'ELEM_DMG', '热熔伤害加成': 'ELEM_DMG',
    '导电伤害加成': 'ELEM_DMG', '衍射伤害加成': 'ELEM_DMG',
    '冷凝伤害加成': 'ELEM_DMG', '湮灭伤害加成': 'ELEM_DMG',
    '普攻伤害加成': 'NORMAL_ATK_DMG', '重击伤害加成': 'HEAVY_ATK_DMG',
    '共鸣技能伤害加成': 'RESONANCE_SKILL_DMG',
    '共鸣解放伤害加成': 'RESONANCE_LIBERATION_DMG',
}

SONATA_MAP = {
    '凝夜白霜': 'freezing_frost', '熔山裂谷': 'molten_rift',
    '彻空冥雷': 'void_thunder', '啸谷长风': 'sierra_gale',
    '浮星祛暗': 'celestial_light', '沉日劫明': 'havoc_eclipse',
    '隐世回光': 'rejuvenating_glow', '轻云出月': 'moonlit_clouds',
    '不绝余音': 'lingering_tunes', '凌冽决断': 'frosty_resolve',
    '此间永驻之光': 'eternal_radiance', '幽夜隐匿': 'midnight_veil',
    '高天共奏之曲': 'empyrean_anthem', '破浪无惧': 'tidebreaking_courage',
    '流云逝尽之空': 'gusts_of_welkin', '愿戴荣光之旅': 'windward_pilgrimage',
    '奔狼燎原之焰': 'flaming_clawprint', '逆光跃彩之约': 'pact_of_neonlight_leap',
    '星构寻辉之环': 'halo_of_starry_radiance',
    '流金溯真之式': 'rite_of_gilded_revelation',
    '长路启航之星': 'trailblazing_star', '斑驳粉饰之沫': 'chromatic_foam',
    '听唤语义之愿': 'sound_of_true_name', '雪落无声之愿': 'wishes_of_quiet_snowfall',
    '剪心辑梦之影': 'reel_of_spliced_memories',
    '失序彼岸之梦': 'dream_of_the_lost', '息界同调之律': 'law_of_harmony',
    '荣斗铸锋之冠': 'crown_of_valor', '焚羽猎魔之影': 'flamewings_shadow',
    '命理崩毁之弦': 'thread_of_severed_fate',
    '碎梦亡鬼之魇': 'shadow_of_shattered_dreams',
    # Legacy aliases (旧版映射，兼容已有扫描数据)
    '永夜辉光': 'eternal_radiance', '天穹鸣歌': 'empyrean_anthem',
}


def classify_stat(text):
    """识别词条类型。攻击/生命/防御需根据是否含%区分FLAT和PCT。"""
    noise_prefixes = ['艾', '袋', '众', '必', 'X', '文']
    cleaned = text.strip()
    for prefix in noise_prefixes:
        if cleaned.startswith(prefix) and len(cleaned) > len(prefix):
            rest = cleaned[len(prefix):]
            if rest and rest[0] in '攻生防暴共普重治':
                cleaned = rest
                break

    is_pct = '%' in cleaned or '％' in cleaned

    # 优先处理攻击/生命/防御
    if '攻击' in cleaned:
        return 'ATK_PCT' if is_pct else 'FLAT_ATK'
    if '生命' in cleaned:
        return 'HP_PCT' if is_pct else 'FLAT_HP'
    if '防御' in cleaned:
        return 'DEF_PCT' if is_pct else 'FLAT_DEF'

    # 暴击（不含'伤害'）→ CRIT_RATE
    if '暴击' in cleaned and '伤害' not in cleaned:
        return 'CRIT_RATE'

    for key, stype in STAT_TYPE_MAP.items():
        if key in cleaned:
            return stype

    return None


def parse_stat_line(text):
    """解析合并后的词条文本为 {type, value}。"""
    stat_type = classify_stat(text)
    value = extract_number(text)
    if stat_type and value is not None:
        # 二次修正：无%但数值是小数<100 → PCT
        if value < 100 and '.' in text:
            if stat_type == 'FLAT_ATK':
                stat_type = 'ATK_PCT'
            elif stat_type == 'FLAT_HP':
                stat_type = 'HP_PCT'
            elif stat_type == 'FLAT_DEF':
                stat_type = 'DEF_PCT'
        return {'type': stat_type, 'value': value}
    return None


class DetailScanner:
    def __init__(self, game_rect, debug=False):
        self.game_rect = game_rect
        gx, gy, gw, gh = game_rect
        self.config = get_config((gw, gh))
        self.debug = debug
        self.scan_count = 0

    def scan_echo(self, click_pos, retry=0):
        """点击卡片并OCR详情页，返回Echo对象或None。"""
        self.scan_count += 1

        if self.debug:
            print(f"\n  [debug] === 声骸#{self.scan_count} 点击坐标{click_pos} ===")

        # 用win32api直接发送鼠标事件（绕过游戏DirectX拦截）
        mouse_click(click_pos[0], click_pos[1])
        time.sleep(0.8)  # 等待详情区加载

        # 截取视口1 — 词条信息
        data = self._ocr_viewport1()

        if self.debug:
            print(f"  [debug] 视口1: name='{data.get('monsterName')}', cost={data.get('cost')}, "
                  f"main={data.get('mainStat')}, subs={len(data.get('substats', []))}")

        # 滚动右侧详情区读取套装
        self._scroll_detail_down()
        time.sleep(0.5)

        # 截取视口2 — 套装信息
        sonata = self._ocr_viewport2_sonata()
        data['sonata'] = sonata

        if self.debug:
            print(f"  [debug] 视口2: sonata={sonata}")

        # 构建Echo对象
        try:
            echo = Echo.from_ocr_data(data)
            issues = validate_echo(echo)
            if issues:
                echo.validation_issues = issues
                if self.debug:
                    print(f"  [debug] 校验警告: {issues}")
            return echo
        except Exception as e:
            if self.debug:
                print(f"  [debug] 构建Echo失败: {e}")
            return None

    def _ocr_viewport1(self):
        """OCR右侧详情区视口1（初始可见区域）— 整区域一次OCR。"""
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]

        # 截取整个右侧详情区做一次OCR（更准确）
        dx, dy, dw, dh = cfg['detail_area']
        detail_img = capture_region(gx + dx, gy + dy, dw, dh)

        if self.debug:
            os.makedirs('debug_output', exist_ok=True)
            detail_img.save(f'debug_output/detail_{self.scan_count}_vp1.png')

        ocr = get_ocr()
        img_array = np.array(detail_img)
        results = ocr.ocr(img_array, cls=True)
        all_lines = results[0] if results and results[0] else []

        if self.debug:
            print(f"  [debug] 详情区OCR结果数: {len(all_lines)}")
            for line in all_lines[:15]:
                text = line[1][0]
                conf = line[1][1]
                bbox = line[0]
                cy = int((bbox[0][1] + bbox[2][1]) / 2)
                print(f"    [{conf:.2f}] y={cy:4d} '{text}'")

        data = {
            'monsterName': '',
            'level': 25,
            'cost': None,
            'mainStat': None,
            'secondaryStat': None,
            'substats': [],
            'tuneLevel': 0,
        }

        import re

        # 收集各区域文本
        main_texts = []        # 主词条区域: [(x, text)]
        all_subs_lines = []    # 副属性+副词条区域
        zone_ranges = cfg.get('detail_zones', {
            'name': (110, 180),
            'level': (180, 250),
            'cost': (250, 370),
            'main': (445, 496),
            'all_subs': (496, 810),
        })

        for line in all_lines:
            bbox = line[0]
            text = line[1][0]
            conf = line[1][1]
            cx = int((bbox[0][0] + bbox[2][0]) / 2)
            cy = int((bbox[0][1] + bbox[2][1]) / 2)

            if conf < 0.6:
                continue

            # 名称区域 (y: 110-180, 实测中心y≈143)
            if zone_ranges['name'][0] <= cy <= zone_ranges['name'][1]:
                if len(text) >= 2 and not text.isdigit():
                    data['monsterName'] = text.strip()

            # 等级区域 (y: 180-250, 实测中心y≈213)
            elif zone_ranges['level'][0] <= cy <= zone_ranges['level'][1]:
                nums = re.findall(r'\d+', text)
                for n in nums:
                    v = int(n)
                    if 1 <= v <= 25:
                        data['level'] = v
                        break

            # Cost区域 (y: 250-370, 实测中心y≈264)
            elif zone_ranges['cost'][0] <= cy <= zone_ranges['cost'][1]:
                if 'COST' in text.upper():
                    nums = re.findall(r'\d+', text)
                    for n in nums:
                        if int(n) in (1, 3, 4):
                            data['cost'] = int(n)
                            break
                else:
                    nums = re.findall(r'\d+', text)
                    for n in nums:
                        if int(n) in (1, 3, 4) and data.get('cost') is None:
                            data['cost'] = int(n)

            # 主词条区域 (y: 445-496, 实测中心y≈474)
            elif zone_ranges['main'][0] <= cy <= zone_ranges['main'][1]:
                main_texts.append((cx, text.strip()))

            # 副属性+副词条统一收集 (y: 496-780)
            # 副属性+副词条统一收集 (y: 496-780)，记录(y, x, text)
            elif zone_ranges['all_subs'][0] <= cy <= zone_ranges['all_subs'][1]:
                all_subs_lines.append((cy, cx, text.strip()))

        # 主词条解析（按x排序合并）
        if main_texts:
            main_texts.sort(key=lambda it: it[0])
            main_combined = ' '.join(t for _, t in main_texts)
            stat = parse_stat_line(main_combined)
            if stat:
                data['mainStat'] = stat

        # Y 近邻聚类 + x排序合并
        all_subs_lines.sort(key=lambda x: x[0])
        groups = []  # [[items], max_y]，items: [(x, text)]
        row_merge_threshold = cfg.get('detail_row_merge_threshold', 20)
        for cy, cx, text in all_subs_lines:
            if groups and cy - groups[-1][1] <= row_merge_threshold:
                groups[-1][0].append((cx, text))
                groups[-1][1] = max(groups[-1][1], cy)
            else:
                groups.append([[(cx, text)], cy])

        # 解析每组：按x排序（属性名在左=x小，数值在右=x大）
        secondary_stat = None
        substats_collected = []
        for items, _ in groups:
            items.sort(key=lambda it: it[0])
            combined = ' '.join(t for _, t in items)
            stat = parse_stat_line(combined)
            if stat:
                if secondary_stat is None:
                    secondary_stat = stat
                else:
                    substats_collected.append(stat)

        data['secondaryStat'] = secondary_stat
        data['substats'] = substats_collected[:5]
        return data

    def _ocr_viewport2_sonata(self):
        """滚动后OCR右侧详情区，读取套装名称。"""
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]

        # 截取右侧详情区
        dx, dy, dw, dh = cfg['detail_area']
        detail_img = capture_region(gx + dx, gy + dy, dw, dh)

        if self.debug:
            detail_img.save(f'debug_output/detail_{self.scan_count}_vp2.png')

        ocr = get_ocr()
        img_array = np.array(detail_img)
        results = ocr.ocr(img_array, cls=True)
        all_lines = results[0] if results and results[0] else []

        if self.debug:
            print(f"  [debug] 视口2 OCR结果数: {len(all_lines)}")
            for line in all_lines[:10]:
                text = line[1][0]
                conf = line[1][1]
                print(f"    [{conf:.2f}] '{text}'")

        for line in all_lines:
            text = line[1][0]
            for cn_name, eng_key in SONATA_MAP.items():
                if cn_name in text:
                    return eng_key

        return None

    def _scroll_detail_down(self):
        """模拟在右侧详情区向下滚动。"""
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]
        sx, sy = cfg['detail_scroll_pos']

        # 用win32api在详情区中央发送滚轮事件
        mouse_scroll(gx + sx, gy + sy, cfg['detail_scroll_amount'])
