import threading
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime, timedelta
from data_manager import DataManager, SUBJECT_ALIASES, is_known_subject_alias, suggest_subject_correction
from ai_engine import AIEngine

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

TRANSLATIONS = {
    "UA": {
        "tab_hw": "Домашнє завдання",
        "tab_schedule": "Щоденник та Розклад",
        "deadline_ph": "Дедлайн (ДД.ММ.РРРР)",
        "desc_ph": "Опас (стор, вправа...)",
        "btn_add": "Додати",
        "btn_ai_sort": "✨ Розумне сортування ШІ",
        "scroll_title": "Список активних завдань",
        "warn_title": "Попередження ШІ",
        "btn_complete": "✓ Виконано",
        "today_tag": "🔥 СЬОГОДНІ",
        "overdue_tag": "❌ ПРОСТРОЧЕНО!",
        "edit_day_title": "Редагування розкладу на",
        "btn_save": "Зберегти розклад",
        "no_lessons": "Уроків не додано. Натисніть 'Редагувати', щоб заповнити день.",
        "confirm_complete_title": "Підтвердження",
        "confirm_complete_msg": "Точно виконано?",
        "btn_yes": "Так",
        "btn_no": "Скасувати",
        "edit_hw_title": "Редагування завдання",
        "field_subject": "Предмет:",
        "field_deadline": "Дедлайн (ДД.ММ.РРРР):",
        "field_description": "Опис завдання:",
        "btn_save_changes": "Зберегти зміни"
    },
    "RU": {
        "tab_hw": "Домашнее задание",
        "tab_schedule": "Дневник и Расписание",
        "deadline_ph": "Дедлайн (ДД.ММ.ГГГГ)",
        "desc_ph": "Описание (стр, упражнение...)",
        "btn_add": "Добавить",
        "btn_ai_sort": "✨ Умная сортировка ИИ",
        "scroll_title": "Список активных задач",
        "warn_title": "Предупреждение ИИ",
        "btn_complete": "✓ Выполнено",
        "today_tag": "🔥 СЕГОДНЯ",
        "overdue_tag": "❌ ПРОСРОЧЕНО!",
        "edit_day_title": "Редактирование расписания на",
        "btn_save": "Сохранить расписание",
        "no_lessons": "Уроков не добавлено. Нажмите 'Редактировать', чтобы заполнить день.",
        "confirm_complete_title": "Подтверждение",
        "confirm_complete_msg": "Точно выполнено?",
        "btn_yes": "Да",
        "btn_no": "Отмена",
        "edit_hw_title": "Редактирование задания",
        "field_subject": "Предмет:",
        "field_deadline": "Дедлайн (ДД.ММ.ГГГГ):",
        "field_description": "Описание задания:",
        "btn_save_changes": "Сохранить изменения"
    }
}

DAYS_UA = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]

# Неділю в сітці розкладу не показуємо — рівно 6 днів ділиться на 3x2.
SCHEDULE_DAYS = DAYS_UA[:6]
SCHEDULE_GRID_COLS = 3
SCHEDULE_GRID_ROWS = 2

LESSON_NAME_MAX_LEN = 40


def limit_entry_length(entry: ctk.CTkEntry, max_len: int):
    """Обрізає текст поля, якщо він перевищує max_len (в т.ч. після вставки з буфера)."""
    def _enforce(event=None):
        value = entry.get()
        if len(value) > max_len:
            entry.delete(max_len, "end")

    entry.bind("<KeyRelease>", _enforce, add="+")
    entry.bind("<<Paste>>", lambda e: entry.after(1, _enforce), add="+")

