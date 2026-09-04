import os
import json
import re
import difflib
from datetime import datetime, timedelta

# Канонічні назви предметів і відомі варіанти написання, які варто вважати
# тим самим предметом (наприклад, "Англ мова" / "Англ. мова" / "Англійська").
# Ключ — канонічна назва, яка й зберігається та показується в списках.
SUBJECT_ALIASES = {
    "Англійська мова": ["англ мова", "англ", "англійська", "английский", "english"],
    "Українська мова": ["укр мова", "укр", "українська"],
    "Українська література": ["укр літ", "укр література"],
    "Зарубіжна література": ["зарубіжна літ", "світова література"],
    "Математика": ["матем"],
    "Алгебра": [],
    "Геометрія": [],
    "Фізика": [],
    # Фізична культура (урок) навмисно НЕ об'єднується з "Фізикою" — це різні предмети.
    "Фізична культура": ["фіз ра", "фізра", "фізкультура"],
    "Хімія": [],
    "Біологія": ["біол"],
    "Географія": ["геогр"],
    "Історія України": ["іст україни"],
    "Всесвітня історія": ["історія всесвітня"],
    "Правознавство": [],
    "Інформатика": ["інформ", "информатика"],
    "Мистецтво": ["музика", "образотворче мистецтво"],
    "Захист України": ["зу", "дпю"],
    "Підприємництво та фінансова грамотність": ["підприємництво"],
}


def _norm_key(text: str) -> str:
    """Приводить назву до 'ключового' вигляду для порівняння: без крапок,
    зайвих пробілів і регістру."""
    text = text.strip().lower().replace(".", "")
    return re.sub(r"\s+", " ", text)


def _build_alias_lookup() -> dict:
    lookup = {}
    for canonical, variants in SUBJECT_ALIASES.items():
        lookup[_norm_key(canonical)] = canonical
        for variant in variants:
            lookup[_norm_key(variant)] = canonical
    return lookup


_ALIAS_LOOKUP = _build_alias_lookup()

_UKRAINIAN_VOWELS = set("аеєиіїоуюя")


def _looks_like_abbreviation(cleaned: str) -> bool:
    """Коротке слово без голосних (ЗБД, ДПЮ) майже напевно є абревіатурою —
    для таких прийнято писати всі літери великими."""
    if " " in cleaned or not cleaned.isalpha() or len(cleaned) > 6:
        return False
    return not any(ch in _UKRAINIAN_VOWELS for ch in cleaned.lower())


def _format_unknown_subject(cleaned: str) -> str:
    """Уніфікує регістр для предмета, якого немає у словнику синонімів,
    щоб «ЗБД» і «Збд» (чи «труд» і «Труд») давали однаковий результат."""
    if _looks_like_abbreviation(cleaned):
        return cleaned.upper()
    return cleaned[:1].upper() + cleaned[1:].lower()


def normalize_subject_name(raw: str) -> str:
    """Приводить довільно введену назву предмета до єдиного канонічного
    варіанта (якщо він відомий), інакше — уніфікує регістр рядка так, щоб
    будь-яке написання того самого предмета давало однаковий результат."""
    if not isinstance(raw, str):
        return ""

    cleaned = re.sub(r"\s+", " ", raw.strip())
    if not cleaned:
        return ""

    key = _norm_key(cleaned)
    if key in _ALIAS_LOOKUP:
        return _ALIAS_LOOKUP[key]

    return _format_unknown_subject(cleaned)


def is_known_subject_alias(raw: str) -> bool:
    """True, якщо назва точно (з точністю до регістру/крапок/пробілів)
    відповідає одному з канонічних предметів або їхніх синонімів."""
    if not isinstance(raw, str) or not raw.strip():
        return False
    return _norm_key(raw) in _ALIAS_LOOKUP


def suggest_subject_correction(raw: str, known_subjects: list, cutoff: float = 0.72):
    """Шукає серед known_subjects назву, схожу на raw (ймовірна помилка
    введення), і повертає її. Повертає None, якщо raw вже точно збігається
    з одним із відомих варіантів або схожого варіанту не знайдено."""
    canonical = normalize_subject_name(raw)
    if not canonical:
        return None

    lowered_known = {s.lower(): s for s in known_subjects if isinstance(s, str) and s.strip()}
    if canonical.lower() in lowered_known:
        return None

    matches = difflib.get_close_matches(canonical.lower(), lowered_known.keys(), n=1, cutoff=cutoff)
    return lowered_known[matches[0]] if matches else None


def normalize_lesson_list(lessons: list) -> list:
    """Нормалізує назви уроків одного дня. Дублікати НЕ прибираються навмисно —
    здвоєні уроки (той самий предмет двічі підряд) є нормальною ситуацією."""
    result = []
    for lesson in lessons:
        canonical = normalize_subject_name(lesson)
        if canonical:
            result.append(canonical)
    return result


class DataManager:
    def __init__(self, app_name="SchoolPlanner"):
        appdata_path = os.getenv('LOCALAPPDATA') or os.path.expanduser('~')
        self.config_dir = os.path.join(appdata_path, app_name)
        
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
            
        self.json_path = os.path.join(self.config_dir, 'data.json')
        self.data = self._load_data()
        self._prune_old_data()
        self._normalize_existing_schedule()

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

    def _normalize_existing_schedule(self):
        """Приводить уже збережений розклад до нормалізованого вигляду —
        потрібно, щоб прибрати дублікати предметів, які накопичились
        у файлі до впровадження нормалізації."""
        schedule = self.data.get("schedule", {})
        normalized = {}
        changed = False

        for day, lessons in schedule.items():
            new_lessons = normalize_lesson_list(lessons)
            normalized[day] = new_lessons
            if new_lessons != lessons:
                changed = True

        self.data["schedule"] = normalized
        if changed:
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
                canonical = normalize_subject_name(lesson)
                if canonical:
                    subjects.add(canonical)

        return sorted(subjects) if subjects else ["Загальне"]

    def get_homework(self):
        return self.data.get("homework", [])

    def save_homework(self, hw_list):
        self.data["homework"] = hw_list
        self.save_data()

    def get_schedule(self):
        return self.data.get("schedule", {})

    def save_schedule(self, schedule_dict):
        normalized = {day: normalize_lesson_list(lessons) for day, lessons in schedule_dict.items()}
        self.data["schedule"] = normalized
        self.save_data()