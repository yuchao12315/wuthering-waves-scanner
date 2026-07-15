import json
import os
from datetime import datetime

LIVE_FILE = 'echoes_live.json'


class LiveExporter:
    """实时导出器 — 每识别一个声骸立即写入JSON文件。"""

    def __init__(self, output_dir='.'):
        self.output_dir = output_dir
        self.filepath = os.path.join(output_dir, LIVE_FILE)
        self.echoes = []
        self._init_file()

    def _init_file(self):
        data = {
            'echoes': [],
            'exportedAt': datetime.now().isoformat(),
            'version': '1.0',
            'source': 'wuwa-echo-scanner',
            'status': 'scanning',
        }
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add(self, echo):
        """添加一个声骸并立即写入文件。"""
        self.echoes.append(echo)
        self._write()

    def _write(self):
        data = {
            'echoes': [e.to_dict() for e in self.echoes],
            'exportedAt': datetime.now().isoformat(),
            'version': '1.0',
            'source': 'wuwa-echo-scanner',
            'status': 'scanning',
            'count': len(self.echoes),
        }
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def finalize(self):
        """扫描完成，标记状态并生成最终带时间戳的文件。"""
        data = {
            'echoes': [e.to_dict() for e in self.echoes],
            'exportedAt': datetime.now().isoformat(),
            'version': '1.0',
            'source': 'wuwa-echo-scanner',
            'status': 'complete',
            'count': len(self.echoes),
        }
        # 写入实时文件
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 同时生成带时间戳的最终文件
        final_name = f"echoes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        final_path = os.path.join(self.output_dir, final_name)
        with open(final_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"✓ 已导出 {len(self.echoes)} 个声骸")
        print(f"  实时文件: {self.filepath}")
        print(f"  最终文件: {final_path}")
        return final_path