# ================== ВІКНО ПІДТВЕРДЖЕННЯ ДІЇ ==================
class ConfirmDialog(ctk.CTkToplevel):
    """Невелике модальне вікно з питанням і кнопками Так/Скасувати —
    використовується, щоб не дати випадково натиснути 'Виконано'."""
    def __init__(self, parent, title: str, message: str, yes_text: str, no_text: str, on_confirm):
        super().__init__(parent)
        self.on_confirm = on_confirm

        self.title(title)
        self.geometry("360x150")
        self.resizable(False, False)
        self.grab_set()

        lbl = ctk.CTkLabel(self, text=message, font=("Arial", 14), wraplength=300, justify="center")
        lbl.pack(pady=(28, 15), padx=20)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=5)

        btn_yes = ctk.CTkButton(
            btn_frame, text=yes_text, width=110,
            fg_color="#2ECC71", hover_color="#27AE60",
            command=self._confirm
        )
        btn_yes.pack(side="left", padx=8)

        btn_no = ctk.CTkButton(
            btn_frame, text=no_text, width=110,
            fg_color="#7F8C8D", hover_color="#616A6B",
            command=self.destroy
        )
        btn_no.pack(side="left", padx=8)

        self.update_idletasks()
        try:
            px = parent.winfo_x() + (parent.winfo_width() // 2) - 180
            py = parent.winfo_y() + (parent.winfo_height() // 2) - 75
            self.geometry(f"+{px}+{py}")
        except Exception:
            pass

    def _confirm(self):
        self.destroy()
        self.on_confirm()

# ================== ВІКНО РЕДАГУВАННЯ ЗАВДАННЯ ==================
class EditHomeworkDialog(ctk.CTkToplevel):
    """Компактне вікно редагування вже доданого завдання. Попередньо
    заповнюється поточними даними, а збереження йде через ту саму
    валідацію/ШІ-перевірку, що й додавання нового завдання."""
    def __init__(self, parent, task: dict, on_saved):
        super().__init__(parent)
        self.parent_app = parent
        self.task = task
        self.on_saved = on_saved

        t = TRANSLATIONS[parent.current_lang]
        self.title(t["edit_hw_title"])
        self.geometry("380x360")
        self.resizable(False, False)
        self.grab_set()

        ctk.CTkLabel(self, text=t["field_subject"], anchor="w").pack(fill="x", padx=20, pady=(18, 0))
        self.combo_subject = ctk.CTkOptionMenu(self, values=parent.db.get_all_subjects())
        self.combo_subject.set(task.get("subject", ""))
        self.combo_subject.pack(fill="x", padx=20, pady=(2, 0))

        ctk.CTkLabel(self, text=t["field_deadline"], anchor="w").pack(fill="x", padx=20, pady=(14, 0))
        self.entry_deadline = ctk.CTkEntry(self)
        self.entry_deadline.insert(0, task.get("deadline", ""))
        self.entry_deadline.pack(fill="x", padx=20, pady=(2, 0))

        ctk.CTkLabel(self, text=t["field_description"], anchor="w").pack(fill="x", padx=20, pady=(14, 0))
        self.entry_desc = ctk.CTkEntry(self)
        self.entry_desc.insert(0, task.get("description", ""))
        self.entry_desc.pack(fill="x", padx=20, pady=(2, 0))

        btn_save = ctk.CTkButton(
            self, text=t["btn_save_changes"],
            fg_color="#2ECC71", hover_color="#27AE60",
            command=self.save_action
        )
        btn_save.pack(pady=24)

        self.update_idletasks()
        try:
            px = parent.winfo_x() + (parent.winfo_width() // 2) - 190
            py = parent.winfo_y() + (parent.winfo_height() // 2) - 180
            self.geometry(f"+{px}+{py}")
        except Exception:
            pass

    def save_action(self):
        subject = self.combo_subject.get()
        deadline_raw = self.entry_deadline.get().strip()
        desc = self.entry_desc.get().strip()

        # Модель могла ще не бути завантажена — той самий лінивий сценарій,
        # що й при доданні нового завдання.
        if self.parent_app.ai.needs_loading():
            self.parent_app._load_ai_model_then(lambda: self._validate_and_save(subject, deadline_raw, desc))
            return

        self._validate_and_save(subject, deadline_raw, desc)

    def _validate_and_save(self, subject, deadline_raw, desc):
        t = TRANSLATIONS[self.parent_app.current_lang]

        is_valid, msg = self.parent_app.ai.validate_homework(desc, lang=self.parent_app.current_lang)
        if not is_valid:
            messagebox.showwarning(t["warn_title"], msg)
            return

        try:
            deadline_date = datetime.strptime(deadline_raw, "%d.%m.%Y").date()
        except ValueError:
            err_msg = "Невірний формат дедлайну! Використовуйте ДД.ММ.РРРР" if self.parent_app.current_lang == "UA" else "Неверный формат дедлайна! Используйте ДД.ММ.ГГГГ"
            messagebox.showwarning(t["warn_title"], err_msg)
            return

        updated_task = dict(self.task)
        updated_task["subject"] = subject
        updated_task["deadline"] = deadline_date.strftime("%d.%m.%Y")
        updated_task["description"] = desc

        self.on_saved(updated_task)
        self.destroy()

# ================== ОКНО ЗАВАНТАЖЕННЯ ШІ-МОДЕЛІ ==================
class ModelLoadingDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("")
        self.geometry("380x150")
        self.resizable(False, False)

        # Забороняємо закриття хрестиком — очікуємо завершення фонового потоку
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.grab_set()

        lbl = ctk.CTkLabel(
            self,
            text="Завантаження локальної моделі ШІ...\n(Це потрібно лише один раз після запуску)",
            font=("Arial", 13),
            justify="center",
        )
        lbl.pack(pady=(28, 15), padx=20)

        self.progress = ctk.CTkProgressBar(self, mode="indeterminate", width=280)
        self.progress.pack(pady=5)
        self.progress.start()

        self.update_idletasks()
        try:
            px = parent.winfo_x() + (parent.winfo_width() // 2) - 190
            py = parent.winfo_y() + (parent.winfo_height() // 2) - 75
            self.geometry(f"+{px}+{py}")
        except Exception:
            pass

    def close(self):
        self.progress.stop()
        self.grab_release()
        self.destroy()

# ================== ОКНО РЕДАКТИРОВАНИЯ ДНЯ (ДНЕВНИК) ==================
class EditScheduleDialog(ctk.CTkToplevel):
    def __init__(self, parent, day_name, current_lessons, on_save_callback):
        super().__init__(parent)
        self.parent_app = parent
        self.day_name = day_name
        self.on_save_callback = on_save_callback
        
        t = TRANSLATIONS[parent.current_lang]
        self.title(f"{t['edit_day_title']} {day_name}")
        self.geometry("400x520")
        self.resizable(False, False)
        
        # Делаем окно модальным (поверх главного)
        self.grab_set()

        lbl = ctk.CTkLabel(self, text=f"Заповнення уроків: {day_name}", font=("Arial", 16, "bold"))
        lbl.pack(pady=10)

        self.scroll_frame = ctk.CTkScrollableFrame(self, height=360)
        self.scroll_frame.pack(fill="both", expand=True, padx=15, pady=5)

        self.inputs = []
        # Создаем 8 полей для уроков по порядку
        for i in range(8):
            row_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=4)

            lbl_num = ctk.CTkLabel(row_frame, text=f"Урок {i+1}:", width=60, anchor="w")
            lbl_num.pack(side="left")

            val = current_lessons[i] if i < len(current_lessons) else ""
            entry = ctk.CTkEntry(row_frame, placeholder_text="Назва предмета...")
            entry.insert(0, val)
            entry.pack(side="left", fill="x", expand=True, padx=5)
            limit_entry_length(entry, LESSON_NAME_MAX_LEN)

            self.inputs.append(entry)

        btn_save = ctk.CTkButton(self, text=t["btn_save"], fg_color="#2ECC71", hover_color="#27AE60", command=self.save_action)
        btn_save.pack(pady=12)

    def save_action(self):
        new_lessons = [e.get().strip() for e in self.inputs if e.get().strip()]
        # Порівнюємо як з уже вживаними в розкладі предметами, так і з
        # вбудованим словником канонічних назв — щоб ловити помилки навіть
        # у ще жодного разу не введеного предмета.
        known_subjects = list(set(self.parent_app.db.get_all_subjects()) | set(SUBJECT_ALIASES.keys()))

        final_lessons = []
        for lesson in new_lessons:
            # Відомий синонім (наприклад, "Англ мова") мовчки нормалізується
            # пізніше при збереженні — тут питати користувача не потрібно.
            if is_known_subject_alias(lesson):
                final_lessons.append(lesson)
                continue

            suggestion = suggest_subject_correction(lesson, known_subjects)
            if suggestion:
                use_suggestion = messagebox.askyesno(
                    "Можлива помилка у назві предмета",
                    f"Ви ввели «{lesson}».\nМожливо, ви мали на увазі «{suggestion}»?\n\n"
                    f"Використати «{suggestion}»?"
                )
                final_lessons.append(suggestion if use_suggestion else lesson)
            else:
                final_lessons.append(lesson)

        try:
            self.on_save_callback(self.day_name, final_lessons)
        except Exception as e:
            messagebox.showerror("Помилка", f"Не вдалося зберегти розклад: {e}")
        finally:
            self.destroy()

# ================== ГЛАВНОЕ ОКНО ==================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.db = DataManager()
        self.ai = AIEngine(self.db)
        
        self.current_lang = "UA"
        self.current_theme = "Dark"
        self.selected_week_offset = 0
        self.pulse_state = False

        self.title("Шкільний Щоденник")
        self.geometry("1000x720")
        self.minsize(850, 600)

        # ---------------- ВЕРХНЯЯ ПАНЕЛЬ ----------------
        self.top_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_frame.pack(fill="x", padx=10, pady=5)

        self.right_controls = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.right_controls.pack(side="right")

        self.lang_switch = ctk.CTkSegmentedButton(
            self.right_controls,
            values=["UA", "RU"],
            command=self.change_language,
            width=80
        )
        self.lang_switch.set("UA")
        self.lang_switch.pack(side="left", padx=5)

        self.theme_btn = ctk.CTkButton(
            self.right_controls,
            text="🌙",
            width=42,
            height=32,
            corner_radius=10,
            font=("Segoe UI Emoji", 16),
            fg_color="#2B2B2B",
            hover_color="#3B3B3B",
            text_color="#F1C40F",
            command=self.toggle_theme
        )
        self.theme_btn.pack(side="left", padx=5)

        # ---------------- ВКЛАДКИ ----------------
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=5)

        self.tab_hw = self.tabview.add(TRANSLATIONS[self.current_lang]["tab_hw"])
        self.tab_schedule = self.tabview.add(TRANSLATIONS[self.current_lang]["tab_schedule"])

        self._setup_homework_tab()
        self._setup_schedule_tab()

        self.refresh_all_data()
        self._animate_today_buttons()

    def toggle_theme(self):
        if self.current_theme == "Dark":
            self.current_theme = "Light"
            ctk.set_appearance_mode("Light")
            self.theme_btn.configure(text="☀️", text_color="#D35400", fg_color="#E0E0E0", hover_color="#D5D5D5")
        else:
            self.current_theme = "Dark"
            ctk.set_appearance_mode("Dark")
            self.theme_btn.configure(text="🌙", text_color="#F1C40F", fg_color="#2B2B2B", hover_color="#3B3B3B")

    def change_language(self, new_lang: str):
        self.current_lang = new_lang
        t = TRANSLATIONS[self.current_lang]

        self.tabview._segmented_button._buttons_dict[self.tabview._name_list[0]].configure(text=t["tab_hw"])
        self.tabview._segmented_button._buttons_dict[self.tabview._name_list[1]].configure(text=t["tab_schedule"])

        self.entry_deadline.configure(placeholder_text=t["deadline_ph"])
        self.entry_desc.configure(placeholder_text=t["desc_ph"])
        self.btn_add.configure(text=t["btn_add"])
        self.btn_ai_sort.configure(text=t["btn_ai_sort"])
        self.scroll_hw.configure(label_text=t["scroll_title"])
        self.refresh_all_data()

    # ================== ВКЛАДКА: ДОМАШНЕЕ ЗАДАНИЕ ==================
    def _setup_homework_tab(self):
        t = TRANSLATIONS[self.current_lang]

        self.input_frame = ctk.CTkFrame(self.tab_hw)
        self.input_frame.pack(fill="x", padx=10, pady=10)

        self.combo_subject = ctk.CTkOptionMenu(self.input_frame, values=["Загальне"], width=160)
        self.combo_subject.pack(side="left", padx=5, pady=5)

        self.entry_deadline = ctk.CTkEntry(self.input_frame, placeholder_text=t["deadline_ph"], width=160)
        self.entry_deadline.pack(side="left", padx=5, pady=5)

        self.entry_desc = ctk.CTkEntry(self.input_frame, placeholder_text=t["desc_ph"])
        self.entry_desc.pack(side="left", padx=5, pady=5, expand=True, fill="x")

        self.btn_add = ctk.CTkButton(self.input_frame, text=t["btn_add"], width=80, command=self.add_homework_action)
        self.btn_add.pack(side="left", padx=5, pady=5)

        self.controls_frame = ctk.CTkFrame(self.tab_hw, fg_color="transparent")
        self.controls_frame.pack(fill="x", padx=10, pady=2)

        self.btn_ai_sort = ctk.CTkButton(
            self.controls_frame, 
            text=t["btn_ai_sort"], 
            fg_color="#6C5CE7", 
            hover_color="#5A4BD1",
            command=self.ai_sort_action
        )
        self.btn_ai_sort.pack(side="right", padx=5, pady=5)

        self.scroll_hw = ctk.CTkScrollableFrame(self.tab_hw, label_text=t["scroll_title"])
        self.scroll_hw.pack(fill="both", expand=True, padx=10, pady=10)

    def update_subject_dropdown(self):
        subjects = self.db.get_all_subjects()
        self.combo_subject.configure(values=subjects)
        if subjects:
            self.combo_subject.set(subjects[0])

    def add_homework_action(self):
        subject = self.combo_subject.get()
        deadline_raw = self.entry_deadline.get().strip()
        desc = self.entry_desc.get().strip()

        if self.ai.needs_loading():
            self._load_ai_model_then(lambda: self._finish_add_homework(subject, deadline_raw, desc))
            return

        self._finish_add_homework(subject, deadline_raw, desc)

    def _load_ai_model_then(self, callback):
        """Показує модальне вікно і вантажить модель у фоновому потоці,
        щоб інтерфейс не завис на важкій ініціалізації llama.cpp."""
        dialog = ModelLoadingDialog(self)
        state = {"done": False}

        def worker():
            self.ai.load_model()
            state["done"] = True

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if state["done"]:
                dialog.close()
                callback()
            else:
                self.after(100, poll)

        self.after(100, poll)

    def _finish_add_homework(self, subject, deadline_raw, desc):
        t = TRANSLATIONS[self.current_lang]

        is_valid, msg = self.ai.validate_homework(desc, lang=self.current_lang)
        if not is_valid:
            messagebox.showwarning(t["warn_title"], msg)
            return

        if not deadline_raw:
            deadline_date = datetime.now().date() + timedelta(days=1)
        else:
            try:
                deadline_date = datetime.strptime(deadline_raw, "%d.%m.%Y").date()
            except ValueError:
                err_msg = "Невірний формат дедлайну! Використовуйте ДД.ММ.РРРР" if self.current_lang == "UA" else "Неверный формат дедлайна! Используйте ДД.ММ.ГГГГ"
                messagebox.showwarning(t["warn_title"], err_msg)
                return

        # Нормалізуємо дедлайн до єдиного формату з нулями (05.09.2026),
        # інакше рядкове порівняння дат у розкладі не спрацює.
        deadline = deadline_date.strftime("%d.%m.%Y")

        new_task = {
            "id": str(datetime.now().timestamp()),
            "subject": subject,
            "deadline": deadline,
            "description": desc,
            "completed": False
        }

        tasks = self.db.get_homework()
        tasks.append(new_task)
        self.db.save_homework(tasks)

        self.entry_deadline.delete(0, 'end')
        self.entry_desc.delete(0, 'end')

        self.refresh_all_data()

    def ai_sort_action(self):
        tasks = self.db.get_homework()
        sorted_tasks = self.ai.sort_tasks(tasks)
        self.db.save_homework(sorted_tasks)
        self.refresh_homework_list()

    def refresh_homework_list(self):
        for child in self.scroll_hw.winfo_children():
            child.destroy()

        t = TRANSLATIONS[self.current_lang]
        # Список завжди показуємо відсортованим за пріоритетом: прострочені
        # зверху, далі "гарячі" (дедлайн сьогодні/завтра або проект/реферат),
        # решта — за наближенням дедлайну. Порядок збереження на диску не
        # чіпаємо — це лише порядок відображення.
        tasks = self.ai.sort_tasks(self.db.get_homework())
        today_str = datetime.now().strftime("%d.%m.%Y")

        self.today_buttons = []

        for idx, task in enumerate(tasks):
            is_today = (task['deadline'] == today_str)
            is_overdue = self.ai.is_overdue_task(task)
            is_urgent = self.ai.is_urgent_task(task)

            if is_urgent:
                border_width, border_color = 2, "#E74C3C"
            elif is_today:
                border_width, border_color = 2, "#2ECC71"
            else:
                border_width, border_color = 0, "#333333"

            card = ctk.CTkFrame(self.scroll_hw, border_width=border_width, border_color=border_color)
            card.pack(fill="x", padx=5, pady=5)

            if is_overdue:
                prefix = f"{t['overdue_tag']} "
            elif is_today:
                prefix = f"{t['today_tag']} "
            else:
                prefix = ""
            info_text = f"{prefix}[{task['subject']}] (до {task['deadline']})\n{task['description']}"

            lbl = ctk.CTkLabel(card, text=info_text, justify="left", anchor="w", font=("Arial", 13, "bold" if (is_today or is_overdue) else "normal"))
            lbl.pack(side="left", padx=10, pady=8, expand=True, fill="x")

            # Кнопки праворуч: спершу пакуємо "Виконано" (буде крайнім
            # правим), потім "✕" — вона стане лівіше від нього.
            btn_done = ctk.CTkButton(
                card,
                text=t["btn_complete"],
                fg_color="#2ECC71",
                hover_color="#27AE60",
                width=110,
                command=lambda task_id=task['id']: self.confirm_complete_task(task_id)
            )
            btn_done.pack(side="right", padx=(5, 10), pady=5)
            if is_today:
                self.today_buttons.append(btn_done)

            btn_edit = ctk.CTkButton(
                card,
                text="✏️",
                width=35,
                fg_color="#34495E",
                hover_color="#2C3E50",
                command=lambda task_data=task: self.open_edit_homework_dialog(task_data)
            )
            btn_edit.pack(side="right", padx=5, pady=5)

            btn_del = ctk.CTkButton(
                card,
                text="✕",
                width=35,
                fg_color="#E74C3C",
                hover_color="#C0392B",
                command=lambda task_id=task['id']: self.delete_task(task_id)
            )
            btn_del.pack(side="right", padx=(0, 5), pady=5)

            # "❗" — одразу після тексту, перед кнопками, для "гарячих"
            # завдань (дедлайн менш ніж за 2 дні, або тип проект/реферат).
            if is_urgent:
                lbl_alert = ctk.CTkLabel(card, text="❗", text_color="#E74C3C", font=("Arial", 20, "bold"))
                lbl_alert.pack(side="right", padx=(0, 5))

    def _animate_today_buttons(self):
        self.pulse_state = not self.pulse_state
        color = "#2ECC71" if self.pulse_state else "#1ABC9C"
        
        if hasattr(self, 'today_buttons'):
            for btn in self.today_buttons:
                try:
                    btn.configure(fg_color=color)
                except Exception:
                    pass
        
        self.after(800, self._animate_today_buttons)

    def confirm_complete_task(self, task_id):
        t = TRANSLATIONS[self.current_lang]
        ConfirmDialog(
            self,
            title=t["confirm_complete_title"],
            message=t["confirm_complete_msg"],
            yes_text=t["btn_yes"],
            no_text=t["btn_no"],
            on_confirm=lambda: self.complete_task(task_id)
        )

    def complete_task(self, task_id):
        tasks = self.db.get_homework()
        for task in tasks:
            if task['id'] == task_id:
                task['completed'] = True
                break
        self.db.save_homework(tasks)
        self.refresh_all_data()

    def delete_task(self, task_id):
        tasks = [t for t in self.db.get_homework() if t['id'] != task_id]
        self.db.save_homework(tasks)
        self.refresh_all_data()

    def open_edit_homework_dialog(self, task):
        EditHomeworkDialog(self, task, self.save_edited_homework)

    def save_edited_homework(self, updated_task):
        tasks = self.db.get_homework()
        for i, task in enumerate(tasks):
            if task['id'] == updated_task['id']:
                tasks[i] = updated_task
                break
        self.db.save_homework(tasks)
        # refresh_all_data -> refresh_homework_list заново пропускає кожну
        # задачу через ai.sort_tasks/is_urgent_task/is_overdue_task, тож
        # пріоритет, сортування і візуальні акценти перебудуються самі.
        self.refresh_all_data()

    # ================== ВКЛАДКА: ДНЕВНИК И РАСПИСАНИЕ ==================
    def _setup_schedule_tab(self):
        self.week_nav_frame = ctk.CTkFrame(self.tab_schedule, fg_color="transparent")
        self.week_nav_frame.pack(fill="x", padx=10, pady=5)

        self.btn_prev_week = ctk.CTkButton(self.week_nav_frame, text="◄", width=40, command=self.prev_week)
        self.btn_prev_week.pack(side="left", padx=5)

        self.lbl_week_range = ctk.CTkLabel(self.week_nav_frame, text="", font=("Arial", 14, "bold"))
        self.lbl_week_range.pack(side="left", expand=True)

        self.btn_next_week = ctk.CTkButton(self.week_nav_frame, text="►", width=40, command=self.next_week)
        self.btn_next_week.pack(side="right", padx=5)

        self.scroll_schedule = ctk.CTkScrollableFrame(self.tab_schedule)
        self.scroll_schedule.pack(fill="both", expand=True, padx=10, pady=5)

        # Сітка 3 колонки x 2 рядки під картки днів (Пн-Сб).
        for col in range(SCHEDULE_GRID_COLS):
            self.scroll_schedule.grid_columnconfigure(col, weight=1)
        for row in range(SCHEDULE_GRID_ROWS):
            self.scroll_schedule.grid_rowconfigure(row, weight=1)

    def prev_week(self):
        if self.selected_week_offset > -2:
            self.selected_week_offset -= 1
            self.refresh_schedule_view()

    def next_week(self):
        self.selected_week_offset += 1
        self.refresh_schedule_view()

    def get_dates_for_current_view(self):
        today = datetime.now().date()
        start_of_week = today - timedelta(days=today.weekday()) + timedelta(weeks=self.selected_week_offset)
        return [start_of_week + timedelta(days=i) for i in range(7)]

    def refresh_schedule_view(self):
        for child in self.scroll_schedule.winfo_children():
            child.destroy()

        t = TRANSLATIONS[self.current_lang]
        dates = self.get_dates_for_current_view()
        start_str = dates[0].strftime("%d.%m")
        end_str = dates[5].strftime("%d.%m.%Y")
        self.lbl_week_range.configure(text=f"Тиждень: {start_str} — {end_str}")

        schedule_data = self.db.get_schedule()
        all_hw = self.db.get_homework()
        today = datetime.now().date()

        # Сітка 3x2: 6 карток днів (Пн-Сб), неділя в UI не показується.
        for day_idx, day_name in enumerate(SCHEDULE_DAYS):
            day_date = dates[day_idx]
            day_date_str = day_date.strftime("%d.%m.%Y")
            is_today = (day_date == today)

            grid_row, grid_col = divmod(day_idx, SCHEDULE_GRID_COLS)

            day_card = ctk.CTkFrame(
                self.scroll_schedule,
                border_width=2 if is_today else 1,
                border_color="#2ECC71" if is_today else "#333333"
            )
            day_card.grid(row=grid_row, column=grid_col, padx=6, pady=6, sticky="nsew")

            # Шапка картки: назва дня + дата зліва, компактна кнопка
            # редагування точно в куті справа.
            header_frame = ctk.CTkFrame(day_card, fg_color="transparent")
            header_frame.pack(fill="x", padx=8, pady=(8, 4))

            header_text = f"{day_name}\n{day_date_str}" + (" 🔥" if is_today else "")
            lbl_header = ctk.CTkLabel(
                header_frame,
                text=header_text,
                font=("Arial", 13, "bold"),
                justify="left",
                anchor="w",
                text_color="#2ECC71" if is_today else None
            )
            lbl_header.pack(side="left")

            lessons = schedule_data.get(day_name, [])
            btn_edit = ctk.CTkButton(
                header_frame,
                text="✎",
                width=28,
                height=28,
                fg_color="#34495E",
                hover_color="#2C3E50",
                command=lambda d=day_name, l=lessons: self.open_edit_schedule_dialog(d, l)
            )
            btn_edit.pack(side="right", anchor="ne")

            # Компактний список уроків картки
            if not lessons:
                lbl_empty = ctk.CTkLabel(
                    day_card, text=t["no_lessons"], text_color="gray",
                    font=("Arial", 11), anchor="w", justify="left", wraplength=210
                )
                lbl_empty.pack(fill="x", padx=8, pady=(0, 8))
            else:
                day_hws = [h for h in all_hw if h.get("deadline") == day_date_str]

                lessons_frame = ctk.CTkFrame(day_card, fg_color="transparent")
                lessons_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

                for lesson_idx, lesson_title in enumerate(lessons):
                    row = ctk.CTkFrame(lessons_frame, fg_color="#2B2B2B" if self.current_theme == "Dark" else "#F0F0F0")
                    row.pack(fill="x", pady=1)

                    lbl_sub = ctk.CTkLabel(
                        row,
                        text=f"{lesson_idx + 1}. {lesson_title}",
                        anchor="w",
                        justify="left",
                        font=("Arial", 11, "bold"),
                        wraplength=200
                    )
                    lbl_sub.pack(fill="x", padx=6, pady=(3, 0))

                    # ДЗ до цього уроку (якщо є) — компактним рядком нижче
                    sub_hw = [h for h in day_hws if h.get("subject", "").lower() == lesson_title.lower()]
                    if sub_hw:
                        hw_items = []
                        all_done = True
                        for h in sub_hw:
                            done = h.get("completed", False)
                            hw_items.append(f"{'✓' if done else '📌'} {h['description']}")
                            all_done = all_done and done
                        hw_text = " | ".join(hw_items)

                        lbl_hw_desc = ctk.CTkLabel(
                            row,
                            text=hw_text,
                            anchor="w",
                            justify="left",
                            wraplength=190,
                            font=("Arial", 10),
                            # М'який кораловий акцент для активної дз, зелений — коли все виконано
                            text_color="#2ECC71" if all_done else "#FF6F61"
                        )
                        lbl_hw_desc.pack(fill="x", padx=6, pady=(0, 4))
                    else:
                        ctk.CTkLabel(row, text="", height=1).pack()

    def open_edit_schedule_dialog(self, day_name, current_lessons):
        EditScheduleDialog(self, day_name, current_lessons, self.save_schedule_callback)

    def save_schedule_callback(self, day_name, new_lessons):
        sched = self.db.get_schedule()
        sched[day_name] = new_lessons
        self.db.save_schedule(sched)
        self.refresh_all_data()

    def refresh_all_data(self):
        self.update_subject_dropdown()
        self.refresh_homework_list()
        self.refresh_schedule_view()

if __name__ == "__main__":
    app = App()
    app.mainloop()