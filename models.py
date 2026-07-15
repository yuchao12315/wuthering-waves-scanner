import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Echo:
    monsterId: str = ''
    monsterName: str = ''
    cost: int = 1
    rarity: int = 5
    level: int = 25
    tuneLevel: int = 0
    sonata: str = ''
    mainStat: Optional[Dict] = None
    secondaryStat: Optional[Dict] = None
    substats: List[Dict] = field(default_factory=list)
    id: str = ''
    validation_issues: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = self._generate_id()

    def _generate_id(self) -> str:
        """Generate a unique ID via SHA256 hash of key fields."""
        main_type = self.mainStat.get('type', '') if self.mainStat else ''
        main_value = str(self.mainStat.get('value', '')) if self.mainStat else ''
        sorted_subs = sorted(
            [(s.get('type', ''), str(s.get('value', ''))) for s in self.substats]
        )
        raw = f"{self.monsterId}{main_type}{main_value}{''.join(t + v for t, v in sorted_subs)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict:
        """JSON-serializable dict matching the web app's Echo type."""
        return {
            'id': self.id,
            'monsterId': self.monsterId,
            'monsterName': self.monsterName,
            'cost': self.cost,
            'rarity': self.rarity,
            'level': self.level,
            'tuneLevel': self.tuneLevel,
            'sonata': self.sonata,
            'mainStat': self.mainStat,
            'secondaryStat': self.secondaryStat,
            'substats': self.substats,
        }

    @classmethod
    def from_ocr_data(cls, data: Dict) -> 'Echo':
        """Create Echo from OCR-extracted data dict."""
        echo = cls(
            monsterId=data.get('monsterId', data.get('monsterName', '')),
            monsterName=data.get('monsterName', ''),
            cost=data.get('cost', 1) or 1,
            rarity=data.get('rarity', 5),
            level=data.get('level', 25),
            tuneLevel=data.get('tuneLevel', 0),
            sonata=data.get('sonata', '') or '',
            mainStat=data.get('mainStat'),
            secondaryStat=data.get('secondaryStat'),
            substats=data.get('substats', []),
        )
        echo.id = echo._generate_id()
        return echo

    @classmethod
    def from_dict(cls, data: Dict) -> 'Echo':
        """Create Echo from a previously serialized dict."""
        echo = cls(
            id=data.get('id', ''),
            monsterId=data.get('monsterId', ''),
            monsterName=data.get('monsterName', ''),
            cost=data.get('cost', 1),
            rarity=data.get('rarity', 5),
            level=data.get('level', 25),
            tuneLevel=data.get('tuneLevel', 0),
            sonata=data.get('sonata', ''),
            mainStat=data.get('mainStat'),
            secondaryStat=data.get('secondaryStat'),
            substats=data.get('substats', []),
        )
        return echo
