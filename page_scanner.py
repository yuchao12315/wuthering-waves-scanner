"""
单遍扫描器 — 逐页扫描，每页内：
1. OCR列表区找出满级(+25)卡片位置
2. 逐个点击满级卡片，OCR右侧详情区读取属性
3. 当前页处理完后滚动到下一页
4. 一整页都没有满级卡片时停止

合并了原来的阶段一和阶段二，避免滚回顶部重新定位。
"""
import os
import re
import time
import numpy as np
from .screen_capture import capture_region, images_similar
from .ocr_engine import get_ocr, ocr_image, ocr_region_text, extract_number, merge_split_level_markers
from .input_control import click as mouse_click, scroll as mouse_scroll
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
    # 清理OCR噪声前缀
    noise_prefixes = ['艾', '袋', '众', '必', 'X', '文']
    cleaned = text.strip()
    for prefix in noise_prefixes:
        if cleaned.startswith(prefix) and len(cleaned) > len(prefix):
            rest = cleaned[len(prefix):]
            if rest and rest[0] in '攻生防暴共普重治':
                cleaned = rest
                break

    is_pct = '%' in cleaned or '％' in cleaned

    # 优先处理攻击/生命/防御（需要根据%区分FLAT和PCT）
    # 必须在STAT_TYPE_MAP匹配之前，否则会被 '攻击'→FLAT_ATK 优先命中
    if '攻击' in cleaned:
        return 'ATK_PCT' if is_pct else 'FLAT_ATK'
    if '生命' in cleaned:
        return 'HP_PCT' if is_pct else 'FLAT_HP'
    if '防御' in cleaned:
        return 'DEF_PCT' if is_pct else 'FLAT_DEF'

    # 暴击（不含'伤害'不含'率'）→ CRIT_RATE
    if '暴击' in cleaned and '伤害' not in cleaned:
        return 'CRIT_RATE'

    # 其他词条用STAT_TYPE_MAP匹配
    for key, stype in STAT_TYPE_MAP.items():
        if key in cleaned:
            return stype

    return None


def parse_stat_line(text):
    """解析合并后的词条文本为 {type, value}。对FLAT类型做二次修正。"""
    stat_type = classify_stat(text)
    value = extract_number(text)
    if stat_type and value is not None:
        # 二次修正：classify_stat可能在无%时返回FLAT，但数值是小数<100（百分比）
        if value < 100 and '.' in text:
            if stat_type == 'FLAT_ATK':
                stat_type = 'ATK_PCT'
            elif stat_type == 'FLAT_HP':
                stat_type = 'HP_PCT'
            elif stat_type == 'FLAT_DEF':
                stat_type = 'DEF_PCT'
        return {'type': stat_type, 'value': value}
    return None


