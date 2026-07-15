import json
import os

PROGRESS_FILE = 'scan_progress.json'


class ScanProgress:
    def __init__(self, progress_dir='.'):
        self.filepath = os.path.join(progress_dir, PROGRESS_FILE)
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        return json.loads(content)
            except (json.JSONDecodeError, ValueError):
                pass
        return {'phase': None, 'scanned_echoes': [], 'max_level_positions': [], 'completed': False}

    def save(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def add_echo(self, echo_dict):
        if 'scanned_echoes' not in self.data:
            self.data['scanned_echoes'] = []
        self.data['scanned_echoes'].append(echo_dict)
        self.save()

    def set_phase(self, phase):
        self.data['phase'] = phase
        self.save()

    def set_positions(self, positions):
        self.data['max_level_positions'] = positions
        self.save()

    def mark_complete(self):
        self.data['completed'] = True
        self.save()

    def has_incomplete(self):
        return os.path.exists(self.filepath) and not self.data.get('completed', False)

    def get_scanned_count(self):
        return len(self.data.get('scanned_echoes', []))

    def reset(self):
        self.data = {'phase': None, 'scanned_echoes': [], 'max_level_positions': [], 'completed': False}
        if os.path.exists(self.filepath):
            os.remove(self.filepath)
