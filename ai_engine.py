import os
import threading
from datetime import datetime

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

MODEL_PATH = "./models/qwen2.5-3b-instruct-q4_k_m.gguf"

TRASH_WORDS = [
    "какашка", "бред", "авава", "тест123", "забей", "фигня",
    "лайно", "дурниця", "сміття", "забий", "нісенітниця"
]

# Ключові слова, що вказують на "великий" тип роботи — такі завдання
# вимагають більше часу на підготовку, тож підсвічуємо їх завчасно.
URGENT_TYPE_KEYWORDS = ["проект", "реферат"]

URGENT_DAYS_THRESHOLD = 2


class AIEngine:
    def __init__(self, data_manager):
        self.db = data_manager
        self.llm = None
        self._load_lock = threading.Lock()

        if Llama is None:
            print("[AIEngine] Бібліотека llama-cpp-python не встановлена — ШІ-перевірка вимкнена.")
            self.model_state = "unavailable"
        elif not os.path.isfile(MODEL_PATH):
            print(f"[AIEngine] Файл моделі не знайдено: {MODEL_PATH} — ШІ-перевірка вимкнена.")
            self.model_state = "unavailable"
        else:
            # Файл є і бібліотека є — саме завантаження моделі в пам'ять
            # відкладається до першого виклику validate_homework (ліниве завантаження).
            self.model_state = "not_loaded"

    def is_model_ready(self) -> bool:
        return self.llm is not None

    def needs_loading(self) -> bool:
        """True, якщо модель ще жодного разу не намагались завантажити і варто
        зробити це у фоновому потоці перед першою перевіркою тексту."""
        return self.model_state == "not_loaded" and self.llm is None

    def load_model(self):
        """Важке завантаження .gguf у пам'ять. Викликати з фонового потоку,
        щоб не блокувати інтерфейс. Безпечно викликати повторно."""
        with self._load_lock:
            if self.llm is not None or self.model_state == "unavailable":
                return

            self.model_state = "loading"
            try:
                self.llm = Llama(
                    model_path=MODEL_PATH,
                    n_ctx=2048,
                    n_threads=max(1, (os.cpu_count() or 4) - 1),
                    n_gpu_layers=0,
                    verbose=False,
                )
                self.model_state = "loaded"
            except Exception as e:
                print(f"[AIEngine] Не вдалося завантажити модель: {e} — ШІ-перевірка вимкнена.")
                self.llm = None
                self.model_state = "failed"

    def validate_homework(self, text: str, lang: str = "UA") -> tuple[bool, str]:
        cleaned_text = text.strip().lower()

        short_msg = "Занадто короткий опис!" if lang == "UA" else "Слишком короткое описание!"
        trash_msg = "⚠️ Це не схоже на домашнє завдання!" if lang == "UA" else "⚠️ Это не похоже на домашнее задание!"

        if len(cleaned_text) < 3:
            return False, short_msg

        for word in TRASH_WORDS:
            if word in cleaned_text:
                return False, trash_msg

        if self.llm is None:
            return True, "OK"

        try:
            return self._validate_with_llm(text.strip(), lang, trash_msg)
        except Exception as e:
            print(f"[AIEngine] Помилка інференсу моделі: {e}")
            return True, "OK"

    def _validate_with_llm(self, text: str, lang: str, trash_msg: str) -> tuple[bool, str]:
        prompt = (
            "You check if a short student note is a real homework/study task description "
            "(subject topic, page, exercise, project, exam, reading, etc.) written in Ukrainian or Russian, "
            "as opposed to spam, gibberish, random keyboard smashing or an unrelated message.\n"
            "Respond with exactly one word: OK if it is a plausible homework description, "
            "or INVALID if it is not.\n\n"
            f"Text language: {lang}\n"
            f"Text: \"{text}\"\n"
            "Answer:"
        )

        response = self.llm.create_chat_completion(
            messages=[
                {"role": "system", "content": "You are a strict but fair homework text validator. Reply with a single word only."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=10,
            temperature=0.0,
        )

        answer = response["choices"][0]["message"]["content"].strip().upper()

        if "INVALID" in answer:
            return False, trash_msg
        return True, "OK"

    def _days_left(self, item: dict):
        """Кількість днів до дедлайну, або None, якщо дату не вдалося розібрати."""
        try:
            deadline_date = datetime.strptime(item["deadline"], "%d.%m.%Y").date()
            return (deadline_date - datetime.now().date()).days
        except (ValueError, KeyError):
            return None

    def is_overdue_task(self, item: dict) -> bool:
        """True, якщо дедлайн уже минув."""
        days_left = self._days_left(item)
        return days_left is not None and days_left < 0

    def is_urgent_task(self, item: dict) -> bool:
        """Позначає завдання як 'горить' — без звернення до ШІ, лише за
        датою дедлайну (менше URGENT_DAYS_THRESHOLD днів, включно з
        простроченими) або за типом роботи (проект/реферат у описі)."""
        days_left = self._days_left(item)
        if days_left is not None and days_left < URGENT_DAYS_THRESHOLD:
            return True

        description = item.get("description", "").lower()
        return any(keyword in description for keyword in URGENT_TYPE_KEYWORDS)

    def calculate_priority(self, item: dict) -> float:
        """Пріоритет для сортування списку активних завдань. Три чіткі рівні:
        1) прострочені — завжди зверху, чим довше прострочено, тим вище;
        2) 'гарячі' (дедлайн сьогодні/завтра або тип проект/реферат);
        3) решта — за наближенням дедлайну."""
        days_left = self._days_left(item)
        is_overdue = self.is_overdue_task(item)
        is_urgent = self.is_urgent_task(item)

        if is_overdue:
            score = 10_000 + abs(days_left)
        elif is_urgent:
            score = 5_000 - (days_left or 0)
        elif days_left is not None:
            score = max(0, 1_000 - days_left)
        else:
            score = 10  # некоректна/відсутня дата дедлайну

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
        active_tasks = [t for t in tasks if not t.get("completed", False)]
        return sorted(active_tasks, key=lambda x: self.calculate_priority(x), reverse=True)
