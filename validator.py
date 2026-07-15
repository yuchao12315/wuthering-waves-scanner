from .models import Echo

VALID_MAIN_STATS = {
    4: {'FLAT_ATK', 'ATK_PCT', 'HP_PCT', 'DEF_PCT', 'CRIT_RATE', 'CRIT_DMG', 'HEAL_BONUS'},
    3: {'FLAT_ATK', 'ATK_PCT', 'HP_PCT', 'DEF_PCT', 'ENERGY_REGEN', 'ELEM_DMG'},
    1: {'ATK_PCT', 'HP_PCT', 'DEF_PCT', 'FLAT_HP'},
}

STAT_RANGES = {
    'FLAT_ATK': (30, 200),
    'ATK_PCT': (6.0, 60.0),
    'FLAT_HP': (320, 2500),
    'HP_PCT': (6.0, 60.0),
    'FLAT_DEF': (30, 100),
    'DEF_PCT': (6.0, 50.0),
    'CRIT_RATE': (6.0, 25.0),
    'CRIT_DMG': (12.0, 50.0),
    'ENERGY_REGEN': (6.0, 35.0),
    'ELEM_DMG': (25.0, 35.0),
    'HEAL_BONUS': (20.0, 30.0),
    'NORMAL_ATK_DMG': (5.0, 15.0),
    'HEAVY_ATK_DMG': (5.0, 15.0),
    'RESONANCE_SKILL_DMG': (5.0, 15.0),
    'RESONANCE_LIBERATION_DMG': (5.0, 15.0),
}


def validate_echo(echo):
    """Validate an echo's data. Returns list of issues (empty = valid)."""
    issues = []

    # Cost validation
    if echo.cost not in (1, 3, 4):
        issues.append(f"非法Cost值: {echo.cost}")

    # Main stat type validation
    if echo.cost in VALID_MAIN_STATS:
        if echo.mainStat and echo.mainStat.get('type') not in VALID_MAIN_STATS[echo.cost]:
            issues.append(f"Cost{echo.cost}不能有主词条{echo.mainStat.get('type')}")

    # Main stat value range
    if echo.mainStat:
        stat_type = echo.mainStat.get('type')
        value = echo.mainStat.get('value')
        if stat_type in STAT_RANGES and value is not None:
            lo, hi = STAT_RANGES[stat_type]
            if not (lo * 0.8 <= value <= hi * 1.2):  # 20% tolerance for OCR errors
                issues.append(f"主词条{stat_type}值{value}超出范围[{lo},{hi}]")

    # Substat count vs tune level
    expected_substats = echo.tuneLevel + 1 if echo.tuneLevel else None
    if expected_substats and len(echo.substats) != expected_substats:
        issues.append(f"调谐等级{echo.tuneLevel}应有{expected_substats}条副词条，实际{len(echo.substats)}条")

    # Substat value ranges
    for sub in echo.substats:
        stat_type = sub.get('type')
        value = sub.get('value')
        if stat_type in STAT_RANGES and value is not None:
            lo, hi = STAT_RANGES[stat_type]
            # Substats have smaller ranges than main stats
            sub_hi = hi * 0.5
            if value > sub_hi * 1.5:  # generous tolerance
                issues.append(f"副词条{stat_type}值{value}疑似异常")

    return issues