class PageScanner:
    def __init__(self, game_rect, debug=False):
        self.game_rect = game_rect
        gx, gy, gw, gh = game_rect
        self.config = get_config((gw, gh))
        self.debug = debug
        self.echo_count = 0

    def scan_all(self, progress_callback=None, on_echo=None):
        """
        逐页扫描，返回所有识别到的Echo列表。
        progress_callback(page, total_echoes): 进度回调
        on_echo(echo): 每识别到一个echo时的回调（用于实时保存进度）
        """
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]
        grid_ox, grid_oy = cfg['card_grid_origin']
        card_w = cfg['card_width']
        card_h = cfg['card_height']
        cols = cfg['card_cols']
        rows = cfg['card_rows']

        echoes = []
        scanned_ids = set()
        page_idx = 0
        no_scroll_count = 0
        consecutive_non25 = 0  # 连续非25级卡片数
        prev_screenshot = None

        while no_scroll_count < 3:
            # 截取列表区域（用于滚动检测）
            lx, ly, lw, lh = cfg['list_region']
            screenshot = capture_region(gx + lx, gy + ly, lw, lh)

            if prev_screenshot and images_similar(prev_screenshot, screenshot):
                no_scroll_count += 1
                if self.debug:
                    print(f"  [debug] 页面未变化 ({no_scroll_count}/3)")
                prev_screenshot = screenshot
                page_idx += 1
                self._scroll_list()
                time.sleep(TIMING['scroll_wait'])
                continue

            no_scroll_count = 0

            if self.debug:
                os.makedirs('debug_output', exist_ok=True)
                screenshot.save(f'debug_output/page_{page_idx}.png')
                print(f"\n  [debug] === 第{page_idx}页：逐卡片点击 ===")

            # 逐个点击当前页所有卡片位置
            # 优化：先快速点击第一列判断该行是否已扫过（重复检测），
            # 如果该行第一个就是重复的则整行跳过
            page_new = 0
            page_skip = 0
            should_stop = False

            for row in range(rows):
                if should_stop:
                    break

                # 快速检测：点击该行第一个卡片，看是否重复
                first_click_x = gx + grid_ox + 0 * card_w + card_w // 2
                first_click_y = gy + grid_oy + row * card_h + card_h // 2
                first_echo = self._scan_card_detail({'click_pos': (first_click_x, first_click_y)})

                if first_echo is None:
                    # 非满级
                    consecutive_non25 += 1
                    page_skip += 1
                    if self.debug:
                        print(f"  [debug] 行{row}首卡非满级 (连续{consecutive_non25}个)")
                    if consecutive_non25 >= 10:
                        should_stop = True
                    continue
                elif first_echo.id in scanned_ids:
                    # 该行第一个卡片是重复的 → 整行都是旧的，跳过
                    if self.debug:
                        print(f"  [debug] 行{row}首卡重复(id={first_echo.id})，跳过整行")
                    page_skip += cols
                    continue
                else:
                    # 新卡片，记录并继续扫该行剩余卡片
                    consecutive_non25 = 0
                    scanned_ids.add(first_echo.id)
                    echoes.append(first_echo)
                    page_new += 1
                    if on_echo:
                        on_echo(first_echo)

                # 扫该行剩余列（col 1~5）
                for col in range(1, cols):
                    if should_stop:
                        break

                    click_x = gx + grid_ox + col * card_w + card_w // 2
                    click_y = gy + grid_oy + row * card_h + card_h // 2

                    echo = self._scan_card_detail({'click_pos': (click_x, click_y)})

                    if echo is None:
                        consecutive_non25 += 1
                        page_skip += 1
                        if self.debug:
                            print(f"  [debug] 卡[{row},{col}] 非满级 (连续{consecutive_non25}个)")
                        if consecutive_non25 >= 10:
                            should_stop = True
                    else:
                        consecutive_non25 = 0
                        if echo.id in scanned_ids:
                            if self.debug:
                                print(f"  [debug] 卡[{row},{col}] 重复")
                            continue
                        scanned_ids.add(echo.id)
                        echoes.append(echo)
                        page_new += 1
                        if on_echo:
                            on_echo(echo)

                    if progress_callback:
                        progress_callback(page_idx, len(echoes))

                if progress_callback:
                    progress_callback(page_idx, len(echoes))

            if self.debug:
                print(f"  [debug] 页{page_idx}: 新增{page_new}个, 跳过{page_skip}个非满级")

            if should_stop:
                print(f"\n  连续{consecutive_non25}个非满级声骸，停止扫描")
                break

            prev_screenshot = screenshot
            page_idx += 1
            self._scroll_list()
            time.sleep(TIMING['scroll_wait'])

        print(f"\n扫描完成: 共扫描{page_idx+1}页，识别{len(echoes)}个满级声骸（去重后）")
        return echoes

    def _find_max_level_cards(self, page_idx, list_img):
        """OCR列表区域，找出所有等级为25的卡片及其点击坐标。"""
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]
        grid_ox, grid_oy = cfg['card_grid_origin']
        card_w = cfg['card_width']
        card_h = cfg['card_height']
        cols = cfg['card_cols']
        rows = cfg['card_rows']

        if self.debug:
            os.makedirs('debug_output', exist_ok=True)
            list_img.save(f'debug_output/page_{page_idx}.png')

        ocr = get_ocr()
        img_array = np.array(list_img)
        results = ocr.ocr(img_array, cls=True)
        all_lines = results[0] if results and results[0] else []

        # 合并被OCR拆分的 '+' 和 '25'
        all_lines = merge_split_level_markers(all_lines)

        if self.debug:
            print(f"  [debug] 页{page_idx} OCR结果数: {len(all_lines)}")
            for line in all_lines[:20]:
                text = line[1][0]
                conf = line[1][1]
                bbox = line[0]
                cx = int((bbox[0][0] + bbox[2][0]) / 2)
                cy = int((bbox[0][1] + bbox[2][1]) / 2)
                print(f"    [{conf:.2f}] ({cx:4d},{cy:4d}) '{text}'")

        cards = []
        found_set = set()

        for line in all_lines:
            bbox = line[0]
            text = line[1][0]

            # 找包含数字25的短文本
            nums = re.findall(r'\d+', text)
            is_level_25 = False
            for n in nums:
                if int(n) == 25:
                    is_level_25 = True
                    break
            if not is_level_25:
                continue
            if len(text) > 6:
                continue

            # 根据bbox坐标确定所属卡片
            cx = (bbox[0][0] + bbox[2][0]) / 2
            cy = (bbox[0][1] + bbox[2][1]) / 2
            col = int(cx // card_w)
            row = int(cy // card_h)
            if col >= cols or row >= rows:
                continue

            key = (row, col)
            if key in found_set:
                continue
            found_set.add(key)

            click_x = gx + grid_ox + col * card_w + card_w // 2
            click_y = gy + grid_oy + row * card_h + card_h // 2

            cards.append({
                'row': row, 'col': col,
                'click_pos': (click_x, click_y),
            })

            if self.debug:
                print(f"  [debug] → 满级卡片[{row},{col}] 点击({click_x},{click_y})")

        return cards

    def _scan_card_detail(self, card_info):
        """点击一张卡片，OCR右侧详情区，返回Echo或None。"""
        self.echo_count += 1
        click_x, click_y = card_info['click_pos']

        if self.debug:
            print(f"\n  [debug] === 声骸#{self.echo_count} 点击({click_x},{click_y}) ===")

        best_data = None

        for retry in range(3):
            if retry > 0 and self.debug:
                print(f"  [debug] --- 第{retry+1}次重试 ---")

            # 1. 详情区滚回顶部
            self._focus_and_reset_detail()
            time.sleep(0.3)

            # 2. 点击卡片
            mouse_click(click_x, click_y)
            time.sleep(0.8)

            # 3. 确保详情区在顶部
            self._focus_and_reset_detail()
            time.sleep(0.8)

            # 4. OCR视口1 — 词条信息（等待详情区完全渲染）
            data = self._ocr_detail_viewport1()

            if self.debug:
                print(f"  [debug] 视口1: name='{data.get('monsterName')}' cost={data.get('cost')} "
                      f"main={data.get('mainStat')} sec={data.get('secondaryStat')} "
                      f"subs={len(data.get('substats', []))}")

            # 4b. 等级校验：详情区等级必须是25才继续
            detail_level = data.get('level', 0)
            if detail_level != 25:
                if detail_level != 0:
                    if self.debug:
                        print(f"  [debug] 详情区等级={detail_level}≠25，跳过")
                    # 滚回顶部再返回
                    self._focus_and_reset_detail()
                    return None
                # level=0 表示未识别到等级，继续尝试（可能OCR漏了）

            # 5. 逐步滚动详情区搜索套装名称
            sonata = None
            for scroll_round in range(4):
                self._scroll_detail_down()
                time.sleep(0.4)
                sonata = self._ocr_detail_viewport2_sonata()
                if sonata:
                    if self.debug:
                        print(f"  [debug] 视口2: 第{scroll_round+1}轮滚动找到套装={sonata}")
                    break
                if self.debug:
                    print(f"  [debug] 视口2: 第{scroll_round+1}轮滚动未找到套装")
            data['sonata'] = sonata

            # 6. 详情区滚回顶部
            self._focus_and_reset_detail()
            time.sleep(0.2)

            # 7. 合并多次尝试的结果
            if best_data is None:
                best_data = data
            else:
                best_data = self._merge_data(best_data, data)

            # 8. 检查所有必需字段
            missing = self._check_data_complete(best_data)
            if not missing:
                if self.debug:
                    print(f"  [debug] ✓ 所有字段完整")
                break
            if self.debug:
                print(f"  [debug] 缺失: {missing}")

        # 最终检查
        missing = self._check_data_complete(best_data) if best_data else ['全部']
        if self.debug and missing:
            print(f"  [debug] ⚠ 最终缺失: {missing}")

        try:
            echo = Echo.from_ocr_data(best_data)
            issues = validate_echo(echo)
            for m in missing:
                issues.append(f'{m}未识别')
            if issues:
                echo.validation_issues = issues
            return echo
        except Exception as e:
            if self.debug:
                print(f"  [debug] 构建Echo失败: {e}")
            return None

    def _merge_data(self, old, new):
        """合并两次OCR结果，优先取有值的字段。"""
        merged = dict(old)
        if not merged.get('monsterName') and new.get('monsterName'):
            merged['monsterName'] = new['monsterName']
        if merged.get('cost') is None and new.get('cost') is not None:
            merged['cost'] = new['cost']
        if merged.get('mainStat') is None and new.get('mainStat') is not None:
            merged['mainStat'] = new['mainStat']
        if merged.get('secondaryStat') is None and new.get('secondaryStat') is not None:
            merged['secondaryStat'] = new['secondaryStat']
        if not merged.get('substats') and new.get('substats'):
            merged['substats'] = new['substats']
        if not merged.get('sonata') and new.get('sonata'):
            merged['sonata'] = new['sonata']
        return merged

    def _clean_ocr_text(self, text):
        """清理OCR常见噪声前缀/后缀。"""
        # 常见OCR误识别的前缀字符
        noise_prefixes = ['艾', '袋', '众', '必', 'X', '我X', '我']
        cleaned = text.strip()
        for prefix in noise_prefixes:
            if cleaned.startswith(prefix) and len(cleaned) > len(prefix):
                rest = cleaned[len(prefix):]
                # 只有后面跟着有意义的中文才去掉前缀
                if rest and rest[0] in '攻生防暴共普重治':
                    cleaned = rest
                    break
        return cleaned

    def _check_data_complete(self, data):
        """检查所有必需字段是否完整。全部拿到才算完整。"""
        missing = []
        if not data.get('monsterName'):
            missing.append('名称')
        if data.get('cost') is None:
            missing.append('Cost')
        if data.get('mainStat') is None:
            missing.append('主词条')
        if data.get('secondaryStat') is None:
            missing.append('副属性')
        subs = data.get('substats', [])
        if len(subs) == 0:
            missing.append('副词条')
        if not data.get('sonata'):
            missing.append('套装')
        return missing

    def _focus_and_reset_detail(self):
        """
        点击详情区激活焦点，然后向上滚动回顶部。
        每次滚动间隔足够让游戏处理消息。
        """
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]
        sx, sy = cfg['detail_scroll_pos']
        steps = cfg.get('detail_scroll_up_steps', 20)

        # 点击详情区中央激活焦点
        mouse_click(gx + sx, gy + sy)
        time.sleep(0.15)

        # 向上滚动回顶部
        for _ in range(steps):
            mouse_scroll(gx + sx, gy + sy, 1)
            time.sleep(0.03)

    def _ocr_detail_viewport1(self):
        """截取整个右侧详情区做OCR，按y坐标分配字段。"""
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]
        dx, dy, dw, dh = cfg['detail_area']
        detail_img = capture_region(gx + dx, gy + dy, dw, dh)

        if self.debug:
            os.makedirs('debug_output', exist_ok=True)
            detail_img.save(f'debug_output/detail_{self.echo_count}_vp1.png')

        ocr = get_ocr()
        img_array = np.array(detail_img)
        results = ocr.ocr(img_array, cls=True)
        all_lines = results[0] if results and results[0] else []

        if self.debug:
            print(f"  [debug] 详情区OCR: {len(all_lines)}条")
            for line in all_lines[:15]:
                text = line[1][0]
                conf = line[1][1]
                cy = int((line[0][0][1] + line[0][2][1]) / 2)
                print(f"    [{conf:.2f}] y={cy:4d} '{text}'")

        data = {
            'monsterName': '', 'level': 25, 'cost': None,
            'mainStat': None, 'secondaryStat': None,
            'substats': [], 'tuneLevel': 0,
        }

        # Y坐标区间配置（基于calibrate实测日志）：
        #   y≈65:  导航栏数字（忽略）
        #   y≈143: 声骸名称
        #   y≈213: 等级(+25)
        #   y≈264: Cost(COST 4)
        #   y≈371: 图标(Z, 忽略)
        #   y≈473-474: 主词条(暴击伤害 44.0%)
        #   y≈518-519: 副属性(攻击 150)
        #   y≈563-743: 副词条1-5（间距~45px）
        #
        # name/level/cost/main 用固定zone，副属性+副词条合并为 all_subs 大区
        # 用 Y 近邻聚类(20px)自动分行，不依赖精确的 zone 边界
        # secondary + sub1~sub5 合并为一个 all_subs 大区:
        #   - 消除 secondary/sub1 边界不精确导致副词条被误分配为副属性的问题
        #   - 消除 sub5 zone 上界过紧导致最后一条副词条丢失的问题
        #   - 用 Y 近邻聚类自动分行，不依赖固定的 sub1~sub5 zone 边界
        zone_ranges = self.config.get('detail_zones', {
            'name': (110, 180),
            'level': (180, 250),
            'cost': (250, 370),
            'main': (445, 496),
            'all_subs': (496, 810),
        })
        zones = {
            name: (bounds[0], bounds[1], [])
            for name, bounds in zone_ranges.items()
        }

        for line in all_lines:
            bbox = line[0]
            text = line[1][0]
            conf = line[1][1]
            cx = int((bbox[0][0] + bbox[2][0]) / 2)
            cy = int((bbox[0][1] + bbox[2][1]) / 2)
            if conf < 0.6:
                continue
            clean_text = self._clean_ocr_text(text)
            for zone_name, (y_min, y_max, texts) in zones.items():
                if y_min <= cy <= y_max:
                    texts.append((cx, clean_text))
                    break

        # 解析各区间（zone存的是 (x, text) 元组列表）
        # 名称
        for _, t in zones['name'][2]:
            if len(t) >= 2 and not t.isdigit():
                data['monsterName'] = t
                break

        # 等级
        for _, t in zones['level'][2]:
            nums = re.findall(r'\d+', t)
            for n in nums:
                val = int(n)
                if 1 <= val <= 25:
                    data['level'] = val
                    break

        # Cost
        all_cost_text = ' '.join(t for _, t in zones['cost'][2])
        if 'COST' in all_cost_text.upper():
            nums = re.findall(r'\d+', all_cost_text)
            for n in nums:
                if int(n) in (1, 3, 4):
                    data['cost'] = int(n)
                    break

        # 主词条（按x排序合并：属性名在左，数值在右）
        main_items = sorted(zones['main'][2], key=lambda it: it[0])
        main_text = ' '.join(t for _, t in main_items)
        if main_text:
            stat = parse_stat_line(main_text)
            if stat:
                data['mainStat'] = stat

        # 副属性 + 副词条 — 从 all_subs 大区用 Y 近邻聚类自动分行
        # 收集时记录 (y, x, text)，合并时按x排序保证属性名在前数值在后
        all_subs_lines = []  # [(y, x, text)]
        for line in all_lines:
            bbox = line[0]
            text = line[1][0]
            conf = line[1][1]
            cx = int((bbox[0][0] + bbox[2][0]) / 2)
            cy = int((bbox[0][1] + bbox[2][1]) / 2)
            if conf < 0.6:
                continue
            y_min, y_max = zones['all_subs'][0], zones['all_subs'][1]
            if y_min <= cy <= y_max:
                clean_text = self._clean_ocr_text(text)
                all_subs_lines.append((cy, cx, clean_text))

        # 按 Y 排序
        all_subs_lines.sort(key=lambda x: x[0])

        # Y 近邻聚类：同一行的属性名(左)和数值(右)y相近但x不同
        # 1080p 下 20px 阈值 < 行间距(~45px)的一半；其他分辨率按高度缩放。
        # groups: [[items], max_y]，items: [(x, text)]
        groups = []
        row_merge_threshold = self.config.get('detail_row_merge_threshold', 20)
        for cy, cx, text in all_subs_lines:
            if groups and cy - groups[-1][1] <= row_merge_threshold:
                groups[-1][0].append((cx, text))
                groups[-1][1] = max(groups[-1][1], cy)
            else:
                groups.append([[(cx, text)], cy])

        # 解析每组：按x排序合并（左边属性名 + 右边数值）
        secondary_stat = None
        substats_collected = []
        for items, _ in groups:
            # 按x排序：属性名(x小)在前，数值(x大)在后
            items.sort(key=lambda it: it[0])
            combined = ' '.join(t for _, t in items)
            stat = parse_stat_line(combined)
            if stat:
                if secondary_stat is None:
                    secondary_stat = stat
                else:
                    substats_collected.append(stat)

        data['secondaryStat'] = secondary_stat
        data['substats'] = substats_collected
        return data

    def _ocr_detail_viewport2_sonata(self):
        """滚动后OCR详情区，搜索套装名称。

        搜索策略:
        1. 直接匹配已知套装名称（SONATA_MAP）
        2. 如果没匹配到，找"合鸣效果"标题，其下一行文本就是套装名称
        """
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]
        dx, dy, dw, dh = cfg['detail_area']
        detail_img = capture_region(gx + dx, gy + dy, dw, dh)

        if self.debug:
            os.makedirs('debug_output', exist_ok=True)
            detail_img.save(f'debug_output/detail_{self.echo_count}_vp2.png')

        ocr = get_ocr()
        img_array = np.array(detail_img)
        results = ocr.ocr(img_array, cls=True)
        all_lines = results[0] if results and results[0] else []

        if self.debug:
            print(f"  [debug] 视口2 OCR: {len(all_lines)}条")
            for line in all_lines[:10]:
                cy = int((line[0][0][1] + line[0][2][1]) / 2)
                print(f"    [{line[1][1]:.2f}] y={cy} '{line[1][0]}'")

        # 按y坐标排序
        sorted_lines = sorted(all_lines, key=lambda l: (l[0][0][1] + l[0][2][1]) / 2)

        # 策略1: 直接匹配已知套装名称
        for line in sorted_lines:
            text = line[1][0]
            for cn_name, eng_key in SONATA_MAP.items():
                if cn_name in text:
                    return eng_key

        # 策略2: 找"合鸣效果"标题，取其下一行文本作为套装名称
        for i, line in enumerate(sorted_lines):
            text = line[1][0]
            if '合鸣效果' in text or '合鸣' in text:
                # 下一行就是套装名称
                if i + 1 < len(sorted_lines):
                    next_text = sorted_lines[i + 1][1][0].strip()
                    if len(next_text) >= 2 and not next_text.isdigit():
                        # 尝试在SONATA_MAP中匹配
                        for cn_name, eng_key in SONATA_MAP.items():
                            if cn_name in next_text:
                                return eng_key
                        # 没匹配到已知套装，用原文作为套装名（可能是新套装）
                        if self.debug:
                            print(f"  [debug] 合鸣效果下方未知套装: '{next_text}'")
                        return next_text

        return None

    def _scroll_list(self):
        """
        滚动声骸列表区。
        策略：多次小滚动（每次list_scroll_amount步），滚完后等待页面稳定。
        调用方通过 images_similar 检测是否真的滚动了，没变则再滚。
        小步滚动避免跳过卡片行。
        """
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]
        sx, sy = cfg['list_scroll_pos']
        amount = cfg['list_scroll_amount']
        # 点击列表区中央确保焦点
        mouse_click(gx + sx, gy + sy)
        time.sleep(0.1)
        # 逐步发送滚轮，每步间隔让游戏处理
        steps = abs(amount)
        sign = -1 if amount < 0 else 1
        for _ in range(steps):
            mouse_scroll(gx + sx, gy + sy, sign)
            time.sleep(0.03)

    def _scroll_detail_down(self):
        """向下滚动右侧详情区约500px（需滚过技能描述才能看到套装）。"""
        cfg = self.config
        gx, gy = self.game_rect[0], self.game_rect[1]
        sx, sy = cfg['detail_scroll_pos']
        steps = cfg.get('detail_scroll_down_steps', 15)
        # 先点击详情区确保焦点
        mouse_click(gx + sx, gy + sy)
        time.sleep(0.1)
        for _ in range(steps):
            mouse_scroll(gx + sx, gy + sy, -1)
            time.sleep(0.03)
