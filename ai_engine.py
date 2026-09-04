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

    def calculate_priority(self, item: dict) -> float:
        score = 0.0
        today = datetime.now().date()

        try:
            deadline_date = datetime.strptime(item["deadline"], "%d.%m.%Y").date()
            days_left = (deadline_date - today).days

            if days_left == 0:
                score += 1000
            elif days_left < 0:
                score += 500
            elif days_left == 1:
                score += 80
            elif days_left <= 3:
                score += 50
            else:
                score += max(5, 30 - days_left * 2)
        except (ValueError, KeyError):
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
        active_tasks = [t for t in tasks if not t.get("completed", False)]
        return sorted(active_tasks, key=lambda x: self.calculate_priority(x), reverse=True)
