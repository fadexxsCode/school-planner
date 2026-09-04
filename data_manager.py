import os
import json
from datetime import datetime, timedelta

class DataManager:
    def __init__(self, app_name="SchoolPlanner"):
        appdata_path = os.getenv('LOCALAPPDATA') or os.path.expanduser('~')
        self.config_dir = os.path.join(appdata_path, app_name)
        
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
            
        self.json_path = os.path.join(self.config_dir, 'data.json')
        self.data = self._load_data()
        self._prune_old_data()

    def _get_default_structure(self):
        return {
            "schedule": {
                "Понеділок": [],
                "Вівторок": [],
                "Середа": [],
                "Четвер": [],
                "П'ятниця": [],
                "Субота": [],
                "Неділя": []
            },
            "homework": [],
            "subject_weights": {}
        }

    def _load_data(self):
        if not os.path.exists(self.json_path):
            default_data = self._get_default_structure()
            self.save_data(default_data)
            return default_data
        
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return self._get_default_structure()

    def _prune_old_data(self):
        """Авто-очистка выполненных задач старше 14 дней"""
        homeworks = self.data.get("homework", [])
        today = datetime.now().date()
        two_weeks_ago = today - timedelta(days=14)

        filtered_hw = []
        for item in homeworks:
            try:
                task_date = datetime.strptime(item["deadline"], "%d.%m.%Y").date()
                if task_date >= two_weeks_ago:
                    filtered_hw.append(item)
            except ValueError:
                filtered_hw.append(item)

        self.data["homework"] = filtered_hw
        self.save_data()

    def save_data(self, data=None):
        if data is not None:
            self.data = data
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)

    def get_all_subjects(self) -> list:
        """Возвращает строго УНИКАЛЬНЫЙ список всех предметов без повторов"""
        subjects = set()
        for day, lessons in self.data.get("schedule", {}).items():
            for lesson in lessons:
                if isinstance(lesson, str) and lesson.strip():
                    # Приводим к единому регистру для исключения дублей вроде "Физика" и "физика"
                    clean_subject = lesson.strip().capitalize()
                    subjects.add(clean_subject)
        
        return sorted(list(subjects)) if subjects else ["Загальне"]

    def get_homework(self):
        return self.data.get("homework", [])

    def save_homework(self, hw_list):
        self.data["homework"] = hw_list
        self.save_data()

    def get_schedule(self):
        return self.data.get("schedule", {})

    def save_schedule(self, schedule_dict):
        self.data["schedule"] = schedule_dict
        self.save_data()