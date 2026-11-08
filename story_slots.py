"""기존 스토리를 보존하는 독립 파일 슬롯. 기존 파일은 재사용/초기화하지 않습니다."""
from pathlib import Path
import json
import re
import sqlite3

from database import STORY_DB_PATH


class StorySlots:
    pattern = re.compile(r'aidc_story_slot_([0-9]+)\.db')

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else STORY_DB_PATH.parent
        self.directory = self.directory.resolve()
        self.legacy_path = self.directory / STORY_DB_PATH.name

    def available(self):
        paths = [p for p in self.directory.glob('aidc_story_slot_*.db')
                 if p.is_file() and self.pattern.fullmatch(p.name)]
        paths.sort(key=lambda p: int(self.pattern.fullmatch(p.name)[1]))
        if self.legacy_path.is_file():
            paths.insert(0, self.legacy_path)
        return paths

    def reserve_new(self):
        """독점 생성으로 연속 클릭이나 별도 프로세스에서도 기존 파일을 덮어쓰지 않습니다."""
        number = max((int(self.pattern.fullmatch(p.name)[1]) for p in self.available()
                      if self.pattern.fullmatch(p.name)), default=0) + 1
        while True:
            path = self.directory / f'aidc_story_slot_{number:03d}.db'
            try:
                with path.open('xb'):
                    pass
            except FileExistsError:
                number += 1
            else:
                return path

    def describe(self, path):
        """슬롯의 진행 위치를 읽기 전용으로 확인합니다. 파일을 수정하거나 잠금을 잡지 않으며 실패하면 빈 문자열입니다."""
        try:
            connection = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=0.2)
            try:
                row = connection.execute('SELECT payload FROM simulation_state WHERE id=1').fetchone()
            finally:
                connection.close()
            if row is None:
                return ' · 시작 전'
            story = json.loads(row[0]).get('story')
            if not isinstance(story, dict):
                return ''
            chapter2 = story.get('chapter2') if isinstance(story.get('chapter2'), dict) else None
            done2 = bool(chapter2) and len(chapter2.get('completed_steps', [])) >= 6
            if story.get('practice') is True:
                return ' · Chapter 2 연습 '+('완료' if done2 else '진행 중')
            if chapter2:
                return ' · Chapter 2 '+('완료' if done2 else '진행 중')
            return ' · Chapter 1 '+('완료' if story.get('chapter_completed') else '진행 중')
        except Exception:
            return ''

    def title(self, path):
        match = self.pattern.fullmatch(Path(path).name)
        return (f'새 스토리 {int(match[1])}' if match else '기존 스토리') + f' · {Path(path).name}'
