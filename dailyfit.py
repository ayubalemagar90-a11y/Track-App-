"""
DailyFit — lightweight Windows personal routine tracker.
Uses only Python's standard library plus optional winotify for Windows toast alerts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

try:
    from version_info import APP_VERSION
except Exception:
    APP_VERSION = "0.1.0"

APP_NAME = "DailyFit"
TRISAMBAT = "https://trisambat.com"
TRISAMBAT_API = TRISAMBAT + "/api/v1"
USER_HOME = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
APP_DIR = USER_HOME / "DailyFit"
CACHE_DIR = APP_DIR / "calendar_cache"
APP_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = APP_DIR / "data.json"

THEMES = {
    "Purple": {"bg": "#101722", "panel": "#1b2637", "panel2": "#243249",
               "fg": "#f2f5fa", "muted": "#aab6c7", "accent": "#a78bfa",
               "border": "#34445c"},
    "Ocean": {"bg": "#0e2029", "panel": "#1b3540", "panel2": "#244653",
              "fg": "#f1f7f8", "muted": "#a9c0c7", "accent": "#5ed1e6",
              "border": "#345763"},
    "Light": {"bg": "#f2f5fb", "panel": "#ffffff", "panel2": "#e8edf7",
              "fg": "#172033", "muted": "#657188", "accent": "#6653dd",
              "border": "#d5ddeb"},
}

DEFAULTS = {
    "theme": "Purple",
    "weekday_schedule": [
        "05:45 | Wake up and get ready",
        "06:00 | Morning study",
        "07:00 | Breakfast and prepare for school",
        "09:00 | School",
        "16:30 | Return home, snack and rest",
        "17:00 | Gentle movement / exercise (optional)",
        "17:30 | Homework and study",
        "19:00 | Dinner",
        "19:30 | Revision / reading",
        "20:45 | Free time and prepare for tomorrow",
        "21:30 | Sleep",
    ],
    "home_schedule": [
        "07:00 | Wake up and breakfast",
        "08:00 | Study session",
        "09:00 | Short break",
        "09:30 | Homework / reading",
        "11:00 | Free time or help at home",
        "12:30 | Lunch and rest",
        "14:00 | Study session",
        "15:00 | Hobby / relaxing break",
        "16:00 | Gentle movement / exercise (optional)",
        "17:00 | Review and personal tasks",
        "19:00 | Dinner",
        "20:00 | Relax and prepare for tomorrow",
        "21:30 | Sleep",
    ],
    "weekend_schedule": [
        "07:30 | Wake up and breakfast",
        "08:30 | Study / catch up",
        "10:00 | Free time",
        "11:00 | Hobby or family time",
        "12:30 | Lunch",
        "14:00 | Relax / reading",
        "16:00 | Outdoor time or gentle movement (optional)",
        "17:00 | Personal projects",
        "19:00 | Dinner",
        "20:00 | Prepare for the week",
        "21:30 | Sleep",
    ],
    "holiday_schedule": [
        "07:30 | Wake up and breakfast",
        "08:30 | Relaxed study or reading",
        "10:00 | Family / free time",
        "12:30 | Lunch",
        "14:00 | Hobby time",
        "16:00 | Optional walk or gentle movement",
        "18:00 | Free time",
        "19:00 | Dinner",
        "20:00 | Relax",
        "21:30 | Sleep",
    ],
    "notes": "",
    "activities": ["Push-ups", "Sit-ups", "Squats", "Water (mL)"],
    "counts": {},
    "day_modes": {},
    "school_closures": [],
    "reminders_enabled": True,
    "startup_enabled": False,
    "github_repo": "",
    "calendar_language": "en",
}

def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            merged = DEFAULTS.copy()
            merged.update(data if isinstance(data, dict) else {})
            return merged
        except (OSError, ValueError):
            pass
    # Migrate data from the earlier DailyFitPlanner prototype when available.
    old_file = Path.home() / "DailyFitPlanner" / "planner.json"
    merged = DEFAULTS.copy()
    if old_file.exists():
        try:
            old = json.loads(old_file.read_text(encoding="utf-8"))
            if old.get("weekday"):
                merged["weekday_schedule"] = [x for x in old["weekday"].splitlines() if x.strip()]
            if old.get("weekend"):
                merged["weekend_schedule"] = [x for x in old["weekend"].splitlines() if x.strip()]
            merged["notes"] = old.get("notes", "")
            merged["counts"] = old.get("counts", {})
            merged["school_closures"] = old.get("holidays", [])
        except (OSError, ValueError, AttributeError):
            pass
    return merged

DATA = load_data()

def save_data():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)

def parse_schedule(lines):
    parsed = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if "|" not in line:
            raise ValueError(f"Use HH:MM | Activity format: {line}")
        clock, activity = line.split("|", 1)
        datetime.strptime(clock.strip(), "%H:%M")
        activity = activity.strip()
        if not activity:
            raise ValueError("Activity names cannot be empty.")
        parsed.append((clock.strip(), activity))
    return sorted(parsed, key=lambda x: x[0])

def day_key():
    return date.today().isoformat()

def date_is_weekend(day: date):
    return day.weekday() >= 5  # Saturday and Sunday

def version_tuple(value):
    nums = re.findall(r"\d+", str(value))
    return tuple(int(x) for x in nums[:4]) or (0,)

class DailyFit(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"DailyFit  •  v{APP_VERSION}")
        self.geometry("1060x740")
        self.minsize(800, 590)
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_taskbar)
        self.current_page = "Dashboard"
        self.current_schedule_type = "weekday_schedule"
        self.schedule_editor = None
        self.calendar_month = date.today().replace(day=1)
        self.month_days = []
        self.calendar_loading = False
        self.reminded = set()
        self.last_update_check = None
        self.theme = THEMES.get(DATA.get("theme"), THEMES["Purple"])
        self._build_shell()
        self.show_page("Dashboard")
        self.after(5000, self.reminder_tick)
        self.after(12000, lambda: self.check_for_updates(silent=True, automatic=True))
        self.after(2500, self.refresh_calendar_background)
        self.after(3600000, self.periodic_update_check)
        if "--background" in sys.argv:
            self.after(700, self.iconify)

    def _build_shell(self):
        self.configure(bg=self.theme["bg"])
        self.sidebar = tk.Frame(self, bg=self.theme["panel"], width=205)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Label(self.sidebar, text="DAILYFIT", bg=self.theme["panel"],
                 fg=self.theme["fg"], font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=20, pady=(24, 0))
        tk.Label(self.sidebar, text="Personal routine & wellness", bg=self.theme["panel"],
                 fg=self.theme["muted"], font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(2, 22))
        self.nav_buttons = {}
        for name, symbol in [
            ("Dashboard", "⌂"), ("Timetable", "▦"), ("Trainer", "◉"),
            ("Calendar", "▣"), ("Notes", "✎"), ("Settings", "⚙")
        ]:
            b = tk.Button(self.sidebar, text=f"  {symbol}   {name}", anchor="w",
                          command=lambda n=name: self.show_page(n),
                          bg=self.theme["panel"], fg=self.theme["fg"],
                          activebackground=self.theme["panel2"],
                          activeforeground=self.theme["fg"], relief="flat",
                          bd=0, padx=14, pady=12, font=("Segoe UI", 11))
            b.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[name] = b
        tk.Frame(self.sidebar, bg=self.theme["border"], height=1).pack(fill="x", padx=15, pady=16)
        tk.Label(self.sidebar, text=f"Version {APP_VERSION}", bg=self.theme["panel"],
                 fg=self.theme["muted"], font=("Segoe UI", 9)).pack(side="bottom", anchor="w", padx=20, pady=16)

        self.main = tk.Frame(self, bg=self.theme["bg"])
        self.main.pack(side="right", fill="both", expand=True)
        self.header = tk.Frame(self.main, bg=self.theme["bg"])
        self.header.pack(fill="x", padx=26, pady=(22, 12))
        self.header_title = tk.Label(self.header, text="Dashboard", bg=self.theme["bg"],
                                     fg=self.theme["fg"], font=("Segoe UI", 22, "bold"))
        self.header_title.pack(side="left")
        self.header_date = tk.Label(self.header, text=date.today().strftime("%A, %d %B %Y"),
                                    bg=self.theme["bg"], fg=self.theme["muted"],
                                    font=("Segoe UI", 10))
        self.header_date.pack(side="right", pady=8)
        self.page_host = tk.Frame(self.main, bg=self.theme["bg"])
        self.page_host.pack(fill="both", expand=True, padx=26, pady=(0, 22))

    def rebuild_theme(self):
        for widget in self.winfo_children():
            widget.destroy()
        self.theme = THEMES.get(DATA.get("theme"), THEMES["Purple"])
        self._build_shell()
        self.show_page(self.current_page)

    def card(self, parent, padx=16, pady=13):
        frame = tk.Frame(parent, bg=self.theme["panel"], highlightbackground=self.theme["border"],
                         highlightthickness=1)
        frame.pack(fill="x", pady=6)
        inner = tk.Frame(frame, bg=self.theme["panel"])
        inner.pack(fill="both", expand=True, padx=padx, pady=pady)
        return frame, inner

    def label(self, parent, text, size=11, color=None, bold=False, **kwargs):
        return tk.Label(parent, text=text, bg=kwargs.pop("bg", self.theme["bg"]),
                        fg=color or self.theme["fg"],
                        font=("Segoe UI", size, "bold" if bold else "normal"),
                        anchor=kwargs.pop("anchor", "w"), justify="left", **kwargs)

    def button(self, parent, text, command, primary=False, **kwargs):
        return tk.Button(parent, text=text, command=command,
                         bg=self.theme["accent"] if primary else self.theme["panel2"],
                         fg="#111827" if primary else self.theme["fg"],
                         activebackground=self.theme["accent"],
                         activeforeground="#111827" if primary else self.theme["fg"],
                         relief="flat", bd=0, padx=13, pady=8,
                         font=("Segoe UI", 10, "bold" if primary else "normal"), **kwargs)

    def show_page(self, page):
        self.current_page = page
        self.header_title.config(text=page)
        self.header_date.config(text=datetime.now().strftime("%A, %d %B %Y"))
        for name, button in self.nav_buttons.items():
            button.configure(bg=self.theme["panel2"] if name == page else self.theme["panel"],
                             fg=self.theme["accent"] if name == page else self.theme["fg"])
        for widget in self.page_host.winfo_children():
            widget.destroy()
        getattr(self, f"page_{page.lower()}")()

    def active_mode(self):
        today = date.today()
        key = today.isoformat()
        override = DATA.get("day_modes", {}).get(key)
        if override == "home":
            return "home_schedule", "Home day — school missed"
        if override == "school":
            return "weekday_schedule", "School day"
        if key in DATA.get("school_closures", []):
            return "holiday_schedule", "School closed — holiday timetable"
        if key in DATA.get("api_school_holidays", []):
            return "holiday_schedule", "Public holiday — holiday timetable"
        if date_is_weekend(today):
            return "weekend_schedule", "Weekend timetable"
        return "weekday_schedule", "School-day timetable"

    def page_dashboard(self):
        mode_key, mode_title = self.active_mode()
        heading = tk.Frame(self.page_host, bg=self.theme["bg"])
        heading.pack(fill="x", pady=(0, 8))
        self.label(heading, mode_title, 14, self.theme["accent"], True).pack(anchor="w")
        self.label(heading, "Your day, your pace. Adjust your plan whenever needed.",
                   10, self.theme["muted"]).pack(anchor="w", pady=(3, 0))

        if mode_key == "weekday_schedule":
            self.button(heading, "I missed school today", self.confirm_school_skipped,
                        primary=True).pack(anchor="e", pady=4)
        elif DATA.get("day_modes", {}).get(day_key()) == "home":
            self.button(heading, "Undo — use school-day timetable",
                        self.undo_school_skipped).pack(anchor="e", pady=4)

        # Counters
        _, inner = self.card(self.page_host)
        self.label(inner, "DAILY COUNTERS", 9, self.theme["muted"], True).pack(anchor="w")
        counts = DATA.setdefault("counts", {}).setdefault(day_key(), {})
        row = tk.Frame(inner, bg=self.theme["panel"])
        row.pack(fill="x", pady=(8, 0))
        for name in DATA.get("activities", []):
            value = counts.get(name, 0)
            cell = tk.Frame(row, bg=self.theme["panel2"])
            cell.pack(side="left", fill="both", expand=True, padx=4)
            tk.Label(cell, text=name, bg=self.theme["panel2"], fg=self.theme["muted"],
                     font=("Segoe UI", 9), wraplength=100).pack(padx=8, pady=(8, 0))
            tk.Label(cell, text=str(value), bg=self.theme["panel2"], fg=self.theme["fg"],
                     font=("Segoe UI", 20, "bold")).pack(pady=3)
            step = 250 if name.lower().startswith("water") else 1
            self.button(cell, f"+{step}", lambda n=name, s=step: self.change_count(n, s),
                        primary=True).pack(pady=(0, 8))
        self.button(inner, "+ Add my own counter", self.add_counter).pack(anchor="w", pady=(10, 0))

        # Timetable preview
        _, inner = self.card(self.page_host)
        self.label(inner, "TODAY'S TIMETABLE", 9, self.theme["muted"], True).pack(anchor="w")
        schedule = self.get_schedule(mode_key)
        now_text = datetime.now().strftime("%H:%M")
        upcoming = [(t, a) for t, a in schedule if t >= now_text]
        for clock, activity in (upcoming[:5] or schedule[-3:]):
            line = tk.Frame(inner, bg=self.theme["panel"])
            line.pack(fill="x", pady=3)
            tk.Label(line, text=clock, bg=self.theme["panel"], fg=self.theme["accent"],
                     width=7, anchor="w", font=("Segoe UI", 10, "bold")).pack(side="left")
            tk.Label(line, text=activity, bg=self.theme["panel"], fg=self.theme["fg"],
                     anchor="w", font=("Segoe UI", 10)).pack(side="left", padx=8)
        self.button(inner, "Edit timetable", lambda: self.show_page("Timetable")).pack(anchor="e", pady=(8, 0))

        # Nepali date strip
        _, inner = self.card(self.page_host)
        self.label(inner, "NEPALI PATRO", 9, self.theme["muted"], True).pack(anchor="w")
        cache = self.load_cached_json("today_" + day_key(), None, allow_expired=True)
        if cache:
            bs = cache.get("text", {}).get("bs", {}).get("en", "Nepali calendar data cached")
            self.label(inner, bs, 12, self.theme["fg"], True).pack(anchor="w", pady=4)
        else:
            self.label(inner, "Open Calendar to fetch today's Bikram Sambat date and events.",
                       10, self.theme["muted"]).pack(anchor="w", pady=4)
        self.button(inner, "Open Nepali calendar", lambda: self.show_page("Calendar")).pack(anchor="e")

    def confirm_school_skipped(self):
        yes = messagebox.askyesno(
            "Confirm school status",
            "Did you really miss school today?\n\n"
            "YES  — switch today's plan to your home-day timetable.\n"
            "NO   — keep your school-day timetable.",
            parent=self
        )
        if yes:
            DATA.setdefault("day_modes", {})[day_key()] = "home"
            save_data()
            self.show_page("Dashboard")

    def undo_school_skipped(self):
        if messagebox.askyesno("Change today's timetable",
                               "Switch back to the school-day timetable?", parent=self):
            DATA.setdefault("day_modes", {}).pop(day_key(), None)
            save_data()
            self.show_page("Dashboard")

    def change_count(self, name, step):
        counts = DATA.setdefault("counts", {}).setdefault(day_key(), {})
        counts[name] = max(0, int(counts.get(name, 0)) + step)
        save_data()
        self.show_page("Dashboard")

    def add_counter(self):
        name = simpledialog.askstring("New counter", "What would you like to count?", parent=self)
        if name and name.strip():
            clean = name.strip()[:35]
            if clean not in DATA.setdefault("activities", []):
                DATA["activities"].append(clean)
                save_data()
                self.show_page("Dashboard")

    def get_schedule(self, key):
        try:
            return parse_schedule(DATA.get(key, []))
        except ValueError:
            return []

    def page_timetable(self):
        top = tk.Frame(self.page_host, bg=self.theme["bg"])
        top.pack(fill="x")
        self.label(top, "Create separate plans for school days, missed-school days, weekends and holidays.",
                   10, self.theme["muted"]).pack(anchor="w", pady=(0, 10))
        choices = {
            "School day (Mon–Fri)": "weekday_schedule",
            "Home day (school missed)": "home_schedule",
            "Weekend (Sat–Sun)": "weekend_schedule",
            "Holiday / school closed": "holiday_schedule",
        }
        self.schedule_choice = tk.StringVar(value=next(
            (title for title, key in choices.items() if key == self.current_schedule_type),
            "School day (Mon–Fri)"
        ))
        bar = tk.Frame(self.page_host, bg=self.theme["bg"])
        bar.pack(fill="x", pady=5)
        combo = ttk.Combobox(bar, textvariable=self.schedule_choice, values=list(choices),
                             state="readonly", width=32)
        combo.pack(side="left")
        self.schedule_text = tk.Text(self.page_host, height=20, wrap="word",
                                     bg=self.theme["panel"], fg=self.theme["fg"],
                                     insertbackground=self.theme["fg"], relief="flat",
                                     font=("Consolas", 10), padx=12, pady=10)
        self.schedule_text.pack(fill="both", expand=True, pady=8)

        def load_choice(_event=None):
            self.current_schedule_type = choices[self.schedule_choice.get()]
            self.schedule_text.delete("1.0", "end")
            self.schedule_text.insert("1.0", "\n".join(DATA.get(self.current_schedule_type, [])))
        combo.bind("<<ComboboxSelected>>", load_choice)
        load_choice()
        help_text = "Format: 06:30 | Morning study     (24-hour time, one activity per line)"
        self.label(self.page_host, help_text, 9, self.theme["muted"]).pack(anchor="w")
        self.button(self.page_host, "Save this timetable", self.save_schedule,
                    primary=True).pack(anchor="e", pady=8)

    def save_schedule(self):
        lines = [x for x in self.schedule_text.get("1.0", "end").splitlines() if x.strip()]
        try:
            parsed = parse_schedule(lines)
        except ValueError as exc:
            messagebox.showerror("Check timetable format", str(exc), parent=self)
            return
        DATA[self.current_schedule_type] = [f"{t} | {a}" for t, a in parsed]
        save_data()
        messagebox.showinfo("Saved", "Your timetable has been saved.", parent=self)

    def page_trainer(self):
        self.label(self.page_host, "A simple guided session area. Choose a comfortable activity and rest whenever needed.",
                   10, self.theme["muted"]).pack(anchor="w", pady=(0, 10))
        _, inner = self.card(self.page_host)
        self.label(inner, "TRAINER", 10, self.theme["muted"], True).pack(anchor="w")
        self.label(inner, "1. Start gently  •  2. Use a comfortable pace  •  3. Take breaks  •  4. Stop when you need to",
                   12).pack(anchor="w", pady=8)
        self.label(inner, "This app records your activity; it does not set required exercise targets.",
                   9, self.theme["muted"]).pack(anchor="w")
        _, inner2 = self.card(self.page_host)
        self.label(inner2, "REST TIMER", 10, self.theme["muted"], True).pack(anchor="w")
        self.rest_seconds = 60
        self.timer_label = self.label(inner2, "01:00", 28, self.theme["fg"], True)
        self.timer_label.pack(anchor="w", pady=8)
        row = tk.Frame(inner2, bg=self.theme["panel"])
        row.pack(anchor="w")
        self.button(row, "Start 60-second rest", self.start_rest, primary=True).pack(side="left", padx=(0, 6))
        self.button(row, "Reset", self.reset_rest).pack(side="left")
        self.rest_running = False

    def start_rest(self):
        self.rest_seconds = 60
        self.rest_running = True
        self.update_rest_label()

    def reset_rest(self):
        self.rest_running = False
        self.rest_seconds = 60
        self.update_rest_label()

    def update_rest_label(self):
        if hasattr(self, "timer_label") and self.timer_label.winfo_exists():
            self.timer_label.config(text=f"{self.rest_seconds//60:02}:{self.rest_seconds%60:02}")
        if self.rest_running:
            if self.rest_seconds <= 0:
                self.rest_running = False
                self.show_notification("Rest timer", "Your rest timer is finished.")
                return
            self.rest_seconds -= 1
            self.after(1000, self.update_rest_label)

    def page_notes(self):
        self.label(self.page_host, "Keep reminders, school tasks, ideas or anything you want to remember.",
                   10, self.theme["muted"]).pack(anchor="w", pady=(0, 10))
        self.notes_box = tk.Text(self.page_host, wrap="word", bg=self.theme["panel"],
                                 fg=self.theme["fg"], insertbackground=self.theme["fg"],
                                 relief="flat", padx=14, pady=12,
                                 font=("Segoe UI", 11))
        self.notes_box.pack(fill="both", expand=True)
        self.notes_box.insert("1.0", DATA.get("notes", ""))
        self.button(self.page_host, "Save notes", self.save_notes,
                    primary=True).pack(anchor="e", pady=8)

    def save_notes(self):
        DATA["notes"] = self.notes_box.get("1.0", "end").rstrip()
        save_data()
        messagebox.showinfo("Saved", "Your notes have been saved.", parent=self)

    def _cache_path(self, key):
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", key)
        return CACHE_DIR / f"{safe}.json"

    def load_cached_json(self, key, url, allow_expired=False):
        path = self._cache_path(key)
        if path.exists():
            try:
                age = datetime.now().timestamp() - path.stat().st_mtime
                if allow_expired or age < 24 * 3600:
                    return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        if not url:
            return None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DailyFit/1.0 (personal calendar)"})
            with urllib.request.urlopen(req, timeout=12) as response:
                result = json.loads(response.read().decode("utf-8"))
            path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return result
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None

    def refresh_calendar_background(self):
        # Refresh the current Nepali date and public-holiday list quietly.
        def worker():
            today_info = self.load_cached_json(
                "today_" + day_key(), TRISAMBAT_API + "/today.json"
            )
            month = date.today()
            month_info = self.load_cached_json(
                f"ad_{month.year}_{month.month:02d}",
                f"{TRISAMBAT_API}/ad/{month.year}/{month.month:02d}.json"
            )
            holidays = []
            for item in (month_info or {}).get("days", []):
                ad = item.get("ad")
                events = item.get("events", []) or []
                if ad and any(
                    isinstance(event, dict)
                    and event.get("holiday") == "national"
                    and event.get("verified")
                    for event in events
                ):
                    holidays.append(ad)
            def apply_result():
                DATA["api_school_holidays"] = holidays
                save_data()
                if self.current_page == "Dashboard":
                    self.show_page("Dashboard")
            self.after(0, apply_result)
        threading.Thread(target=worker, daemon=True).start()

    def page_calendar(self):
        self.label(self.page_host, "Bikram Sambat date, festivals and public-holiday references. Internet is needed to refresh.",
                   10, self.theme["muted"]).pack(anchor="w", pady=(0, 10))
        self.calendar_status = self.label(self.page_host, "Loading Nepali Patro…", 12, self.theme["accent"], True)
        self.calendar_status.pack(anchor="w", pady=4)
        nav = tk.Frame(self.page_host, bg=self.theme["bg"])
        nav.pack(fill="x", pady=4)
        self.button(nav, "◀ Previous month", lambda: self.change_calendar_month(-1)).pack(side="left")
        self.month_title = self.label(nav, self.calendar_month.strftime("%B %Y"), 12, self.theme["fg"], True)
        self.month_title.pack(side="left", padx=14)
        self.button(nav, "Next month ▶", lambda: self.change_calendar_month(1)).pack(side="left")
        self.button(nav, "Refresh", lambda: self.load_calendar(force=True)).pack(side="right")

        self.calendar_list = tk.Listbox(self.page_host, height=16, bg=self.theme["panel"],
                                        fg=self.theme["fg"], selectbackground=self.theme["accent"],
                                        selectforeground="#111827", relief="flat",
                                        font=("Segoe UI", 10), activestyle="none")
        self.calendar_list.pack(fill="both", expand=True, pady=8)
        row = tk.Frame(self.page_host, bg=self.theme["bg"])
        row.pack(fill="x")
        self.button(row, "Mark selected date as school closed", self.add_calendar_closure,
                    primary=True).pack(side="left")
        self.button(row, "Remove selected manual closure", self.remove_calendar_closure).pack(side="left", padx=8)
        link = tk.Label(self.page_host, text="Calendar data by Trisambat • Open website",
                        bg=self.theme["bg"], fg=self.theme["accent"], cursor="hand2",
                        font=("Segoe UI", 9, "underline"))
        link.pack(anchor="w", pady=(8, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open(TRISAMBAT + "/developers?lang=en"))
        self.load_calendar()

    def change_calendar_month(self, offset):
        first = self.calendar_month
        month_index = first.month - 1 + offset
        year = first.year + month_index // 12
        month = month_index % 12 + 1
        self.calendar_month = date(year, month, 1)
        self.month_title.config(text=self.calendar_month.strftime("%B %Y"))
        self.load_calendar()

    def load_calendar(self, force=False):
        if self.calendar_loading:
            return
        self.calendar_loading = True
        self.calendar_status.config(text="Fetching calendar data…")
        month = self.calendar_month
        key = f"ad_{month.year}_{month.month:02d}"
        url = f"{TRISAMBAT_API}/ad/{month.year}/{month.month:02d}.json"
        def worker():
            data_month = None if force else self.load_cached_json(key, None)
            if data_month is None:
                data_month = self.load_cached_json(key, url)
            today_data = self.load_cached_json("today_" + day_key(),
                                               TRISAMBAT_API + "/today.json")
            self.after(0, lambda: self.calendar_loaded(data_month, today_data))
        threading.Thread(target=worker, daemon=True).start()

    def calendar_loaded(self, month_data, today_data):
        self.calendar_loading = False
        self.calendar_list.delete(0, "end")
        self.month_days = []
        today_label = ""
        if today_data:
            today_label = today_data.get("text", {}).get("bs", {}).get("en", "")
            events = today_data.get("events", []) or []
            event_names = [self.event_name(e) for e in events]
            holiday_text = " • Public holiday" if today_data.get("holiday") else ""
            self.calendar_status.config(text=f"Today: {today_label}{holiday_text}")
        else:
            self.calendar_status.config(text="Calendar unavailable — showing cached data when possible.")
        days = (month_data or {}).get("days", [])
        for item in days:
            ad = item.get("ad", "")
            bs = item.get("text", {}).get("bs", {}).get("en", "")
            weekday_num = item.get("weekday", -1)
            weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][weekday_num] if 0 <= weekday_num <= 6 else ""
            events = item.get("events", []) or []
            names = [self.event_name(e) for e in events]
            national = any(isinstance(e, dict) and e.get("holiday") == "national" and e.get("verified") for e in events)
            if national and ad and ad not in DATA.setdefault("api_school_holidays", []):
                DATA["api_school_holidays"].append(ad)
            is_sat_sun = False
            try:
                is_sat_sun = date.fromisoformat(ad).weekday() >= 5
            except ValueError:
                pass
            status = "School closure" if national else ("Weekend" if is_sat_sun else "")
            if ad in DATA.get("school_closures", []):
                status = "Your school closure"
            line = f"{ad}   |   {weekday:<3}   |   {bs}"
            if names:
                line += "   |   " + ", ".join(names)
            if status:
                line += "   |   [" + status + "]"
            self.calendar_list.insert("end", line)
            self.month_days.append(ad)
        if not days:
            self.calendar_list.insert("end", "No month data returned. Check your internet connection.")
        save_data()

    @staticmethod
    def event_name(event):
        if isinstance(event, str):
            return event
        if isinstance(event, dict):
            return (event.get("name") or event.get("title") or
                    event.get("text", {}).get("en") or event.get("name_en") or "Calendar event")
        return "Calendar event"

    def selected_calendar_date(self):
        selection = self.calendar_list.curselection()
        if not selection:
            return None
        index = selection[0]
        return self.month_days[index] if 0 <= index < len(self.month_days) else None

    def add_calendar_closure(self):
        selected = self.selected_calendar_date()
        if not selected:
            messagebox.showinfo("Select a date", "Select a date from the calendar first.", parent=self)
            return
        if selected not in DATA.setdefault("school_closures", []):
            DATA["school_closures"].append(selected)
            save_data()
        messagebox.showinfo("Saved", f"{selected} marked as a school-closed day.", parent=self)
        self.show_page("Calendar")

    def remove_calendar_closure(self):
        selected = self.selected_calendar_date()
        if not selected:
            return
        if selected in DATA.get("school_closures", []):
            DATA["school_closures"].remove(selected)
            save_data()
            self.show_page("Calendar")
        else:
            messagebox.showinfo("Not a manual closure", "This date is not in your manual closure list.",
                                parent=self)

    def page_settings(self):
        self.label(self.page_host, "Personal settings stay on this computer. Your logs, notes and timetable are never uploaded.",
                   10, self.theme["muted"]).pack(anchor="w", pady=(0, 10))
        _, inner = self.card(self.page_host)
        self.label(inner, "APPEARANCE", 9, self.theme["muted"], True).pack(anchor="w")
        for name in THEMES:
            self.button(inner, name, lambda t=name: self.set_theme(t),
                        primary=(DATA.get("theme") == name)).pack(side="left", padx=(0, 7), pady=8)

        _, inner = self.card(self.page_host)
        self.label(inner, "TIMETABLE REMINDERS", 9, self.theme["muted"], True).pack(anchor="w")
        self.reminder_var = tk.BooleanVar(value=DATA.get("reminders_enabled", True))
        tk.Checkbutton(inner, text="Notify me when a scheduled session starts",
                       variable=self.reminder_var, command=self.save_reminder_setting,
                       bg=self.theme["panel"], fg=self.theme["fg"],
                       selectcolor=self.theme["panel2"], activebackground=self.theme["panel"],
                       activeforeground=self.theme["fg"]).pack(anchor="w", pady=6)
        self.label(inner, "DailyFit checks the timetable locally. It does not send your schedule anywhere.",
                   9, self.theme["muted"]).pack(anchor="w")

        _, inner = self.card(self.page_host)
        self.label(inner, "AUTOMATIC UPDATES", 9, self.theme["muted"], True).pack(anchor="w")
        self.label(inner, "GitHub repository (public), format: username/repository", 9,
                   self.theme["muted"]).pack(anchor="w", pady=(8, 2))
        self.repo_var = tk.StringVar(value=DATA.get("github_repo", ""))
        tk.Entry(inner, textvariable=self.repo_var, width=42, bg=self.theme["panel2"],
                 fg=self.theme["fg"], insertbackground=self.theme["fg"], relief="flat").pack(anchor="w", ipady=6)
        row = tk.Frame(inner, bg=self.theme["panel"])
        row.pack(anchor="w", pady=8)
        self.button(row, "Save repository", self.save_repo, primary=True).pack(side="left", padx=(0, 7))
        self.button(row, "Check for updates now", lambda: self.check_for_updates(silent=False)).pack(side="left")
        self.label(inner, f"Installed version: {APP_VERSION}", 9, self.theme["muted"]).pack(anchor="w")
        self.label(inner, "Self-update activates after the project has a GitHub Release containing DailyFit.exe and DailyFit.exe.sha256.",
                   9, self.theme["muted"], wraplength=700).pack(anchor="w", pady=(4, 0))

        _, inner = self.card(self.page_host)
        self.label(inner, "WINDOWS STARTUP", 9, self.theme["muted"], True).pack(anchor="w")
        self.label(inner, "Start DailyFit after you sign in to Windows. Closing the window minimizes it; choose Exit in Settings to stop reminders.",
                   9, self.theme["muted"], wraplength=700).pack(anchor="w", pady=5)
        self.button(inner, "Enable Windows startup", self.enable_startup).pack(side="left", padx=(0, 7))
        self.button(inner, "Disable Windows startup", self.disable_startup).pack(side="left")
        self.button(self.page_host, "Exit DailyFit completely", self.exit_app).pack(anchor="e", pady=10)

    def set_theme(self, name):
        DATA["theme"] = name
        save_data()
        self.rebuild_theme()

    def save_reminder_setting(self):
        DATA["reminders_enabled"] = bool(self.reminder_var.get())
        save_data()

    def save_repo(self):
        repo = self.repo_var.get().strip()
        if repo and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            messagebox.showerror("Repository format", "Enter it like username/DailyFit.", parent=self)
            return
        DATA["github_repo"] = repo
        save_data()
        messagebox.showinfo("Saved", "Update repository saved.", parent=self)

    def enable_startup(self):
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            messagebox.showinfo("Build required", "Windows startup is enabled after installing the packaged EXE.",
                                parent=self)
            return
        try:
            import winreg
            command = f'"{sys.executable}" --background'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "DailyFit", 0, winreg.REG_SZ, command)
            DATA["startup_enabled"] = True
            save_data()
            messagebox.showinfo("Startup enabled", "DailyFit will start when you sign in to Windows.",
                                parent=self)
        except OSError as exc:
            messagebox.showerror("Startup error", str(exc), parent=self)

    def disable_startup(self):
        if sys.platform != "win32":
            return
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, "DailyFit")
                except FileNotFoundError:
                    pass
            DATA["startup_enabled"] = False
            save_data()
            messagebox.showinfo("Startup disabled", "DailyFit will no longer start automatically.",
                                parent=self)
        except OSError as exc:
            messagebox.showerror("Startup error", str(exc), parent=self)

    def minimize_to_taskbar(self):
        # Keep reminders active; the app remains available from its taskbar button.
        self.iconify()

    def exit_app(self):
        if messagebox.askyesno("Exit DailyFit", "Exit completely? Timetable reminders will stop until reopened.",
                               parent=self):
            self.destroy()

    def show_notification(self, title, message):
        try:
            from winotify import Notification, audio
            toast = Notification(app_id="DailyFit", title=title, msg=message, duration="short")
            try:
                toast.set_audio(audio.Default, loop=False)
            except Exception:
                pass
            toast.show()
        except Exception:
            try:
                self.bell()
            except Exception:
                pass
            # Small non-modal popup rather than a blocking message box.
            try:
                popup = tk.Toplevel(self)
                popup.title(title)
                popup.configure(bg=self.theme["panel"])
                popup.attributes("-topmost", True)
                tk.Label(popup, text=title, bg=self.theme["panel"], fg=self.theme["fg"],
                         font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
                tk.Label(popup, text=message, bg=self.theme["panel"], fg=self.theme["fg"],
                         wraplength=300, justify="left").pack(anchor="w", padx=14, pady=(0, 12))
                popup.after(7000, popup.destroy)
            except tk.TclError:
                pass

    def reminder_tick(self):
        try:
            if DATA.get("reminders_enabled", True):
                now = datetime.now()
                current = now.strftime("%H:%M")
                key, _title = self.active_mode()
                schedule = self.get_schedule(key)
                for clock, activity in schedule:
                    event_id = f"{now.date().isoformat()}_{key}_{clock}"
                    if clock == current and event_id not in self.reminded:
                        self.reminded.add(event_id)
                        self.show_notification("DailyFit • Next session", f"Your next session: {activity}")
            # Keep memory bounded.
            if len(self.reminded) > 100:
                self.reminded.clear()
        except Exception:
            pass
        self.after(15000, self.reminder_tick)

    def periodic_update_check(self):
        self.check_for_updates(silent=True, automatic=True)
        self.after(6 * 60 * 60 * 1000, self.periodic_update_check)

    def check_for_updates(self, silent=False, automatic=False):
        repo = DATA.get("github_repo", "").strip()
        if not repo:
            if not silent:
                messagebox.showinfo("Update setup", "Add your public GitHub repository in Settings first.",
                                    parent=self)
            return
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            if not silent:
                messagebox.showerror("Repository", "The repository must look like username/repository.",
                                     parent=self)
            return
        def worker():
            try:
                url = f"https://api.github.com/repos/{repo}/releases/latest"
                req = urllib.request.Request(url, headers={
                    "Accept": "application/vnd.github+json", "User-Agent": "DailyFit-Updater"
                })
                with urllib.request.urlopen(req, timeout=15) as response:
                    release = json.loads(response.read().decode("utf-8"))
                tag = str(release.get("tag_name", "")).lstrip("vV")
                if version_tuple(tag) <= version_tuple(APP_VERSION):
                    result = ("current", tag)
                else:
                    assets = {a.get("name"): a.get("browser_download_url")
                              for a in release.get("assets", [])}
                    exe_url = assets.get("DailyFit.exe")
                    hash_url = assets.get("DailyFit.exe.sha256")
                    if not exe_url or not hash_url:
                        result = ("missing_assets", tag)
                    else:
                        result = ("available", tag, exe_url, hash_url)
            except Exception as exc:
                result = ("error", str(exc))
            self.after(0, lambda: self.handle_update_result(result, silent))
        threading.Thread(target=worker, daemon=True).start()

    def handle_update_result(self, result, silent):
        status = result[0]
        if status == "current":
            if not silent:
                messagebox.showinfo("DailyFit is up to date", f"You have v{APP_VERSION}. Latest is v{result[1]}.",
                                    parent=self)
        elif status == "missing_assets":
            if not silent:
                messagebox.showwarning("Release not ready",
                    f"GitHub has release {result[1]}, but it does not contain the EXE and SHA-256 files yet.",
                    parent=self)
        elif status == "available":
            if not getattr(sys, "frozen", False) or sys.platform != "win32":
                if not silent:
                    messagebox.showinfo("Update available",
                        f"Version {result[1]} is available. Install the Windows EXE build to enable one-click self-updating.",
                        parent=self)
                return
            if not silent and not messagebox.askyesno("Update available",
                    f"DailyFit v{result[1]} is available. Download and install it now?", parent=self):
                return
            self.download_and_apply_update(result[1], result[2], result[3])
        elif status == "error":
            if not silent:
                messagebox.showerror("Update check failed", result[1], parent=self)

    def download_and_apply_update(self, tag, exe_url, hash_url):
        try:
            headers = {"User-Agent": "DailyFit-Updater"}
            def get_bytes(url):
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as response:
                    return response.read()
            expected_text = get_bytes(hash_url).decode("utf-8").strip()
            expected_hash = expected_text.split()[0].lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                raise ValueError("The release checksum file is invalid.")
            payload = get_bytes(exe_url)
            actual_hash = hashlib.sha256(payload).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError("The downloaded update failed its SHA-256 check.")
            current_exe = Path(sys.executable).resolve()
            if not current_exe.is_file():
                raise OSError("Could not locate the installed EXE.")
            temp_exe = Path(tempfile.gettempdir()) / "DailyFit_update.exe"
            temp_exe.write_bytes(payload)
            bat = Path(tempfile.gettempdir()) / "DailyFit_apply_update.bat"
            bat.write_text(
                "@echo off\r\n"
                "setlocal\r\n"
                "set \"SRC=" + str(temp_exe) + "\"\r\n"
                "set \"DST=" + str(current_exe) + "\"\r\n"
                "timeout /t 2 /nobreak >nul\r\n"
                "set /a tries=0\r\n"
                ":retry\r\n"
                "copy /Y \"%SRC%\" \"%DST%\" >nul\r\n"
                "if not errorlevel 1 goto done\r\n"
                "set /a tries+=1\r\n"
                "if %tries% GEQ 20 goto failed\r\n"
                "timeout /t 1 /nobreak >nul\r\n"
                "goto retry\r\n"
                ":done\r\n"
                "start \"\" \"%DST%\"\r\n"
                "del \"%SRC%\" >nul 2>&1\r\n"
                "del \"%~f0\" >nul 2>&1\r\n"
                "exit /b 0\r\n"
                ":failed\r\n"
                "del \"%SRC%\" >nul 2>&1\r\n"
                "del \"%~f0\" >nul 2>&1\r\n"
                "exit /b 1\r\n",
                encoding="utf-8"
            )
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(["cmd.exe", "/c", str(bat)], creationflags=flags,
                             close_fds=True)
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Update failed", str(exc), parent=self)

if __name__ == "__main__":
    app = DailyFit()
    app.mainloop()
