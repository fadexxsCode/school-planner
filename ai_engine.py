from datetime import datetime

class AIEngine:
    def __init__(self, data_manager):
        self.db = data_manager

    def validate_homework(self, text: str, lang: str = "UA") -> tuple[bool, str]:
        cleaned_text = text.strip().lower()
        
        if len(cleaned_text) < 3:
            msg = "Занадто короткий опис!" if lang == "UA" else "Слишком короткое описание!"
            return False, msg

        trash_words = [
            "какашка", "бред", "авава", "тест123", "забей", "фигня",
            "лайно", "дурниця", "сміття", "забий", "нісенітниця"
        ]
        for word in trash_words:
            if word in cleaned_text:
                msg = "⚠️ Це не схоже на домашнє завдання!" if lang == "UA" else "⚠️ Это не похоже на домашнее задание!"
                return False, msg

        return True, "OK"

    def calculate_priority(self, item: dict) -> float:
        score = 0.0
        today = datetime.now().date()
        
        try:
            deadline_date = datetime.strptime(item["deadline"], "%d.%m.%Y").date()
            days_left = (deadline_date - today).days

            # 🌟 Если дедлайн СЕГОДНЯ — абсолютный максимальный приоритет!
            if days_left == 0:
                score += 1000
            elif days_left < 0:
                score += 500  # Просрочено
            elif days_left == 1:
                score += 80   # На завтра
            elif days_left <= 3:
                score += 50
            else:
                score += max(5, 30 - days_left * 2)
        except ValueError:
            score += 10

        text_length = len(item.get("description", ""))
        if text_length > 100:
            score += 15
        elif text_length > 40:
            score += 8

        subject = item.get("subject", "")
        subject_weights = self.db.data.get("subject_weights", {})
        custom_multiplier = subject_weights.get(subject, 1.0)

        return score * custom_multiplier

    def sort_tasks(self, tasks: list) -> list:
        # Выполненные задачи убираем из активного планировщика
        active_tasks = [t for t in tasks if not t.get("completed", False)]
        return sorted(active_tasks, key=lambda x: self.calculate_priority(x), reverse=True)