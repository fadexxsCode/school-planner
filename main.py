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
        "edit_day_title": "Редагування розкладу на",
        "btn_save": "Зберегти розклад",
        "no_lessons": "Уроків не додано. Натисніть 'Редагувати', щоб заповнити день."
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
        "edit_day_title": "Редактирование расписания на",
        "btn_save": "Сохранить расписание",
        "no_lessons": "Уроков не добавлено. Нажмите 'Редактировать', чтобы заполнить день."
    }
}

DAYS_UA = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]

LESSON_NAME_MAX_LEN = 40


def limit_entry_length(entry: ctk.CTkEntry, max_len: int):
    """Обрізає текст поля, якщо він перевищує max_len (в т.ч. після вставки з буфера)."""
    def _enforce(event=None):
        value = entry.get()
        if len(value) > max_len:
            entry.delete(max_len, "end")

    entry.bind("<KeyRelease>", _enforce, add="+")
    entry.bind("<<Paste>>", lambda e: entry.after(1, _enforce), add="+")

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
        tasks = [item for item in self.db.get_homework() if not item.get("completed", False)]
        today_str = datetime.now().strftime("%d.%m.%Y")

        self.today_buttons = []

        for idx, task in enumerate(tasks):
            is_today = (task['deadline'] == today_str)
            
            card = ctk.CTkFrame(self.scroll_hw, border_width=2 if is_today else 0, border_color="#2ECC71" if is_today else "#333333")
            card.pack(fill="x", padx=5, pady=5)

            prefix = f"{t['today_tag']} " if is_today else ""
            info_text = f"{prefix}[{task['subject']}] (до {task['deadline']})\n{task['description']}"
            
            lbl = ctk.CTkLabel(card, text=info_text, justify="left", anchor="w", font=("Arial", 13, "bold" if is_today else "normal"))
            lbl.pack(side="left", padx=10, pady=8, expand=True, fill="x")

            if is_today:
                btn_done = ctk.CTkButton(
                    card, 
                    text=t["btn_complete"], 
                    fg_color="#2ECC71", 
                    hover_color="#27AE60",
                    width=110,
                    command=lambda task_id=task['id']: self.complete_task(task_id)
                )
                btn_done.pack(side="right", padx=10, pady=5)
                self.today_buttons.append(btn_done)
            else:
                btn_del = ctk.CTkButton(
                    card, 
                    text="✕", 
                    width=35, 
                    fg_color="#E74C3C", 
                    hover_color="#C0392B",
                    command=lambda task_id=task['id']: self.delete_task(task_id)
                )
                btn_del.pack(side="right", padx=10, pady=5)

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
        end_str = dates[6].strftime("%d.%m.%Y")
        self.lbl_week_range.configure(text=f"Тиждень: {start_str} — {end_str}")

        schedule_data = self.db.get_schedule()
        all_hw = self.db.get_homework()

        # Отображаем 7 карточек дней (таблицы бумажного дневника)
        for day_idx, day_name in enumerate(DAYS_UA):
            day_date = dates[day_idx]
            day_date_str = day_date.strftime("%d.%m.%Y")
            is_today = (day_date == datetime.now().date())

            day_card = ctk.CTkFrame(
                self.scroll_schedule, 
                border_width=2 if is_today else 1, 
                border_color="#2ECC71" if is_today else "#333333"
            )
            day_card.pack(fill="x", padx=5, pady=8)

            # Шапка дня дневника
            header_frame = ctk.CTkFrame(day_card, fg_color="transparent")
            header_frame.pack(fill="x", padx=10, pady=5)

            header_text = f"{day_name} ({day_date_str})" + (" — СЬОГОДНІ" if is_today else "")
            lbl_header = ctk.CTkLabel(
                header_frame, 
                text=header_text, 
                font=("Arial", 14, "bold"), 
                text_color="#2ECC71" if is_today else None
            )
            lbl_header.pack(side="left")

            # Кнопка быстрой настройки расписания для этого дня
            lessons = schedule_data.get(day_name, [])
            btn_edit = ctk.CTkButton(
                header_frame, 
                text="✎ Редагувати", 
                width=100, 
                height=24,
                fg_color="#34495E",
                hover_color="#2C3E50",
                command=lambda d=day_name, l=lessons: self.open_edit_schedule_dialog(d, l)
            )
            btn_edit.pack(side="right")

            # Таблица предметов дня (как в бумажном дневнике)
            if not lessons:
                lbl_empty = ctk.CTkLabel(day_card, text=t["no_lessons"], text_color="gray", anchor="w")
                lbl_empty.pack(padx=15, pady=5)
            else:
                table_frame = ctk.CTkFrame(day_card, fg_color="transparent")
                table_frame.pack(fill="x", padx=10, pady=5)

                # Ищем домашние задания для этой конкретной даты
                day_hws = [h for h in all_hw if h.get("deadline") == day_date_str]

                for lesson_idx, lesson_title in enumerate(lessons):
                    row = ctk.CTkFrame(table_frame, fg_color="#2B2B2B" if self.current_theme=="Dark" else "#F0F0F0")
                    row.pack(fill="x", pady=2)

                    lesson_row = ctk.CTkFrame(row, fg_color="transparent")
                    lesson_row.pack(fill="x", padx=5, pady=(4, 0))

                    # Номер урока
                    lbl_num = ctk.CTkLabel(lesson_row, text=f"№ {lesson_idx+1}", width=45, font=("Arial", 12, "bold"))
                    lbl_num.pack(side="left")

                    # Название предмета
                    lbl_sub = ctk.CTkLabel(lesson_row, text=lesson_title, anchor="w", font=("Arial", 13, "bold"))
                    lbl_sub.pack(side="left", padx=5, fill="x", expand=True)

                    # ДЗ к этому конкретному предмету (если есть) — выводим отдельной строкой под уроком
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
                            wraplength=600,
                            font=("Arial", 12),
                            # М'який кораловий акцент для активної дз, зелений — коли все виконано
                            text_color="#2ECC71" if all_done else "#FF6F61"
                        )
                        lbl_hw_desc.pack(fill="x", padx=(50, 10), pady=(0, 6))
                    else:
                        # Невеликий відступ знизу, щоб урок без дз не "злипався" з наступним
                        ctk.CTkLabel(row, text="", height=2).pack()

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