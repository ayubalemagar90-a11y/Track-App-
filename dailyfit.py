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
import time
from datetime import date, datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

try:
    from nepdate import NepaliDate
    from nepdate_patro import info as patro_info
except ImportError:
    NepaliDate = patro_info = None

try:
    from version_info import APP_VERSION
except Exception:
    APP_VERSION = "0.1.0"

APP_NAME = "DailyFit"
NEPALI_MONTHS_EN = {
    1: "Baisakh", 2: "Jestha", 3: "Asar", 4: "Shrawan", 5: "Bhadra",
    6: "Ashwin", 7: "Kartik", 8: "Mangsir", 9: "Poush", 10: "Magh",
    11: "Falgun", 12: "Chaitra",
}
NEPALI_MONTHS_NE = {
    1: "बैशाख", 2: "जेठ", 3: "असार", 4: "साउन", 5: "भदौ",
    6: "असोज", 7: "कार्तिक", 8: "मंसिर", 9: "पुष", 10: "माघ",
    11: "फागुन", 12: "चैत",
}
NEPALI_MONTHS = NEPALI_MONTHS_NE
WEEKDAYS_EN = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
WEEKDAYS_NE = ["आइत", "सोम", "मंगल", "बुध", "बिही", "शुक्र", "शनि"]

def local_calendar_month(year, month):
    """Build one BS month from the bundled, free NepDate data; no calendar API is used."""
    if NepaliDate is None or patro_info is None:
        return None
    first = NepaliDate(int(year), int(month), 1)
    ad_day = first.to_date()
    last = first.last_of_month().to_date()
    days = []
    while ad_day <= last:
        bs_day = NepaliDate.from_date(ad_day)
        bs_key = (bs_day.year, bs_day.month, bs_day.day)
        # Date conversion covers more years than the bundled Patro event data.
        has_patro_data = (2077, 1, 1) <= bs_key <= (2084, 8, 20)
        day_info = patro_info(bs_day) if has_patro_data else None
        events = [{
            "name": event.en, "name_np": event.np,
            "text": {"en": event.en, "ne": event.np},
            "holiday": "national" if day_info.is_public_holiday else None,
        } for event in (day_info.events if day_info else [])]
        tithi = day_info.tithi if day_info else None
        bs_ne = f"{bs_day.day} {NEPALI_MONTHS_NE[bs_day.month]} {bs_day.year}, {WEEKDAYS_NE[(ad_day.weekday()+1)%7]}बार"
        bs_en = f"{bs_day.day} {NEPALI_MONTHS_EN[bs_day.month]} {bs_day.year}, {ad_day.strftime('%A')}"
        days.append({
            "ad": ad_day.isoformat(),
            "bs": {"year": bs_day.year, "month": bs_day.month, "day": bs_day.day},
            "weekday": (ad_day.weekday() + 1) % 7,
            "holiday": bool(day_info and day_info.is_public_holiday),
            "events": events,
            "text": {
                "bs": {"ne": bs_ne, "en": bs_en},
                "tithi": {"ne": tithi.np if tithi else "", "en": tithi.en if tithi else ""},
            },
        })
        ad_day += timedelta(days=1)
    return {"year": int(year), "month": int(month), "days": days}
USER_HOME = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
APP_DIR = USER_HOME / "DailyFit"
APP_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = APP_DIR / "data.json"
BACKUP_DIR = APP_DIR / "backups"

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
    "github_repo": "ayubalemagar90-a11y/Track-App-",
    "calendar_language": "ne",
    "calendar_view_mode": "month",
    "week_starts_monday": False,
    "time_format": "24h",
    "tasks": [],
    "habits": [],
    "habit_logs": {},
    "calendar_events": [],
    "notes_entries": [],
    "daily_goals": [],
    "weekly_goals": [],
    "mood_logs": {},
    "reflections": {},
    "sleep_logs": {},
    "quiet_hours": {"enabled": False, "start": "21:00", "end": "07:00"},
    "wellness_enabled": True,
    "exercise_goal": 3,
    "exercise_sessions": [],
    "exercise_reminder_enabled": False,
    "exercise_reminder_time": "17:00",
    "focus_sessions": {},
    "water_reminders_enabled": False,
    "break_reminders_enabled": False,
    "last_wellness_reminder": "",
    "backup_dir": "",
    "window_geometry": "",
    "setup_complete": False,
}

def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            merged = DEFAULTS.copy()
            merged.update(data if isinstance(data, dict) else {})
            quiet_hours = merged.get("quiet_hours")
            if not isinstance(quiet_hours, dict):
                quiet_hours = {}
            merged["quiet_hours"] = {**DEFAULTS["quiet_hours"], **quiet_hours}
            for list_key in ("tasks", "habits", "calendar_events", "notes_entries", "daily_goals", "weekly_goals"):
                if not isinstance(merged.get(list_key), list):
                    merged[list_key] = []
            if merged.get("notes") and not merged.get("notes_entries"):
                merged["notes_entries"] = [{
                    "id": str(int(time.time())), "title": "My notes", "category": "General",
                    "tags": "", "body": merged["notes"], "pinned": True,
                    "created": date.today().isoformat(),
                }]
            # Replace the short timetable entered in the earlier app with the original
            # DailyFit plan; leave any other custom schedules untouched.
            previous_short_plan = [
                "09:00 | School",
                "16:30 | Rest and snack",
                "17:00 | Study",
                "19:00 | Dinner",
                "20:00 | Revision",
                "21:30 | Sleep",
            ]
            saved_schedule = merged.get("weekday_schedule")
            if isinstance(saved_schedule, list) and [
                str(line).strip() for line in saved_schedule if str(line).strip()
            ] == previous_short_plan:
                merged["weekday_schedule"] = DEFAULTS["weekday_schedule"].copy()
            if not merged.get("github_repo"):
                merged["github_repo"] = DEFAULTS["github_repo"]
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

def parse_schedule(lines, include_duration=False):
    parsed = []
    occupied = set()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) not in {2, 3}:
            raise ValueError(f"Use HH:MM | Activity | optional duration in minutes: {line}")
        clock, activity = parts[0], parts[1]
        datetime.strptime(clock.strip(), "%H:%M")
        activity = activity.strip()
        if not activity:
            raise ValueError("Activity names cannot be empty.")
        if clock in occupied:
            raise ValueError(f"Two activities cannot start at the same time: {clock}")
        occupied.add(clock)
        duration = None
        if len(parts) == 3 and parts[2]:
            try:
                duration = int(parts[2])
                if not 1 <= duration <= 720:
                    raise ValueError
            except ValueError:
                raise ValueError("Duration must be a whole number from 1 to 720 minutes.")
        parsed.append((clock, activity, duration))
    parsed.sort(key=lambda x: x[0])
    for current, following in zip(parsed, parsed[1:]):
        duration = current[2]
        if duration is not None:
            current_minutes = int(current[0][:2]) * 60 + int(current[0][3:])
            next_minutes = int(following[0][:2]) * 60 + int(following[0][3:])
            if current_minutes + duration > next_minutes:
                raise ValueError(f"'{current[1]}' overlaps the next activity at {following[0]}.")
    return parsed if include_duration else [(clock, activity) for clock, activity, _duration in parsed]

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
        self.geometry(DATA.get("window_geometry") or "1060x740")
        self.minsize(800, 590)
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_taskbar)
        self.current_page = "Dashboard"
        self.notes_dirty = False
        self.schedule_dirty = False
        self.current_schedule_type = "weekday_schedule"
        self.schedule_editor = None
        saved_calendar_month = DATA.get("calendar_view_bs", {})
        self.calendar_bs_year = saved_calendar_month.get("year")
        self.calendar_bs_month = saved_calendar_month.get("month")
        self.selected_calendar_ad = None
        self.month_days = []
        self.calendar_loading = False
        self.calendar_data_by_ad = {}
        self.calendar_view_mode = DATA.get("calendar_view_mode", "month")
        self.reminded = set()
        self.last_update_check = None
        self.focus_remaining = 0
        self.focus_running = False
        self.last_backup_date = ""
        self.theme = THEMES.get(DATA.get("theme"), THEMES["Purple"])
        self._build_shell()
        self.show_page("Dashboard")
        self.after(5000, self.reminder_tick)
        self.after(12000, lambda: self.check_for_updates(silent=True, automatic=True))
        if DATA.get("pending_release_notes"):
            self.after(1500, self.show_pending_release_notes)
        self.after(2500, self.refresh_calendar_background)
        self.after(8000, self.automatic_backup)
        self.after(3600000, self.periodic_update_check)
        self.bind_all("<Alt-Left>", lambda _e: self.calendar_keyboard_move(-1), add="+")
        self.bind_all("<Alt-Right>", lambda _e: self.calendar_keyboard_move(1), add="+")
        self.bind_all("<Alt-Home>", lambda _e: self.calendar_today() if self.current_page == "Calendar" else None, add="+")
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
            ("Dashboard", "⌂"), ("Timetable", "▦"), ("Tasks", "✓"),
            ("Habits", "★"), ("History", "◷"), ("Trainer", "◉"), ("Calendar", "▣"),
            ("Notes", "✎"), ("Settings", "⚙")
        ]:
            b = tk.Button(self.sidebar, text=f"  {symbol}   {name}", anchor="w",
                          command=lambda n=name: self.show_page(n),
                          bg=self.theme["panel"], fg=self.theme["fg"],
                          activebackground=self.theme["panel2"],
                          activeforeground=self.theme["fg"], relief="flat",
                          bd=0, padx=14, pady=12, font=("Segoe UI", 11))
            b.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[name] = b
            self.add_tooltip(b, f"Open the {name} page")
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
        page_container = tk.Frame(self.main, bg=self.theme["bg"])
        page_container.pack(fill="both", expand=True, padx=(26, 14), pady=(0, 16))
        self.page_scroll_canvas = tk.Canvas(page_container, bg=self.theme["bg"], highlightthickness=0)
        page_scroll = ttk.Scrollbar(page_container, orient="vertical", command=self.page_scroll_canvas.yview)
        self.page_scroll_canvas.configure(yscrollcommand=page_scroll.set)
        self.page_scroll_canvas.pack(side="left", fill="both", expand=True)
        page_scroll.pack(side="right", fill="y")
        self.page_host = tk.Frame(self.page_scroll_canvas, bg=self.theme["bg"])
        self.page_window = self.page_scroll_canvas.create_window((0, 0), window=self.page_host, anchor="nw")
        self.page_host.bind("<Configure>", lambda _e: self.page_scroll_canvas.configure(scrollregion=self.page_scroll_canvas.bbox("all")))
        self.page_scroll_canvas.bind("<Configure>", lambda event: self.page_scroll_canvas.itemconfigure(self.page_window, width=event.width))
        self.page_scroll_canvas.bind("<MouseWheel>", lambda event: self.page_scroll_canvas.yview_scroll(-1 * int(event.delta / 120), "units"))

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

    def add_tooltip(self, widget, message):
        state = {"window": None}
        def show(_event=None):
            if state["window"] is not None or not widget.winfo_exists():
                return
            tip = tk.Toplevel(self)
            tip.wm_overrideredirect(True)
            tip.configure(bg=self.theme["panel2"])
            x = widget.winfo_rootx() + 8
            y = widget.winfo_rooty() + widget.winfo_height() + 3
            tip.geometry(f"+{x}+{y}")
            tk.Label(tip, text=message, bg=self.theme["panel2"], fg=self.theme["fg"],
                     font=("Segoe UI", 9), padx=8, pady=4).pack()
            state["window"] = tip
        def hide(_event=None):
            if state["window"] is not None:
                try:
                    state["window"].destroy()
                except tk.TclError:
                    pass
                state["window"] = None
        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")

    def show_page(self, page):
        if self.current_page == "Notes" and page != "Notes" and self.notes_dirty:
            choice = messagebox.askyesnocancel("Unsaved note", "Save your note before leaving this page?", parent=self)
            if choice is None:
                return
            if choice:
                self.save_notes()
                if self.notes_dirty:
                    return
            else:
                self.notes_dirty = False
        if self.current_page == "Timetable" and page != "Timetable" and self.schedule_dirty:
            choice = messagebox.askyesnocancel("Unsaved timetable", "Save your timetable before leaving this page?", parent=self)
            if choice is None:
                return
            if choice:
                self.save_schedule()
                if self.schedule_dirty:
                    return
            else:
                self.schedule_dirty = False
        self.current_page = page
        self.header_title.config(text=page)
        self.header_date.config(text=datetime.now().strftime("%A, %d %B %Y"))
        for name, button in self.nav_buttons.items():
            button.configure(bg=self.theme["panel2"] if name == page else self.theme["panel"],
                             fg=self.theme["accent"] if name == page else self.theme["fg"])
        for widget in self.page_host.winfo_children():
            widget.destroy()
        self.page_scroll_canvas.yview_moveto(0)
        getattr(self, f"page_{page.lower()}")()

    def active_mode(self):
        today = date.today()
        key = today.isoformat()
        override = DATA.get("day_modes", {}).get(key)
        if override == "home":
            return "home_schedule", "Home day — school missed"
        if override == "school":
            return "weekday_schedule", "School day"
        if override == "weekend":
            return "weekend_schedule", "Weekend plan"
        if override == "holiday":
            return "holiday_schedule", "Holiday plan"
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

        if not DATA.get("setup_complete"):
            _, setup = self.card(self.page_host)
            self.label(setup, "WELCOME TO DAILYFIT", 10, self.theme["muted"], True).pack(anchor="w")
            self.label(setup, "Your suggested school, home, weekend, and holiday plans are ready. Personal records stay on this computer.",
                       10, self.theme["fg"], wraplength=670).pack(anchor="w", pady=5)
            self.button(setup, "Quick setup guide", self.first_run_setup, primary=True).pack(anchor="w")

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
            progress_key = f"{day_key()}|{mode_key}|{clock}"
            is_done = progress_key in DATA.setdefault("completed_schedule", [])
            tk.Label(line, text=self.display_clock(clock), bg=self.theme["panel"], fg=self.theme["accent"],
                     width=7, anchor="w", font=("Segoe UI", 10, "bold")).pack(side="left")
            tk.Label(line, text=activity, bg=self.theme["panel"], fg=self.theme["fg"],
                     anchor="w", font=("Segoe UI", 10)).pack(side="left", padx=8)
            self.button(line, "Done" if is_done else "Mark done",
                        lambda k=mode_key, t=clock: self.toggle_schedule_complete(k, t)).pack(side="right", padx=2)
            self.button(line, "Skip / move",
                        lambda k=mode_key, t=clock, a=activity: self.skip_or_reschedule(k, t, a)).pack(side="right", padx=2)
        self.button(inner, "Edit timetable", lambda: self.show_page("Timetable")).pack(anchor="e", pady=(8, 0))

        current = [(clock, activity) for clock, activity in schedule if clock <= now_text]
        if current:
            _, current_inner = self.card(self.page_host)
            self.label(current_inner, "CURRENT / MOST RECENT SESSION", 9, self.theme["muted"], True).pack(anchor="w")
            self.label(current_inner, f"{self.display_clock(current[-1][0])}  •  {current[-1][1]}", 11, self.theme["fg"], True).pack(anchor="w", pady=3)

        # Nepali date strip
        _, inner = self.card(self.page_host)
        self.label(inner, "NEPALI PATRO", 9, self.theme["muted"], True).pack(anchor="w")
        if NepaliDate is not None:
            bs_today = NepaliDate.from_date(date.today())
            month_label = NEPALI_MONTHS_NE.get(bs_today.month, "")
            today_text = f"{self.nepali_digits(bs_today.year)} {month_label} {self.nepali_digits(bs_today.day)}"
            self.label(inner, today_text, 12, self.theme["fg"], True).pack(anchor="w", pady=4)
        else:
            self.label(inner, "Install the free NepDate calendar package to show BS dates.",
                       10, self.theme["muted"]).pack(anchor="w", pady=4)
        self.button(inner, "Open Nepali calendar", lambda: self.show_page("Calendar")).pack(anchor="e")

    def first_run_setup(self):
        messagebox.showinfo("DailyFit quick setup",
                            "1. Open Timetable to review the suggested routines.\n"
                            "2. Open Calendar to see the offline BS Patro.\n"
                            "3. Use Tasks and Habits only for goals you choose.\n"
                            "4. Settings lets you change reminders, themes, backups, and updates.\n\n"
                            "Your notes and activity records stay on this PC.", parent=self)
        DATA["setup_complete"] = True
        save_data()
        self.show_page("Dashboard")

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
            overrides = DATA.get("schedule_overrides", {}).get(day_key(), {})
            lines = overrides.get(key, DATA.get(key, []))
            skipped = set(DATA.get("skipped_schedule", {}).get(day_key(), {}).get(key, []))
            return [(clock, activity) for clock, activity in parse_schedule(lines) if clock not in skipped]
        except ValueError:
            return []

    def toggle_schedule_complete(self, key, clock):
        progress_key = f"{day_key()}|{key}|{clock}"
        completed = DATA.setdefault("completed_schedule", [])
        if progress_key in completed:
            completed.remove(progress_key)
        else:
            completed.append(progress_key)
        save_data()
        self.show_page("Dashboard")

    def skip_or_reschedule(self, key, clock, activity):
        choice = messagebox.askyesnocancel("Adjust today's plan", "Yes: skip this item. No: move it to another time. Cancel: keep it.", parent=self)
        if choice is None:
            return
        overrides = DATA.setdefault("schedule_overrides", {}).setdefault(day_key(), {})
        lines = overrides.get(key, DATA.get(key, []))
        if choice:
            skipped = DATA.setdefault("skipped_schedule", {}).setdefault(day_key(), {}).setdefault(key, [])
            if clock not in skipped:
                skipped.append(clock)
        else:
            new_clock = simpledialog.askstring("Move activity", "New start time (HH:MM):", initialvalue=clock, parent=self)
            if new_clock is None:
                return
            try:
                datetime.strptime(new_clock.strip(), "%H:%M")
            except ValueError:
                messagebox.showerror("Time format", "Use 24-hour time such as 17:30.", parent=self)
                return
            overrides[key] = [line for line in lines if not line.startswith(clock + " |")]
            overrides[key].append(f"{new_clock.strip()} | {activity}")
            try:
                parse_schedule(overrides[key])
            except ValueError as exc:
                messagebox.showerror("Cannot move activity", str(exc), parent=self)
                overrides[key] = lines
                return
            skipped = DATA.setdefault("skipped_schedule", {}).setdefault(day_key(), {}).setdefault(key, [])
            if clock not in skipped:
                skipped.append(clock)
        save_data()
        self.show_page("Dashboard")

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
        self.schedule_text.bind("<<Modified>>", self.mark_schedule_dirty)

        def load_choice(_event=None):
            next_key = choices[self.schedule_choice.get()]
            if self.schedule_dirty and next_key != self.current_schedule_type:
                choice = messagebox.askyesnocancel("Unsaved timetable", "Save this timetable before switching plans?", parent=self)
                if choice is None:
                    old_title = next(title for title, key in choices.items() if key == self.current_schedule_type)
                    self.schedule_choice.set(old_title)
                    return
                if choice:
                    self.save_schedule()
                    if self.schedule_dirty:
                        old_title = next(title for title, key in choices.items() if key == self.current_schedule_type)
                        self.schedule_choice.set(old_title)
                        return
                else:
                    self.schedule_dirty = False
            self.current_schedule_type = next_key
            self.schedule_text.delete("1.0", "end")
            self.schedule_text.insert("1.0", "\n".join(DATA.get(self.current_schedule_type, [])))
            self.schedule_text.edit_modified(False)
            self.schedule_dirty = False
        combo.bind("<<ComboboxSelected>>", load_choice)
        load_choice()
        help_text = "Format: 06:30 | Morning study | optional duration in minutes (24-hour time)"
        self.label(self.page_host, help_text, 9, self.theme["muted"]).pack(anchor="w")
        actions = tk.Frame(self.page_host, bg=self.theme["bg"])
        actions.pack(fill="x", pady=8)
        self.button(actions, "Restore suggested plan", self.restore_default_schedule).pack(side="left")
        self.button(actions, "Copy to another plan…", self.copy_schedule).pack(side="left", padx=6)
        self.button(actions, "Save this timetable", self.save_schedule,
                    primary=True).pack(side="right")

    def restore_default_schedule(self):
        if not messagebox.askyesno("Restore suggested timetable", "Replace this timetable with the DailyFit suggested plan?", parent=self):
            return
        DATA[self.current_schedule_type] = list(DEFAULTS[self.current_schedule_type])
        save_data()
        self.schedule_text.delete("1.0", "end")
        self.schedule_text.insert("1.0", "\n".join(DATA[self.current_schedule_type]))
        self.schedule_text.edit_modified(False)
        self.schedule_dirty = False

    def copy_schedule(self):
        choices = {
            "School day": "weekday_schedule", "Home day": "home_schedule",
            "Weekend": "weekend_schedule", "Holiday": "holiday_schedule",
        }
        destination = simpledialog.askstring("Copy timetable", "Copy the current plan to which one?\n" +
                                              " / ".join(choices), parent=self)
        if destination is None:
            return
        key = next((value for label, value in choices.items() if label.casefold() == destination.strip().casefold()), None)
        if not key:
            messagebox.showerror("Choose a plan", "Enter School day, Home day, Weekend, or Holiday.", parent=self)
            return
        if key == self.current_schedule_type:
            messagebox.showinfo("Same plan", "Choose a different timetable type.", parent=self)
            return
        if not messagebox.askyesno("Replace timetable", "Replace the selected plan with a copy of the current editor?", parent=self):
            return
        lines = [line.strip() for line in self.schedule_text.get("1.0", "end").splitlines() if line.strip()]
        try:
            parse_schedule(lines, include_duration=True)
        except ValueError as exc:
            messagebox.showerror("Check timetable format", str(exc), parent=self)
            return
        DATA[key] = lines
        save_data()
        messagebox.showinfo("Copied", "The timetable copy was saved.", parent=self)

    def save_schedule(self):
        lines = [x for x in self.schedule_text.get("1.0", "end").splitlines() if x.strip()]
        try:
            parsed = parse_schedule(lines, include_duration=True)
        except ValueError as exc:
            messagebox.showerror("Check timetable format", str(exc), parent=self)
            return
        DATA[self.current_schedule_type] = [
            f"{t} | {a}" + (f" | {duration}" if duration else "")
            for t, a, duration in parsed
        ]
        save_data()
        self.schedule_dirty = False
        self.schedule_text.edit_modified(False)
        messagebox.showinfo("Saved", "Your timetable has been saved.", parent=self)

    def mark_schedule_dirty(self, _event=None):
        if hasattr(self, "schedule_text") and self.schedule_text.edit_modified():
            self.schedule_dirty = True
            self.schedule_text.edit_modified(False)

    def display_clock(self, value):
        try:
            parsed = datetime.strptime(value, "%H:%M")
            return parsed.strftime("%I:%M %p").lstrip("0") if DATA.get("time_format") == "12h" else value
        except ValueError:
            return value

    def page_history(self):
        self.label(
            self.page_host,
            "Review saved counter totals by day, for the last 7 days, month-to-date, and all time.",
            10, self.theme["muted"], wraplength=760
        ).pack(anchor="w", pady=(0, 8))

        controls = tk.Frame(self.page_host, bg=self.theme["bg"])
        controls.pack(fill="x", pady=5)
        self.button(controls, "◀ Previous day", lambda: self.change_history_date(-1)).pack(side="left", padx=(0, 4))
        self.history_date_var = tk.StringVar(value=date.today().isoformat())
        self.history_date_entry = tk.Entry(
            controls, textvariable=self.history_date_var, width=12,
            bg=self.theme["panel"], fg=self.theme["fg"], insertbackground=self.theme["fg"], relief="flat"
        )
        self.history_date_entry.pack(side="left", padx=4, ipady=6)
        self.history_date_entry.bind("<Return>", lambda _event: self.refresh_history())
        self.button(controls, "Show date", self.refresh_history, primary=True).pack(side="left", padx=4)
        self.button(controls, "Today", self.history_today).pack(side="left", padx=4)
        self.button(controls, "Next day ▶", lambda: self.change_history_date(1)).pack(side="left", padx=4)

        self.history_status = self.label(self.page_host, "", 10, self.theme["muted"])
        self.history_status.pack(anchor="w", pady=(4, 2))
        self.history_tree = ttk.Treeview(
            self.page_host,
            columns=("selected_day", "last_7", "month_to_date", "all_time"),
            show="tree headings", height=14, selectmode="browse"
        )
        self.history_tree.heading("#0", text="Counter")
        self.history_tree.column("#0", width=210, anchor="w")
        for column, title, width in (
            ("selected_day", "Selected day", 120),
            ("last_7", "7 days through date", 150),
            ("month_to_date", "Month through date", 150),
            ("all_time", "All time", 120),
        ):
            self.history_tree.heading(column, text=title)
            self.history_tree.column(column, width=width, anchor="e")
        self.history_tree.pack(fill="both", expand=True, pady=6)
        self.label(
            self.page_host,
            "Totals are shown separately for each counter because they can use different units (for example, repetitions and mL).",
            9, self.theme["muted"], wraplength=760
        ).pack(anchor="w", pady=(2, 8))
        self.refresh_history()

    def history_today(self):
        self.history_date_var.set(date.today().isoformat())
        self.refresh_history()

    def change_history_date(self, offset):
        try:
            selected = date.fromisoformat(self.history_date_var.get().strip())
        except ValueError:
            messagebox.showerror("Date format", "Enter a date as YYYY-MM-DD first.", parent=self)
            return
        self.history_date_var.set((selected + timedelta(days=offset)).isoformat())
        self.refresh_history()

    @staticmethod
    def counter_value(value):
        try:
            return max(0, int(value))
        except (ValueError, TypeError, OverflowError):
            return 0

    def refresh_history(self):
        if not hasattr(self, "history_tree") or not self.history_tree.winfo_exists():
            return
        try:
            selected = date.fromisoformat(self.history_date_var.get().strip())
        except ValueError:
            messagebox.showerror("Date format", "Enter a date as YYYY-MM-DD.", parent=self)
            return

        self.history_date_var.set(selected.isoformat())
        for row in self.history_tree.get_children():
            self.history_tree.delete(row)

        raw_counts = DATA.get("counts", {})
        if not isinstance(raw_counts, dict):
            raw_counts = {}
        records = []
        for raw_day, values in raw_counts.items():
            if not isinstance(values, dict):
                continue
            try:
                record_day = date.fromisoformat(str(raw_day))
            except ValueError:
                continue
            records.append((record_day, values))

        activity_names = [
            str(name).strip() for name in DATA.get("activities", [])
            if str(name).strip()
        ]
        historical_names = {
            str(name).strip() for _record_day, values in records for name in values
            if str(name).strip()
        }
        names = activity_names + sorted(historical_names - set(activity_names), key=str.casefold)

        selected_values = next(
            (values for record_day, values in records if record_day == selected), {}
        )
        seven_day_start = selected - timedelta(days=6)
        month_start = selected.replace(day=1)
        for name in names:
            selected_total = self.counter_value(selected_values.get(name, 0))
            seven_day_total = sum(
                self.counter_value(values.get(name, 0))
                for record_day, values in records
                if seven_day_start <= record_day <= selected
            )
            month_total = sum(
                self.counter_value(values.get(name, 0))
                for record_day, values in records
                if month_start <= record_day <= selected
            )
            all_time_total = sum(
                self.counter_value(values.get(name, 0)) for _record_day, values in records
            )
            self.history_tree.insert(
                "", "end", text=name,
                values=(selected_total, seven_day_total, month_total, all_time_total)
            )

        if selected_values:
            self.history_status.config(text=f"Counter totals for {selected.isoformat()}")
        else:
            self.history_status.config(text=f"No counter entries saved for {selected.isoformat()}; showing 0 for that day.")

    def page_tasks(self):
        self.label(self.page_host, "Homework, study plans, exam dates, and small daily goals stay on this computer.",
                   10, self.theme["muted"]).pack(anchor="w", pady=(0, 8))
        tools = tk.Frame(self.page_host, bg=self.theme["bg"])
        tools.pack(fill="x", pady=5)
        self.button(tools, "+ Add task", self.add_task, primary=True).pack(side="left")
        self.button(tools, "Start", lambda: self.set_task_status("In progress")).pack(side="left", padx=4)
        self.button(tools, "Complete / reopen", self.toggle_task_done).pack(side="left", padx=4)
        self.task_filter_var = tk.StringVar(value="Open")
        ttk.Combobox(tools, textvariable=self.task_filter_var, values=["All", "Open", "Done", "Archived"],
                     state="readonly", width=9).pack(side="right", padx=4)
        self.task_filter_var.trace_add("write", lambda *_: self.refresh_tasks())
        self.task_search_var = tk.StringVar()
        tk.Entry(tools, textvariable=self.task_search_var, width=24, relief="flat",
                 bg=self.theme["panel"], fg=self.theme["fg"], insertbackground=self.theme["fg"]).pack(side="right", ipady=5)
        self.task_search_var.trace_add("write", lambda *_: self.refresh_tasks())
        task_actions = tk.Frame(self.page_host, bg=self.theme["bg"])
        task_actions.pack(fill="x", pady=2)
        self.button(task_actions, "Add subtask", self.add_subtask).pack(side="left", padx=4)
        self.button(task_actions, "Check subtask", self.toggle_subtask).pack(side="left", padx=4)
        self.button(task_actions, "Archive / restore", self.archive_task).pack(side="left", padx=4)
        self.button(task_actions, "Delete", self.delete_task).pack(side="left", padx=4)
        self.task_tree = ttk.Treeview(self.page_host, columns=("due", "subject", "priority", "status", "subtasks"),
                                      show="headings", height=12, selectmode="browse")
        for column, title, width in (("due", "Due date", 100), ("subject", "Subject", 130),
                                     ("priority", "Priority", 90), ("status", "Status", 110),
                                     ("subtasks", "Subtasks", 80)):
            self.task_tree.heading(column, text=title)
            self.task_tree.column(column, width=width, anchor="w")
        self.task_tree.pack(fill="both", expand=True, pady=6)
        self.task_summary = self.label(self.page_host, "", 9, self.theme["muted"])
        self.task_summary.pack(anchor="w", pady=3)
        frame, inner = self.card(self.page_host)
        self.label(inner, "TODAY'S GOALS", 9, self.theme["muted"], True).pack(anchor="w")
        self.goals_frame = tk.Frame(inner, bg=self.theme["panel"])
        self.goals_frame.pack(fill="x", pady=4)
        self.button(inner, "+ Add daily goal", self.add_daily_goal).pack(anchor="w")
        _, weekly = self.card(self.page_host)
        self.label(weekly, "WEEKLY GOALS", 9, self.theme["muted"], True).pack(anchor="w")
        self.weekly_goals_frame = tk.Frame(weekly, bg=self.theme["panel"])
        self.weekly_goals_frame.pack(fill="x", pady=4)
        self.button(weekly, "+ Add weekly goal", self.add_weekly_goal).pack(anchor="w")
        self.refresh_tasks()
        self.refresh_daily_goals()
        self.refresh_weekly_goals()

    def add_task(self):
        title = simpledialog.askstring("New task", "Task or assignment name:", parent=self)
        if not title or not title.strip():
            return
        due = simpledialog.askstring("Due date", "Due date (YYYY-MM-DD), or leave blank:",
                                     initialvalue="", parent=self)
        if due is None:
            return
        due = due.strip()
        if due:
            try:
                date.fromisoformat(due)
            except ValueError:
                messagebox.showerror("Date format", "Enter a due date as YYYY-MM-DD.", parent=self)
                return
        subject = simpledialog.askstring("Subject", "Subject or category:", initialvalue="General", parent=self)
        if subject is None:
            return
        priority = simpledialog.askstring("Priority", "Priority: High, Normal, or Low", initialvalue="Normal", parent=self)
        if priority is None:
            return
        priority = priority.strip().title()
        if priority not in {"High", "Normal", "Low"}:
            messagebox.showerror("Priority", "Choose High, Normal, or Low.", parent=self)
            return
        tags = simpledialog.askstring("Task tags", "Tags, separated by commas (optional):", initialvalue="", parent=self)
        if tags is None:
            return
        reminder_time = simpledialog.askstring("Task reminder", "Reminder time on the due date (HH:MM), or leave blank:", initialvalue="", parent=self)
        if reminder_time is None:
            return
        reminder_time = reminder_time.strip()
        if reminder_time:
            try:
                reminder_time = datetime.strptime(reminder_time, "%H:%M").strftime("%H:%M")
            except ValueError:
                messagebox.showerror("Time format", "Use HH:MM, such as 08:30.", parent=self)
                return
        DATA.setdefault("tasks", []).append({
            "id": str(int(time.time() * 1000)), "title": title.strip()[:140], "due": due,
            "subject": subject.strip()[:40] or "General", "priority": priority,
            "status": "Pending", "subtasks": [], "tags": tags.strip()[:200], "reminder_time": reminder_time,
        })
        save_data()
        self.refresh_tasks()

    def selected_task(self):
        if not hasattr(self, "task_tree"):
            return None
        selected = self.task_tree.selection()
        if not selected:
            return None
        task_id = selected[0]
        return next((task for task in DATA.get("tasks", []) if task.get("id") == task_id), None)

    def refresh_tasks(self):
        if not hasattr(self, "task_tree") or not self.task_tree.winfo_exists():
            return
        for row in self.task_tree.get_children():
            self.task_tree.delete(row)
        query = self.task_search_var.get().strip().casefold() if hasattr(self, "task_search_var") else ""
        tasks = sorted(DATA.get("tasks", []), key=lambda t: (t.get("status") == "Done", t.get("due") or "9999", t.get("priority") != "High", t.get("title", "").casefold()))
        for task in tasks:
            filter_value = self.task_filter_var.get() if hasattr(self, "task_filter_var") else "Open"
            if filter_value == "Archived" and not task.get("archived"):
                continue
            if filter_value != "Archived" and task.get("archived"):
                continue
            if filter_value == "Open" and task.get("status") == "Done":
                continue
            if filter_value == "Done" and task.get("status") != "Done":
                continue
            haystack = " ".join(str(task.get(k, "")) for k in ("title", "subject", "priority", "status", "tags")).casefold()
            if query and query not in haystack:
                continue
            due = task.get("due", "")
            try:
                days_left = (date.fromisoformat(due) - date.today()).days if due else None
                if days_left is not None and days_left < 0 and task.get("status") != "Done":
                    due = f"OVERDUE ({abs(days_left)}d)"
                elif days_left is not None and task.get("subject", "").casefold() == "exam":
                    due = "Today" if days_left == 0 else f"Exam in {days_left}d"
            except ValueError:
                pass
            self.task_tree.insert("", "end", iid=task.get("id", str(time.time())),
                                  values=(due, task.get("subject", "General"), task.get("priority", "Normal"),
                                          task.get("status", "Pending"), f"{sum(bool(s.get('done')) for s in task.get('subtasks', []))}/{len(task.get('subtasks', []))}"))
        pending = sum(task.get("status") != "Done" for task in tasks)
        self.task_summary.config(text=f"{pending} open • {len(tasks)-pending} complete • Exam subjects show a countdown in the due-date column.")

    def set_task_status(self, status):
        task = self.selected_task()
        if not task:
            return
        task["status"] = status
        save_data()
        self.refresh_tasks()

    def toggle_task_done(self):
        task = self.selected_task()
        if not task:
            return
        task["status"] = "Pending" if task.get("status") == "Done" else "Done"
        save_data()
        self.refresh_tasks()

    def add_subtask(self):
        task = self.selected_task()
        if not task:
            return
        text = simpledialog.askstring("Add subtask", "Subtask name:", parent=self)
        if not text or not text.strip():
            return
        task.setdefault("subtasks", []).append({"title": text.strip()[:100], "done": False})
        save_data()
        messagebox.showinfo("Subtask saved", f"Added under: {task['title']}", parent=self)

    def toggle_subtask(self):
        task = self.selected_task()
        if not task or not task.get("subtasks"):
            return
        subtask = next((item for item in task["subtasks"] if not item.get("done")), task["subtasks"][0])
        subtask["done"] = not subtask.get("done", False)
        save_data()
        self.refresh_tasks()

    def archive_task(self):
        task = self.selected_task()
        if task:
            task["archived"] = not task.get("archived", False)
            save_data()
            self.refresh_tasks()

    def delete_task(self):
        task = self.selected_task()
        if not task:
            return
        if messagebox.askyesno("Delete task", f"Delete '{task.get('title','this task')}'?", parent=self):
            DATA["tasks"] = [item for item in DATA.get("tasks", []) if item.get("id") != task.get("id")]
            save_data()
            self.refresh_tasks()

    def add_daily_goal(self):
        title = simpledialog.askstring("Daily goal", "What would you like to finish today?", parent=self)
        if not title or not title.strip():
            return
        DATA.setdefault("daily_goals", []).append({
            "id": str(int(time.time() * 1000)), "title": title.strip()[:120],
            "date": date.today().isoformat(), "done": False,
        })
        save_data()
        self.refresh_daily_goals()

    def refresh_daily_goals(self):
        if not hasattr(self, "goals_frame") or not self.goals_frame.winfo_exists():
            return
        for child in self.goals_frame.winfo_children():
            child.destroy()
        goals = [goal for goal in DATA.get("daily_goals", []) if goal.get("date") == date.today().isoformat()]
        for goal in goals:
            var = tk.BooleanVar(value=bool(goal.get("done")))
            cb = tk.Checkbutton(self.goals_frame, text=goal.get("title", "Goal"), variable=var,
                                command=lambda item=goal, value=var: self.toggle_goal(item, value),
                                bg=self.theme["panel"], fg=self.theme["fg"], selectcolor=self.theme["panel2"],
                                activebackground=self.theme["panel"], activeforeground=self.theme["fg"], anchor="w")
            cb.pack(fill="x", anchor="w")

    def toggle_goal(self, goal, value):
        goal["done"] = bool(value.get())
        save_data()

    @staticmethod
    def current_week_key():
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat()

    def add_weekly_goal(self):
        title = simpledialog.askstring("Weekly goal", "What would you like to complete this week?", parent=self)
        if not title or not title.strip():
            return
        DATA.setdefault("weekly_goals", []).append({"id": str(int(time.time()*1000)),
                                                       "title": title.strip()[:120],
                                                       "week": self.current_week_key(), "done": False})
        save_data()
        self.refresh_weekly_goals()

    def refresh_weekly_goals(self):
        if not hasattr(self, "weekly_goals_frame") or not self.weekly_goals_frame.winfo_exists():
            return
        for child in self.weekly_goals_frame.winfo_children():
            child.destroy()
        goals = [g for g in DATA.get("weekly_goals", []) if g.get("week") == self.current_week_key()]
        for goal in goals:
            var = tk.BooleanVar(value=bool(goal.get("done")))
            tk.Checkbutton(self.weekly_goals_frame, text=goal.get("title", "Goal"), variable=var,
                           command=lambda item=goal, value=var: self.toggle_goal(item, value),
                           bg=self.theme["panel"], fg=self.theme["fg"], selectcolor=self.theme["panel2"],
                           activebackground=self.theme["panel"], activeforeground=self.theme["fg"], anchor="w").pack(fill="x")
        complete = sum(bool(goal.get("done")) for goal in goals)
        self.label(self.weekly_goals_frame, f"{complete}/{len(goals)} weekly goals complete", 9, self.theme["muted"], bg=self.theme["panel"]).pack(anchor="w")

    def page_habits(self):
        self.label(self.page_host, "Choose your own habits and repeat days. DailyFit only tracks what you choose.",
                   10, self.theme["muted"]).pack(anchor="w", pady=(0, 8))
        bar = tk.Frame(self.page_host, bg=self.theme["bg"])
        bar.pack(fill="x", pady=5)
        self.button(bar, "+ Add habit", self.add_habit, primary=True).pack(side="left")
        self.button(bar, "Pause / resume", self.toggle_habit_pause).pack(side="left", padx=4)
        self.button(bar, "Delete", self.delete_habit).pack(side="left", padx=4)
        self.habit_tree = ttk.Treeview(self.page_host, columns=("days", "streak", "week", "state"),
                                       show="headings", height=16, selectmode="browse")
        for column, title, width in (("days", "Repeat days", 180), ("streak", "Current streak", 110),
                                     ("week", "Last 7 days", 110), ("state", "State", 100)):
            self.habit_tree.heading(column, text=title)
            self.habit_tree.column(column, width=width, anchor="w")
        self.habit_tree.pack(fill="both", expand=True, pady=6)
        self.button(self.page_host, "Mark selected habit done today", self.mark_habit_today).pack(anchor="w")
        self.habit_summary = self.label(self.page_host, "", 9, self.theme["muted"])
        self.habit_summary.pack(anchor="w", pady=6)
        self.refresh_habits()

    def add_habit(self):
        name = simpledialog.askstring("New habit", "Habit name:", parent=self)
        if not name or not name.strip():
            return
        days_text = simpledialog.askstring("Repeat days", "Days: Mon,Tue,Wed,Thu,Fri,Sat,Sun (or All)",
                                           initialvalue="All", parent=self)
        if days_text is None:
            return
        day_names = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        raw = days_text.strip().casefold()
        if raw in {"all", "every day", "daily"}:
            days = list(range(7))
        else:
            parts = [part.strip()[:3] for part in raw.split(",")]
            if not parts or any(part not in day_names for part in parts):
                messagebox.showerror("Repeat days", "Use weekday abbreviations separated by commas.", parent=self)
                return
            days = sorted(set(day_names[part] for part in parts))
        DATA.setdefault("habits", []).append({"id": str(int(time.time()*1000)), "name": name.strip()[:80], "days": days, "active": True})
        save_data()
        self.refresh_habits()

    def selected_habit(self):
        selected = self.habit_tree.selection() if hasattr(self, "habit_tree") else []
        return next((h for h in DATA.get("habits", []) if selected and h.get("id") == selected[0]), None)

    def habit_streak(self, habit_id):
        logs = DATA.get("habit_logs", {})
        cursor = date.today()
        total = 0
        if logs.get(cursor.isoformat(), {}).get(habit_id):
            pass
        else:
            cursor -= timedelta(days=1)
        while logs.get(cursor.isoformat(), {}).get(habit_id):
            total += 1
            cursor -= timedelta(days=1)
        return total

    def refresh_habits(self):
        if not hasattr(self, "habit_tree") or not self.habit_tree.winfo_exists():
            return
        for row in self.habit_tree.get_children():
            self.habit_tree.delete(row)
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        logs = DATA.setdefault("habit_logs", {})
        for habit in DATA.get("habits", []):
            days = ", ".join(names[d] for d in habit.get("days", range(7)) if isinstance(d, int) and 0 <= d < 7)
            week = sum(bool(logs.get((date.today()-timedelta(days=i)).isoformat(), {}).get(habit.get("id"))) for i in range(7))
            self.habit_tree.insert("", "end", iid=habit.get("id", str(time.time())),
                                   values=(days, self.habit_streak(habit.get("id")), f"{week}/7", "Active" if habit.get("active", True) else "Paused"))
        active = sum(bool(h.get("active", True)) for h in DATA.get("habits", []))
        self.habit_summary.config(text=f"{active} active habits • progress is a personal record, not a target.")

    def mark_habit_today(self):
        habit = self.selected_habit()
        if not habit:
            return
        today_logs = DATA.setdefault("habit_logs", {}).setdefault(date.today().isoformat(), {})
        today_logs[habit["id"]] = not today_logs.get(habit["id"], False)
        save_data()
        self.refresh_habits()

    def toggle_habit_pause(self):
        habit = self.selected_habit()
        if habit:
            habit["active"] = not habit.get("active", True)
            save_data()
            self.refresh_habits()

    def delete_habit(self):
        habit = self.selected_habit()
        if habit and messagebox.askyesno("Delete habit", f"Delete '{habit['name']}' and its tracking history?", parent=self):
            DATA["habits"] = [h for h in DATA.get("habits", []) if h.get("id") != habit.get("id")]
            for record in DATA.get("habit_logs", {}).values():
                record.pop(habit.get("id"), None)
            save_data()
            self.refresh_habits()

    def page_trainer(self):
        self.label(self.page_host, "Optional tools only. Set a comfortable pace and stop whenever you want.",
                   10, self.theme["muted"]).pack(anchor="w", pady=(0, 8))
        book = ttk.Notebook(self.page_host)
        book.pack(fill="both", expand=True)
        movement = tk.Frame(book, bg=self.theme["bg"])
        focus = tk.Frame(book, bg=self.theme["bg"])
        checkin = tk.Frame(book, bg=self.theme["bg"])
        sleep = tk.Frame(book, bg=self.theme["bg"])
        book.add(movement, text="Movement & breaks")
        book.add(focus, text="Study focus")
        book.add(checkin, text="Daily check-in")
        book.add(sleep, text="Sleep notes")

        _, inner = self.card(movement)
        self.label(inner, "GENTLE MOVEMENT", 10, self.theme["muted"], True).pack(anchor="w")
        self.label(inner, "This tracker does not set required exercise targets or give medical advice.",
                   10, self.theme["muted"]).pack(anchor="w", pady=5)
        self.exercise_goal_var = tk.StringVar(value=str(DATA.get("exercise_goal", 3)))
        goal_row = tk.Frame(inner, bg=self.theme["panel"])
        goal_row.pack(anchor="w", pady=5)
        self.label(goal_row, "My optional weekly goal:", 10, self.theme["fg"], bg=self.theme["panel"]).pack(side="left")
        tk.Entry(goal_row, textvariable=self.exercise_goal_var, width=5).pack(side="left", padx=6)
        self.button(goal_row, "Save goal", self.save_exercise_goal).pack(side="left")
        self.button(inner, "Record optional movement session", self.record_exercise, primary=True).pack(anchor="w", pady=5)
        self.exercise_summary = self.label(inner, "", 10, self.theme["muted"])
        self.exercise_summary.pack(anchor="w")
        reminder_row = tk.Frame(inner, bg=self.theme["panel"])
        reminder_row.pack(anchor="w", pady=(7, 0))
        self.exercise_reminder_var = tk.BooleanVar(value=bool(DATA.get("exercise_reminder_enabled", False)))
        self.exercise_reminder_time_var = tk.StringVar(value=DATA.get("exercise_reminder_time", "17:00"))
        tk.Checkbutton(reminder_row, text="Optional movement reminder at", variable=self.exercise_reminder_var,
                       bg=self.theme["panel"], fg=self.theme["fg"], selectcolor=self.theme["panel2"],
                       activebackground=self.theme["panel"], activeforeground=self.theme["fg"]).pack(side="left")
        tk.Entry(reminder_row, textvariable=self.exercise_reminder_time_var, width=7).pack(side="left", padx=4)
        self.button(reminder_row, "Save", self.save_exercise_reminder).pack(side="left")
        _, rest = self.card(movement)
        self.label(rest, "REST TIMER", 10, self.theme["muted"], True).pack(anchor="w")
        self.rest_seconds = 60
        self.timer_label = self.label(rest, "01:00", 28, self.theme["fg"], True)
        self.timer_label.pack(anchor="w", pady=6)
        self.button(rest, "Start / reset 60-second rest", self.start_rest, primary=True).pack(anchor="w")
        self.rest_running = False
        if DATA.get("wellness_enabled", True):
            self.label(movement, "Optional idea: take a short stretch or screen break when you feel like one.",
                       9, self.theme["muted"]).pack(anchor="w", pady=6)

        _, focus_inner = self.card(focus)
        self.label(focus_inner, "STUDY SESSION TIMER", 10, self.theme["muted"], True).pack(anchor="w")
        self.label(focus_inner, "Choose any length that works for you. Breaks are optional.", 9, self.theme["muted"]).pack(anchor="w", pady=4)
        self.focus_minutes_var = tk.StringVar(value="25")
        focus_row = tk.Frame(focus_inner, bg=self.theme["panel"])
        focus_row.pack(anchor="w", pady=5)
        self.label(focus_row, "Minutes", 10, self.theme["fg"], bg=self.theme["panel"]).pack(side="left")
        tk.Entry(focus_row, textvariable=self.focus_minutes_var, width=6).pack(side="left", padx=5)
        self.focus_label = self.label(focus_inner, "25:00", 30, self.theme["fg"], True)
        self.focus_label.pack(anchor="w", pady=6)
        focus_actions = tk.Frame(focus_inner, bg=self.theme["panel"])
        focus_actions.pack(anchor="w")
        self.button(focus_actions, "Start / resume", self.start_focus, primary=True).pack(side="left", padx=(0, 4))
        self.button(focus_actions, "Pause", self.pause_focus).pack(side="left", padx=4)
        self.button(focus_actions, "Reset", self.reset_focus).pack(side="left", padx=4)
        self.focus_summary = self.label(focus_inner, "", 9, self.theme["muted"])
        self.focus_summary.pack(anchor="w", pady=5)
        self.refresh_focus_summary()

        _, mood_inner = self.card(checkin)
        self.label(mood_inner, "MOOD CHECK-IN", 10, self.theme["muted"], True).pack(anchor="w")
        self.label(mood_inner, "A private personal note only; it does not diagnose or judge your mood.", 9, self.theme["muted"]).pack(anchor="w", pady=4)
        self.mood_var = tk.StringVar(value=DATA.get("mood_logs", {}).get(day_key(), "Okay"))
        ttk.Combobox(mood_inner, textvariable=self.mood_var, values=["Great", "Good", "Okay", "Low", "Prefer not to say"],
                     state="readonly", width=24).pack(anchor="w", pady=5)
        reflection = DATA.get("reflections", {}).get(day_key(), "")
        self.reflection_box = tk.Text(mood_inner, height=8, wrap="word", bg=self.theme["panel"], fg=self.theme["fg"],
                                      insertbackground=self.theme["fg"], relief="flat", padx=10, pady=8)
        self.reflection_box.pack(fill="both", expand=True, pady=5)
        self.reflection_box.insert("1.0", reflection)
        self.button(mood_inner, "Save private check-in", self.save_checkin, primary=True).pack(anchor="w")

        _, sleep_inner = self.card(sleep)
        self.label(sleep_inner, "SLEEP SCHEDULE NOTE", 10, self.theme["muted"], True).pack(anchor="w")
        self.label(sleep_inner, "Optional time log only; no sleep score or health advice.", 9, self.theme["muted"]).pack(anchor="w", pady=4)
        sleep_row = tk.Frame(sleep_inner, bg=self.theme["panel"])
        sleep_row.pack(anchor="w", pady=5)
        self.sleep_bed_var = tk.StringVar(value="21:30")
        self.sleep_wake_var = tk.StringVar(value="06:30")
        self.label(sleep_row, "Bedtime", 9, self.theme["fg"], bg=self.theme["panel"]).pack(side="left")
        tk.Entry(sleep_row, textvariable=self.sleep_bed_var, width=8).pack(side="left", padx=5)
        self.label(sleep_row, "Wake time", 9, self.theme["fg"], bg=self.theme["panel"]).pack(side="left", padx=(8, 0))
        tk.Entry(sleep_row, textvariable=self.sleep_wake_var, width=8).pack(side="left", padx=5)
        self.button(sleep_inner, "Save today's sleep plan", self.save_sleep_log).pack(anchor="w")
        self.sleep_summary = self.label(sleep_inner, "", 10, self.theme["muted"])
        self.sleep_summary.pack(anchor="w", pady=8)
        self.refresh_wellness_summaries()

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

    def start_focus(self):
        if not self.focus_running and self.focus_remaining <= 0:
            try:
                minutes = int(self.focus_minutes_var.get())
                if not 1 <= minutes <= 180:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Timer length", "Choose 1 to 180 minutes.", parent=self)
                return
            self.focus_remaining = minutes * 60
            self.focus_session_start = datetime.now()
        self.focus_running = True
        self.update_focus_timer()

    def pause_focus(self):
        self.focus_running = False

    def reset_focus(self):
        self.focus_running = False
        self.focus_remaining = 0
        if hasattr(self, "focus_label") and self.focus_label.winfo_exists():
            self.focus_label.config(text=f"{self.focus_minutes_var.get()}:00")

    def update_focus_timer(self):
        if not self.focus_running:
            return
        if self.focus_remaining <= 0:
            self.focus_running = False
            DATA.setdefault("focus_sessions", {}).setdefault(day_key(), []).append(
                {"minutes": max(1, int(self.focus_minutes_var.get())), "completed": True}
            )
            save_data()
            self.show_notification("Study timer", "Your study timer is finished. Take a break if you want.")
            self.refresh_focus_summary()
            return
        if hasattr(self, "focus_label") and self.focus_label.winfo_exists():
            self.focus_label.config(text=f"{self.focus_remaining//60:02}:{self.focus_remaining%60:02}")
        self.focus_remaining -= 1
        self.after(1000, self.update_focus_timer)

    def refresh_focus_summary(self):
        if not hasattr(self, "focus_summary") or not self.focus_summary.winfo_exists():
            return
        count = sum(item.get("minutes", 0) for item in DATA.get("focus_sessions", {}).get(day_key(), []))
        self.focus_summary.config(text=f"Study timer completed today: {count} minutes.")

    def save_checkin(self):
        DATA.setdefault("mood_logs", {})[day_key()] = self.mood_var.get()
        DATA.setdefault("reflections", {})[day_key()] = self.reflection_box.get("1.0", "end").rstrip()
        save_data()
        messagebox.showinfo("Saved", "Your check-in stays in your local app data.", parent=self)

    def save_sleep_log(self):
        try:
            bed = datetime.strptime(self.sleep_bed_var.get().strip(), "%H:%M").strftime("%H:%M")
            wake = datetime.strptime(self.sleep_wake_var.get().strip(), "%H:%M").strftime("%H:%M")
        except ValueError:
            messagebox.showerror("Time format", "Use HH:MM, such as 21:30.", parent=self)
            return
        DATA.setdefault("sleep_logs", {})[day_key()] = {"bed": bed, "wake": wake}
        save_data()
        self.refresh_wellness_summaries()

    def save_exercise_goal(self):
        try:
            goal = int(self.exercise_goal_var.get())
            if not 0 <= goal <= 21:
                raise ValueError
        except ValueError:
            messagebox.showerror("Weekly goal", "Choose a number from 0 to 21 sessions.", parent=self)
            return
        DATA["exercise_goal"] = goal
        save_data()
        self.refresh_wellness_summaries()

    def save_exercise_reminder(self):
        reminder_time = self.exercise_reminder_time_var.get().strip()
        try:
            reminder_time = datetime.strptime(reminder_time, "%H:%M").strftime("%H:%M")
        except ValueError:
            messagebox.showerror("Time format", "Use 24-hour time, such as 17:00.", parent=self)
            return
        DATA["exercise_reminder_enabled"] = bool(self.exercise_reminder_var.get())
        DATA["exercise_reminder_time"] = reminder_time
        save_data()
        messagebox.showinfo("Saved", "Your optional movement reminder was saved.", parent=self)

    def record_exercise(self):
        DATA.setdefault("exercise_sessions", []).append(date.today().isoformat())
        save_data()
        self.refresh_wellness_summaries()

    def refresh_wellness_summaries(self):
        if hasattr(self, "exercise_summary") and self.exercise_summary.winfo_exists():
            week_ago = date.today() - timedelta(days=6)
            count = sum(week_ago <= date.fromisoformat(item) <= date.today()
                        for item in DATA.get("exercise_sessions", []) if self.valid_iso_date(item))
            self.exercise_summary.config(text=f"{count} optional sessions in the last 7 days • personal goal {DATA.get('exercise_goal', 0)}.")
        if hasattr(self, "sleep_summary") and self.sleep_summary.winfo_exists():
            record = DATA.get("sleep_logs", {}).get(day_key())
            week_ago = date.today() - timedelta(days=6)
            logged_days = sum(week_ago <= date.fromisoformat(day) <= date.today()
                              for day in DATA.get("sleep_logs", {}) if self.valid_iso_date(day))
            today_text = f"Today: bed {record['bed']} • wake {record['wake']}" if record else "No sleep plan saved for today."
            self.sleep_summary.config(text=f"{today_text}  •  7-day schedule notes: {logged_days}/7 days")

    @staticmethod
    def valid_iso_date(value):
        try:
            date.fromisoformat(value)
            return True
        except (ValueError, TypeError):
            return False

    def page_notes(self):
        self.label(self.page_host, "Notes are stored locally. Search by title, text, category, or tags.",
                   10, self.theme["muted"]).pack(anchor="w", pady=(0, 8))
        bar = tk.Frame(self.page_host, bg=self.theme["bg"])
        bar.pack(fill="x", pady=4)
        self.notes_search_var = tk.StringVar()
        entry = tk.Entry(bar, textvariable=self.notes_search_var, width=38, relief="flat",
                         bg=self.theme["panel"], fg=self.theme["fg"], insertbackground=self.theme["fg"])
        entry.pack(side="left", ipady=6)
        self.notes_search_var.trace_add("write", lambda *_: self.refresh_notes_list())
        self.button(bar, "+ New note", self.new_note, primary=True).pack(side="left", padx=6)
        self.button(bar, "Save", self.save_notes).pack(side="left", padx=3)
        self.notes_archived_var = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="Show archived", variable=self.notes_archived_var,
                       command=self.refresh_notes_list, bg=self.theme["bg"], fg=self.theme["fg"],
                       selectcolor=self.theme["panel2"], activebackground=self.theme["bg"],
                       activeforeground=self.theme["fg"]).pack(side="right", padx=5)
        note_actions = tk.Frame(self.page_host, bg=self.theme["bg"])
        note_actions.pack(fill="x", pady=2)
        self.button(note_actions, "Pin / unpin", self.toggle_note_pin).pack(side="left", padx=3)
        self.button(note_actions, "Duplicate", self.duplicate_note).pack(side="left", padx=3)
        self.button(note_actions, "Archive / restore", self.archive_note).pack(side="left", padx=3)
        body = tk.PanedWindow(self.page_host, orient="horizontal", bg=self.theme["bg"],
                              sashwidth=6, relief="flat")
        body.pack(fill="both", expand=True, pady=5)
        left = tk.Frame(body, bg=self.theme["panel"])
        right = tk.Frame(body, bg=self.theme["bg"])
        body.add(left, minsize=175, width=230)
        body.add(right, minsize=380)
        self.notes_list = tk.Listbox(left, bg=self.theme["panel"], fg=self.theme["fg"],
                                     selectbackground=self.theme["accent"], relief="flat",
                                     activestyle="none", font=("Segoe UI", 10))
        self.notes_list.pack(fill="both", expand=True, padx=4, pady=4)
        self.notes_list.bind("<<ListboxSelect>>", self.select_note)
        self.note_ids = []
        self.note_title_var = tk.StringVar()
        self.note_category_var = tk.StringVar(value="General")
        self.note_tags_var = tk.StringVar()
        self.note_date_var = tk.StringVar(value=date.today().isoformat())
        self.note_due_var = tk.StringVar()
        for caption, variable in (("Title", self.note_title_var), ("Category", self.note_category_var),
                                  ("Tags (comma separated)", self.note_tags_var),
                                  ("Date (YYYY-MM-DD)", self.note_date_var),
                                  ("Due date (YYYY-MM-DD, optional)", self.note_due_var)):
            variable.trace_add("write", self.mark_note_metadata_dirty)
            self.label(right, caption, 9, self.theme["muted"], True, bg=self.theme["bg"]).pack(anchor="w", pady=(5, 1))
            tk.Entry(right, textvariable=variable, relief="flat", bg=self.theme["panel"],
                     fg=self.theme["fg"], insertbackground=self.theme["fg"]).pack(fill="x", ipady=5)
        self.notes_box = tk.Text(right, wrap="word", bg=self.theme["panel"], fg=self.theme["fg"],
                                 insertbackground=self.theme["fg"], relief="flat", padx=12, pady=10,
                                 font=("Segoe UI", 11))
        self.notes_box.pack(fill="both", expand=True, pady=(7, 0))
        self.notes_box.bind("<<Modified>>", self.mark_notes_dirty)
        self.notes_box.bind("<Control-b>", lambda _e: self.format_note("bold"))
        self.notes_box.bind("<Control-i>", lambda _e: self.format_note("italic"))
        self.current_note_id = None
        if not DATA.get("notes_entries"):
            self.new_note()
        self.refresh_notes_list()
        if self.note_ids:
            self.notes_list.selection_set(0)
            self.select_note()

    def refresh_notes_list(self):
        if not hasattr(self, "notes_list") or not self.notes_list.winfo_exists():
            return
        query = self.notes_search_var.get().strip().casefold()
        show_archived = bool(self.notes_archived_var.get()) if hasattr(self, "notes_archived_var") else False
        items = sorted((note for note in DATA.get("notes_entries", []) if bool(note.get("archived")) == show_archived),
                       key=lambda n: (not n.get("pinned", False), n.get("created", ""), n.get("title", "").casefold()))
        self.notes_list.delete(0, "end")
        self.note_ids = []
        for note in items:
            haystack = " ".join(str(note.get(key, "")) for key in ("title", "category", "tags", "body")).casefold()
            if query and query not in haystack:
                continue
            due = f" • due {note['due']}" if note.get("due") else ""
            pin = "★ " if note.get("pinned") else ""
            note_date = note.get("date", note.get("created", ""))
            self.notes_list.insert("end", f"{pin}{note.get('title','Untitled')} • {note_date}{due}")
            self.note_ids.append(note.get("id"))

    def current_note(self):
        return next((n for n in DATA.get("notes_entries", []) if n.get("id") == self.current_note_id), None)

    def select_note(self, _event=None):
        if not hasattr(self, "notes_list"):
            return
        selection = self.notes_list.curselection()
        if not selection or selection[0] >= len(self.note_ids):
            return
        selected_id = self.note_ids[selection[0]]
        if self.notes_dirty and selected_id != self.current_note_id:
            self.save_notes_silent()
        self.current_note_id = selected_id
        note = self.current_note()
        if not note:
            return
        self.note_title_var.set(note.get("title", ""))
        self.note_category_var.set(note.get("category", "General"))
        self.note_tags_var.set(note.get("tags", ""))
        self.note_date_var.set(note.get("date", note.get("created", date.today().isoformat())))
        self.note_due_var.set(note.get("due", ""))
        self.notes_box.delete("1.0", "end")
        self.notes_box.insert("1.0", note.get("body", ""))
        self.notes_box.edit_modified(False)
        self.notes_dirty = False
        if selected_id in self.note_ids:
            idx = self.note_ids.index(selected_id)
            if self.notes_list.curselection() != (idx,):
                self.notes_list.selection_clear(0, "end")
                self.notes_list.selection_set(idx)

    def new_note(self):
        if self.notes_dirty:
            self.save_notes_silent()
        note = {"id": str(int(time.time()*1000)), "title": "Untitled note", "category": "General",
                "tags": "", "due": "", "body": "", "pinned": False,
                "date": date.today().isoformat(), "created": date.today().isoformat(), "archived": False}
        DATA.setdefault("notes_entries", []).append(note)
        self.current_note_id = note["id"]
        save_data()
        if hasattr(self, "notes_list") and self.notes_list.winfo_exists():
            self.refresh_notes_list()
            if self.note_ids and note["id"] in self.note_ids:
                idx = self.note_ids.index(note["id"])
                self.notes_list.selection_clear(0, "end")
                self.notes_list.selection_set(idx)
                self.select_note()

    def save_notes(self):
        note = self.current_note()
        if note is None:
            return
        due = self.note_due_var.get().strip()
        note_date = self.note_date_var.get().strip()
        try:
            date.fromisoformat(note_date)
        except ValueError:
            messagebox.showerror("Date format", "Enter the note date as YYYY-MM-DD.", parent=self)
            return
        if due:
            try:
                date.fromisoformat(due)
            except ValueError:
                messagebox.showerror("Date format", "Enter a due date as YYYY-MM-DD.", parent=self)
                return
        note.update({"title": self.note_title_var.get().strip()[:120] or "Untitled note",
                     "category": self.note_category_var.get().strip()[:40] or "General",
                     "tags": self.note_tags_var.get().strip()[:200], "due": due,
                     "date": note_date, "body": self.notes_box.get("1.0", "end").rstrip()})
        DATA["notes"] = note["body"]
        save_data()
        self.notes_dirty = False
        self.notes_box.edit_modified(False)
        self.refresh_notes_list()
        messagebox.showinfo("Saved", "Your note has been saved on this computer.", parent=self)

    def toggle_note_pin(self):
        note = self.current_note()
        if note:
            note["pinned"] = not note.get("pinned", False)
            self.save_notes_silent()

    def save_notes_silent(self):
        note = self.current_note()
        if note:
            note.update({"title": self.note_title_var.get().strip() or note.get("title", "Untitled note"),
                         "category": self.note_category_var.get().strip() or "General",
                         "tags": self.note_tags_var.get().strip(),
                         "date": self.note_date_var.get().strip(),
                         "due": self.note_due_var.get().strip(),
                         "body": self.notes_box.get("1.0", "end").rstrip()})
            DATA["notes"] = note["body"]
        save_data()
        self.notes_dirty = False
        if hasattr(self, "notes_box") and self.notes_box.winfo_exists():
            self.notes_box.edit_modified(False)
        self.refresh_notes_list()

    def mark_notes_dirty(self, _event=None):
        if hasattr(self, "notes_box") and self.notes_box.edit_modified():
            self.notes_dirty = True
            self.notes_box.edit_modified(False)

    def duplicate_note(self):
        note = self.current_note()
        if not note:
            return
        if self.notes_dirty:
            self.save_notes_silent()
        clone = {**note, "id": str(int(time.time()*1000)), "title": note.get("title", "Note") + " (copy)",
                 "created": date.today().isoformat(), "pinned": False}
        DATA.setdefault("notes_entries", []).append(clone)
        save_data()
        self.refresh_notes_list()

    def archive_note(self):
        note = self.current_note()
        if not note:
            return
        if self.notes_dirty:
            self.save_notes_silent()
        note["archived"] = not note.get("archived", False)
        save_data()
        self.refresh_notes_list()
        if self.note_ids:
            self.notes_list.selection_set(0)
            self.select_note()
        elif not self.notes_archived_var.get():
            self.new_note()

    def format_note(self, kind):
        try:
            start = self.notes_box.index("sel.first")
            end = self.notes_box.index("sel.last")
            selected = self.notes_box.get(start, end)
        except tk.TclError:
            return "break"
        marker = "**" if kind == "bold" else "*"
        self.notes_box.delete(start, end)
        self.notes_box.insert(start, f"{marker}{selected}{marker}")
        return "break"

    def mark_note_metadata_dirty(self, *_args):
        self.notes_dirty = True

    def refresh_calendar_background(self):
        # Keep the dashboard's holiday decision in sync from bundled offline data.
        if NepaliDate is None or patro_info is None:
            return
        try:
            today_bs = NepaliDate.from_date(date.today())
            month = local_calendar_month(today_bs.year, today_bs.month)
            holidays = [item["ad"] for item in month["days"] if item["holiday"]]
            DATA["api_school_holidays"] = holidays
            save_data()
        except (ValueError, OSError, AttributeError):
            pass

    def page_calendar(self):
        self.label(
            self.page_host,
            "नेपाली पात्रो • Bikram Sambat dates, tithi, festivals and holidays",
            10, self.theme["muted"]
        ).pack(anchor="w", pady=(0, 8))
        self.calendar_status = self.label(
            self.page_host, "नेपाली पात्रो लोड हुँदैछ…", 11, self.theme["accent"], True
        )
        self.calendar_status.pack(anchor="w", pady=3)
        nav = tk.Frame(self.page_host, bg=self.theme["bg"])
        nav.pack(fill="x", pady=4)
        self.button(nav, "◀ अघिल्लो महिना", lambda: self.change_calendar_month(-1)).pack(side="left")
        self.month_title = self.label(nav, "लोड हुँदैछ…", 13, self.theme["fg"], True)
        self.month_title.pack(side="left", padx=14)
        self.button(nav, "अर्को महिना ▶", lambda: self.change_calendar_month(1)).pack(side="left")
        self.button(nav, "Today", self.calendar_today).pack(side="right", padx=4)
        self.calendar_mode_var = tk.StringVar(value=self.calendar_view_mode)
        mode_combo = ttk.Combobox(nav, textvariable=self.calendar_mode_var,
                                  values=["month", "week", "day"], state="readonly", width=8)
        mode_combo.pack(side="right", padx=4)
        mode_combo.bind("<<ComboboxSelected>>", self.change_calendar_view)
        self.button(nav, "Find event", self.search_calendar_events).pack(side="right", padx=4)
        self.button(nav, "Go to BS…", self.goto_bs_month).pack(side="right", padx=4)

        self.calendar_grid = tk.Frame(self.page_host, bg=self.theme["bg"])
        self.calendar_grid.pack(fill="both", expand=True, pady=6)
        self.calendar_cells = tk.Frame(self.calendar_grid, bg=self.theme["bg"])
        self.calendar_cells.pack(fill="both", expand=True)
        self.calendar_weekdays = WEEKDAYS_NE if DATA.get("calendar_language") == "ne" else WEEKDAYS_EN
        self.calendar_cell_frames = {}
        self.calendar_days_by_ad = {}
        self.selected_calendar_ad = None

        row = tk.Frame(self.page_host, bg=self.theme["bg"])
        row.pack(fill="x")
        self.button(
            row, "चयनित दिनलाई स्कूल बिदा बनाउनुहोस्",
            self.add_calendar_closure, primary=True
        ).pack(side="left")
        self.button(row, "आफैं राखेको बिदा हटाउनुहोस्",
                    self.remove_calendar_closure).pack(side="left", padx=8)
        self.button(row, "Set one-time plan", self.set_one_time_plan).pack(side="left", padx=4)
        self.button(row, "Add event", self.add_calendar_event).pack(side="left", padx=4)
        self.button(row, "Edit / delete event", self.manage_calendar_event).pack(side="left", padx=4)
        link = tk.Label(
            self.page_host,
            text="Calendar data: NepDate • MIT open source • informational, not official. Tithi and event details cover BS 2077-01-01 through 2084-08-20; BS/AD date conversion covers a wider range.",
            bg=self.theme["bg"], fg=self.theme["accent"], cursor="hand2",
            font=("Segoe UI", 9, "underline"), wraplength=700, justify="left"
        )
        link.pack(anchor="w", pady=(6, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open("https://github.com/sanamhub/nepdate"))
        self.calendar_upcoming_label = self.label(self.page_host, "", 9, self.theme["muted"], wraplength=700)
        self.calendar_upcoming_label.pack(anchor="w", pady=(3, 8))
        self.load_calendar()

    def change_calendar_month(self, offset):
        if self.calendar_bs_year is None or self.calendar_bs_month is None:
            return
        month_index = self.calendar_bs_month - 1 + offset
        self.calendar_bs_year += month_index // 12
        self.calendar_bs_month = month_index % 12 + 1
        DATA["calendar_view_bs"] = {
            "year": self.calendar_bs_year,
            "month": self.calendar_bs_month,
        }
        save_data()
        months = NEPALI_MONTHS_EN if DATA.get("calendar_language") == "en" else NEPALI_MONTHS_NE
        year_text = str(self.calendar_bs_year) if DATA.get("calendar_language") == "en" else self.nepali_digits(self.calendar_bs_year)
        self.month_title.config(text=f"{months[self.calendar_bs_month]} {year_text}")
        self.load_calendar()

    def calendar_today(self):
        if NepaliDate is None:
            return
        today_bs = NepaliDate.from_date(date.today())
        self.calendar_bs_year, self.calendar_bs_month = today_bs.year, today_bs.month
        self.selected_calendar_ad = date.today().isoformat()
        DATA["calendar_view_bs"] = {"year": today_bs.year, "month": today_bs.month}
        save_data()
        self.load_calendar()

    def change_calendar_view(self, _event=None):
        self.calendar_view_mode = self.calendar_mode_var.get()
        DATA["calendar_view_mode"] = self.calendar_view_mode
        save_data()
        self.load_calendar()

    def calendar_keyboard_move(self, direction):
        if self.current_page != "Calendar" or NepaliDate is None:
            return
        if self.calendar_view_mode == "month":
            self.change_calendar_month(direction)
            return
        anchor = self.selected_calendar_ad or date.today().isoformat()
        try:
            target = date.fromisoformat(anchor) + timedelta(days=direction * (7 if self.calendar_view_mode == "week" else 1))
            bs_day = NepaliDate.from_date(target)
        except (ValueError, OverflowError):
            return
        self.selected_calendar_ad = target.isoformat()
        self.calendar_bs_year, self.calendar_bs_month = bs_day.year, bs_day.month
        self.load_calendar()

    def goto_bs_month(self):
        if NepaliDate is None:
            return
        year = simpledialog.askinteger("Go to BS month", "Bikram Sambat year:", initialvalue=self.calendar_bs_year or 2083, parent=self)
        if year is None:
            return
        month = simpledialog.askinteger("Go to BS month", "Month number (1–12):", initialvalue=self.calendar_bs_month or 1, minvalue=1, maxvalue=12, parent=self)
        if month is None:
            return
        try:
            NepaliDate(year, month, 1)
        except Exception:
            messagebox.showerror("Unsupported date", "That BS month is outside the supported calendar range.", parent=self)
            return
        self.calendar_bs_year, self.calendar_bs_month = year, month
        self.selected_calendar_ad = None
        self.load_calendar()

    def search_calendar_events(self):
        query = simpledialog.askstring("Find calendar event", "Search event or festival name:", parent=self)
        if not query or not query.strip():
            return
        query = query.strip().casefold()
        results = []
        for event in DATA.get("calendar_events", []):
            if query in " ".join(str(event.get(k, "")) for k in ("title", "description", "date")).casefold():
                results.append(f"{event.get('date','')} — {event.get('title','Event')}")
        for item in self.calendar_days_by_ad.values():
            for event in item.get("events", []):
                name = self.event_name(event, DATA.get("calendar_language", "ne"))
                if query in name.casefold():
                    results.append(f"{item.get('ad','')} — {name}")
        summary = "\n".join(results[:20]) if results else "No matching events found in the loaded month or your saved events."
        messagebox.showinfo("Calendar search", summary, parent=self)

    def manage_calendar_event(self):
        selected = self.selected_calendar_ad
        events = [event for event in DATA.get("calendar_events", [])
                  if not selected or any(item.get("id") == event.get("id") for item in self.events_for_date(selected))]
        if not events:
            messagebox.showinfo("No saved event", "Select a date with one of your saved events first.", parent=self)
            return
        labels = [f"{event.get('date','')} — {event.get('title','Event')}" for event in events]
        choice = simpledialog.askstring("Choose event", "Enter the number to edit or delete:\n" +
                                        "\n".join(f"{i+1}. {label}" for i, label in enumerate(labels)), parent=self)
        if choice is None:
            return
        try:
            event = events[int(choice)-1]
        except (ValueError, IndexError):
            messagebox.showerror("Event", "Enter one of the listed numbers.", parent=self)
            return
        action = messagebox.askyesnocancel("Manage event", "Yes: delete this event. No: edit its title and date. Cancel: keep it.", parent=self)
        if action is None:
            return
        if action:
            if messagebox.askyesno("Delete event", f"Delete '{event.get('title','Event')}'?", parent=self):
                DATA["calendar_events"].remove(event)
        else:
            title = simpledialog.askstring("Edit event", "Event name:", initialvalue=event.get("title", ""), parent=self)
            if not title or not title.strip():
                return
            event_date = simpledialog.askstring("Edit event", "Date (YYYY-MM-DD):", initialvalue=event.get("date", ""), parent=self)
            if event_date is None:
                return
            try:
                date.fromisoformat(event_date.strip())
            except ValueError:
                messagebox.showerror("Date format", "Enter a date as YYYY-MM-DD.", parent=self)
                return
            event.update({"title": title.strip()[:100], "date": event_date.strip()})
        save_data()
        self.load_calendar()

    def events_for_date(self, date_text):
        try:
            target = date.fromisoformat(date_text)
        except ValueError:
            return []
        found = []
        for event in DATA.get("calendar_events", []):
            try:
                start = date.fromisoformat(event.get("date", ""))
            except ValueError:
                continue
            repeat = event.get("repeat", "Never")
            matches = target == start
            if repeat == "Daily":
                matches = target >= start
            elif repeat == "Weekly":
                matches = target >= start and target.weekday() == start.weekday()
            elif repeat == "Monthly":
                matches = target >= start and target.day == start.day
            elif repeat == "Yearly":
                matches = target >= start and (target.month, target.day) == (start.month, start.day)
            if matches:
                found.append({**event, "title": event.get("title", "Event")})
        return found

    def add_calendar_event(self):
        selected = self.selected_calendar_ad or date.today().isoformat()
        title = simpledialog.askstring("New event", "Event name:", parent=self)
        if not title or not title.strip():
            return
        date_text = simpledialog.askstring("Event date", "Date (YYYY-MM-DD):", initialvalue=selected, parent=self)
        if date_text is None:
            return
        try:
            date.fromisoformat(date_text.strip())
        except ValueError:
            messagebox.showerror("Date format", "Enter a date as YYYY-MM-DD.", parent=self)
            return
        description = simpledialog.askstring("Event details", "Short note (optional):", parent=self) or ""
        all_day = messagebox.askyesno("All-day event", "Is this an all-day event?", parent=self)
        event_time = ""
        if not all_day:
            event_time = simpledialog.askstring("Event time", "Start time (HH:MM):", initialvalue="09:00", parent=self)
            if event_time is None:
                return
            try:
                event_time = datetime.strptime(event_time.strip(), "%H:%M").strftime("%H:%M")
            except ValueError:
                messagebox.showerror("Time format", "Use HH:MM, such as 09:30.", parent=self)
                return
        repeat = simpledialog.askstring("Repeat event", "Repeat: Never, Daily, Weekly, Monthly, or Yearly", initialvalue="Never", parent=self)
        if repeat is None:
            return
        repeat = repeat.strip().title()
        if repeat not in {"Never", "Daily", "Weekly", "Monthly", "Yearly"}:
            messagebox.showerror("Repeat option", "Choose Never, Daily, Weekly, Monthly, or Yearly.", parent=self)
            return
        reminder = simpledialog.askstring("Event reminder", "Reminder minutes before (0 for none):", initialvalue="0", parent=self)
        if reminder is None:
            return
        try:
            reminder = max(0, min(10080, int(reminder)))
        except ValueError:
            messagebox.showerror("Reminder", "Enter a number of minutes from 0 to 10080.", parent=self)
            return
        DATA.setdefault("calendar_events", []).append({
            "id": str(int(time.time() * 1000)), "title": title.strip()[:100],
            "date": date_text.strip(), "description": description.strip()[:500],
            "all_day": all_day, "time": event_time, "repeat": repeat, "reminder_minutes": reminder,
        })
        save_data()
        self.load_calendar()

    def load_calendar(self, force=False):
        if self.calendar_loading:
            return
        if NepaliDate is None or patro_info is None:
            self.calendar_status.config(text="Nepali calendar package missing. Install the free requirements.txt packages.")
            return
        self.calendar_loading = True
        self.calendar_status.config(text="Loading offline calendar data…")
        try:
            if self.calendar_bs_year is None or self.calendar_bs_month is None:
                saved = DATA.get("calendar_view_bs", {})
                self.calendar_bs_year = saved.get("year")
                self.calendar_bs_month = saved.get("month")
            if self.calendar_bs_year is None or self.calendar_bs_month is None:
                today_bs = NepaliDate.from_date(date.today())
                self.calendar_bs_year, self.calendar_bs_month = today_bs.year, today_bs.month
            month_data = local_calendar_month(self.calendar_bs_year, self.calendar_bs_month)
            if month_data is None:
                raise RuntimeError("Calendar data is unavailable.")
            today_bs = NepaliDate.from_date(date.today())
            today_info = patro_info(today_bs)
            today_data = {
                "text": {"bs": {
                    "ne": f"{self.nepali_digits(today_bs.year)} {NEPALI_MONTHS_NE[today_bs.month]} {self.nepali_digits(today_bs.day)}",
                    "en": f"{today_bs.year} {NEPALI_MONTHS_EN[today_bs.month]} {today_bs.day}",
                }},
                "tithi": today_info.tithi.np if today_info.tithi else "",
            }
            DATA["calendar_view_bs"] = {"year": self.calendar_bs_year, "month": self.calendar_bs_month}
            save_data()
            self.calendar_loaded(month_data, today_data, self.calendar_bs_year, self.calendar_bs_month)
        except (ValueError, RuntimeError, OSError, AttributeError) as exc:
            self.calendar_loading = False
            self.calendar_status.config(text=f"Calendar data unavailable: {exc}")

    def calendar_set_initial_month(self, year, month, today_data, force=False):
        self.calendar_loading = False
        self.calendar_bs_year = year
        self.calendar_bs_month = month
        DATA["calendar_view_bs"] = {"year": year, "month": month}
        save_data()
        self.month_title.config(text=f"{NEPALI_MONTHS.get(month, 'BS')} {self.nepali_digits(year)}")
        self.load_calendar(force=force)

    def calendar_load_failed(self, today_data):
        self.calendar_loading = False
        self.calendar_status.config(text="Offline calendar data could not be loaded.")

    def calendar_loaded(self, month_data, today_data, year, month):
        self.calendar_loading = False
        for widget in self.calendar_cells.winfo_children():
            widget.destroy()
        self.calendar_cell_frames = {}
        self.calendar_days_by_ad = {}
        days = (month_data or {}).get("days", [])
        self.month_days = []
        if self.selected_calendar_ad not in {item.get("ad") for item in days}:
            self.selected_calendar_ad = None
        english = DATA.get("calendar_language") == "en"
        language = "en" if english else "ne"
        months = NEPALI_MONTHS_EN if english else NEPALI_MONTHS_NE
        self.calendar_weekdays = WEEKDAYS_EN if english else WEEKDAYS_NE
        month_name = months.get(month, f"BS {month}")
        year_text = str(year) if english else self.nepali_digits(year)
        self.month_title.config(text=f"{month_name} {year_text}")
        if today_data:
            today_text = today_data.get("text", {}).get("bs", {}).get(language, "")
            self.calendar_status.config(text=f"Today: {today_text}" if english else (f"आज: {today_text}" if today_text else "नेपाली पात्रो"))
        else:
            self.calendar_status.config(text="क्यास गरिएको पात्रो देखाइँदैछ।")

        monday_start = bool(DATA.get("week_starts_monday"))
        week_offset = 1 if monday_start else 0
        weekdays = self.calendar_weekdays[1:] + self.calendar_weekdays[:1] if monday_start else self.calendar_weekdays
        for column, weekday in enumerate(weekdays):
            label = tk.Label(
                self.calendar_cells, text=weekday, bg=self.theme["panel"],
                fg=self.theme["accent"], font=("Nirmala UI", 9, "bold"), pady=4
            )
            label.grid(row=0, column=column, sticky="nsew", padx=1, pady=1)
            self.calendar_cells.grid_columnconfigure(column, weight=1, uniform="calendar")

        if not days:
            tk.Label(
                self.calendar_cells, text="यो महिनाको डेटा भेटिएन। Refresh गर्नुहोस्।",
                bg=self.theme["bg"], fg=self.theme["muted"], font=("Nirmala UI", 10)
            ).grid(row=1, column=0, columnspan=7, sticky="w", padx=8, pady=12)
            return

        visible_days = list(days)
        if self.calendar_view_mode in {"week", "day"} and days:
            target_ad = self.selected_calendar_ad or date.today().isoformat()
            target_index = next((i for i, row_item in enumerate(days) if row_item.get("ad") == target_ad), 0)
            first_col = (days[0].get("weekday", 0) - week_offset) % 7
            target_week = (first_col + target_index) // 7
            if self.calendar_view_mode == "week":
                visible_days = [row_item for i, row_item in enumerate(days)
                                if (first_col + i) // 7 == target_week]
            else:
                visible_days = [days[target_index]]
        first_weekday = days[0].get("weekday", 0) if days else 0
        for index, item in enumerate(visible_days):
            bs = item.get("bs", {}) or {}
            bs_day = bs.get("day", index + 1)
            ad = item.get("ad", "")
            weekday_index = item.get("weekday", 0)
            col = (weekday_index - week_offset) % 7 if 0 <= weekday_index <= 6 else index % 7
            if self.calendar_view_mode == "day":
                row = 1
            elif self.calendar_view_mode == "week":
                visible_first = visible_days[0].get("weekday", 0)
                row = 1
            else:
                row = ((first_weekday - week_offset) % 7 + (bs_day - 1)) // 7 + 1
            events = list(item.get("events", []) or []) + self.events_for_date(ad)
            names = [self.event_name(event, language) for event in events]
            tithi = (item.get("text", {}).get("tithi", {}) or {}).get(language, "")
            is_holiday = bool(item.get("holiday")) or any(
                isinstance(event, dict)
                and event.get("holiday") == "national"
                and event.get("verified")
                for event in events
            )
            is_today = ad == date.today().isoformat()
            bg = self.theme["panel2"] if is_today else self.theme["panel"]
            fg = "#ff8d8d" if is_holiday or weekday_index == 6 else self.theme["fg"]
            frame = tk.Frame(
                self.calendar_cells, bg=bg, height=70,
                highlightbackground=self.theme["accent"] if is_today else self.theme["border"],
                highlightthickness=2 if is_today else 1
            )
            frame.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
            frame.grid_propagate(False)
            bs_label = str(bs_day) if english else self.nepali_digits(bs_day)
            ad_label = ""
            try:
                ad_label = date.fromisoformat(ad).strftime("%d %b")
            except ValueError:
                pass
            title = tk.Label(
                frame, text=f"{bs_label}   {ad_label}", bg=bg, fg=fg,
                font=("Segoe UI" if english else "Nirmala UI", 10, "bold"), anchor="w"
            )
            title.pack(fill="x", padx=4, pady=(2, 0))
            detail_parts = [part for part in [tithi, ", ".join(names[:2]) if names else ""] if part]
            if is_holiday and not names:
                detail_parts.append("बिदा")
            detail = "\n".join(detail_parts)
            sub = tk.Label(
                frame, text=detail, bg=bg, fg=self.theme["muted"],
                font=("Segoe UI" if english else "Nirmala UI", 8), anchor="w", justify="left", wraplength=92
            )
            sub.pack(fill="x", padx=4)
            self.month_days.append(ad)
            self.calendar_days_by_ad[ad] = item
            self.calendar_cell_frames[ad] = frame
            for widget in (frame, title, sub):
                widget.bind("<Button-1>", lambda _e, selected=ad: self.select_calendar_date(selected))
            self.calendar_cells.grid_rowconfigure(row, weight=1, minsize=72)
        upcoming = []
        for item in days:
            ad = item.get("ad", "")
            if ad < date.today().isoformat():
                continue
            names = [self.event_name(event, language) for event in (item.get("events", []) or []) + self.events_for_date(ad)]
            if names:
                upcoming.append(f"{ad}: {', '.join(names[:2])}")
        self.calendar_upcoming_label.config(text="Upcoming this month: " + ("  •  ".join(upcoming[:6]) if upcoming else "no saved events remaining this month"))

    @staticmethod
    def nepali_digits(value):
        table = str.maketrans("0123456789", "०१२३४५६७८९")
        return str(value).translate(table)

    def select_calendar_date(self, ad):
        self.selected_calendar_ad = ad
        item = self.calendar_days_by_ad.get(ad, {})
        language = DATA.get("calendar_language", "ne")
        bs_text = item.get("text", {}).get("bs", {}).get(language, "")
        tithi = (item.get("text", {}).get("tithi", {}) or {}).get(language, "")
        events = [self.event_name(event, language) for event in item.get("events", []) or []]
        details = " • ".join(part for part in [bs_text, tithi, ", ".join(events)] if part)
        if not details:
            details = ad
        self.calendar_status.config(text=f"चयनित: {details}")
        for saved_ad, frame in self.calendar_cell_frames.items():
            frame.configure(
                highlightbackground=self.theme["accent"] if saved_ad == ad else self.theme["border"],
                highlightthickness=2 if saved_ad == ad else 1
            )

    @staticmethod
    def event_name(event, language="ne"):
        if isinstance(event, str):
            return event
        if isinstance(event, dict):
            text = event.get("text", {})
            if isinstance(text, dict):
                localized = text.get(language) or text.get("en")
            else:
                localized = None
            return (localized or event.get("name_np") or event.get("name_ne")
                    or event.get("name") or event.get("title")
                    or event.get("name_en") or "पर्व/कार्यक्रम")
        return "पर्व/कार्यक्रम"

    def selected_calendar_date(self):
        return self.selected_calendar_ad

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

    def set_one_time_plan(self):
        selected = self.selected_calendar_date()
        if not selected:
            messagebox.showinfo("Select a date", "Select a calendar date first.", parent=self)
            return
        choice = simpledialog.askstring("One-time timetable", "Plan for this date: School, Home, Weekend, or Holiday", parent=self)
        if choice is None:
            return
        key = {"school": "school", "home": "home", "weekend": "weekend", "holiday": "holiday"}.get(choice.strip().casefold())
        if not key:
            messagebox.showerror("Plan", "Choose School, Home, Weekend, or Holiday.", parent=self)
            return
        DATA.setdefault("day_modes", {})[selected] = key
        save_data()
        messagebox.showinfo("Saved", f"A one-time {key} plan is set for {selected}.", parent=self)

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
        self.label(inner, "CALENDAR AND CLOCK", 9, self.theme["muted"], True).pack(anchor="w")
        pref = tk.Frame(inner, bg=self.theme["panel"])
        pref.pack(fill="x", pady=6)
        self.time_format_var = tk.StringVar(value=DATA.get("time_format", "24h"))
        self.language_var = tk.StringVar(value=DATA.get("calendar_language", "ne"))
        self.week_start_var = tk.BooleanVar(value=bool(DATA.get("week_starts_monday", False)))
        self.wellness_var = tk.BooleanVar(value=bool(DATA.get("wellness_enabled", True)))
        tk.Label(pref, text="Time", bg=self.theme["panel"], fg=self.theme["fg"]).pack(side="left")
        ttk.Combobox(pref, textvariable=self.time_format_var, values=["24h", "12h"], state="readonly", width=7).pack(side="left", padx=5)
        tk.Label(pref, text="Calendar language", bg=self.theme["panel"], fg=self.theme["fg"]).pack(side="left", padx=(10, 0))
        ttk.Combobox(pref, textvariable=self.language_var, values=["ne", "en"], state="readonly", width=7).pack(side="left", padx=5)
        tk.Checkbutton(inner, text="Start calendar weeks on Monday", variable=self.week_start_var,
                       bg=self.theme["panel"], fg=self.theme["fg"], selectcolor=self.theme["panel2"],
                       activebackground=self.theme["panel"], activeforeground=self.theme["fg"]).pack(anchor="w")
        tk.Checkbutton(inner, text="Show optional wellness prompts", variable=self.wellness_var,
                       bg=self.theme["panel"], fg=self.theme["fg"], selectcolor=self.theme["panel2"],
                       activebackground=self.theme["panel"], activeforeground=self.theme["fg"]).pack(anchor="w")
        self.button(inner, "Save preferences", self.save_preferences, primary=True).pack(anchor="w", pady=5)

        _, inner = self.card(self.page_host)
        self.label(inner, "QUIET HOURS", 9, self.theme["muted"], True).pack(anchor="w")
        quiet = DATA.get("quiet_hours", DEFAULTS["quiet_hours"])
        self.quiet_enabled_var = tk.BooleanVar(value=bool(quiet.get("enabled", False)))
        self.quiet_start_var = tk.StringVar(value=quiet.get("start", "21:00"))
        self.quiet_end_var = tk.StringVar(value=quiet.get("end", "07:00"))
        tk.Checkbutton(inner, text="Mute reminders during quiet hours", variable=self.quiet_enabled_var,
                       bg=self.theme["panel"], fg=self.theme["fg"], selectcolor=self.theme["panel2"],
                       activebackground=self.theme["panel"], activeforeground=self.theme["fg"]).pack(anchor="w")
        self.water_reminder_var = tk.BooleanVar(value=bool(DATA.get("water_reminders_enabled", False)))
        self.break_reminder_var = tk.BooleanVar(value=bool(DATA.get("break_reminders_enabled", False)))
        tk.Checkbutton(inner, text="Optional water reminder (at most every 90 minutes)", variable=self.water_reminder_var,
                       bg=self.theme["panel"], fg=self.theme["fg"], selectcolor=self.theme["panel2"],
                       activebackground=self.theme["panel"], activeforeground=self.theme["fg"]).pack(anchor="w")
        tk.Checkbutton(inner, text="Optional screen-break reminder (at most every 90 minutes)", variable=self.break_reminder_var,
                       bg=self.theme["panel"], fg=self.theme["fg"], selectcolor=self.theme["panel2"],
                       activebackground=self.theme["panel"], activeforeground=self.theme["fg"]).pack(anchor="w")
        quiet_row = tk.Frame(inner, bg=self.theme["panel"])
        quiet_row.pack(anchor="w", pady=5)
        self.label(quiet_row, "From", 9, self.theme["muted"], bg=self.theme["panel"]).pack(side="left")
        tk.Entry(quiet_row, textvariable=self.quiet_start_var, width=7).pack(side="left", padx=4)
        self.label(quiet_row, "until", 9, self.theme["muted"], bg=self.theme["panel"]).pack(side="left")
        tk.Entry(quiet_row, textvariable=self.quiet_end_var, width=7).pack(side="left", padx=4)
        self.button(inner, "Save quiet hours", self.save_quiet_hours).pack(anchor="w")

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

        _, inner = self.card(self.page_host)
        self.label(inner, "PRIVATE DATA BACKUP", 9, self.theme["muted"], True).pack(anchor="w")
        self.label(inner, "Backups stay on this PC unless you choose an export location. DailyFit never uploads your notes, tasks, or timetable.",
                   9, self.theme["muted"], wraplength=700).pack(anchor="w", pady=4)
        backup_row = tk.Frame(inner, bg=self.theme["panel"])
        backup_row.pack(anchor="w", pady=4)
        self.button(backup_row, "Export backup…", self.export_backup, primary=True).pack(side="left", padx=(0, 4))
        self.button(backup_row, "Restore backup…", self.import_backup).pack(side="left", padx=4)
        self.button(backup_row, "Choose auto-backup folder…", self.choose_backup_folder).pack(side="left", padx=4)
        self.button(inner, "Clear all saved app data…", self.clear_all_data).pack(anchor="w", pady=4)
        self.button(inner, "Clear automatic backups…", self.clear_backups).pack(anchor="w", pady=4)
        self.button(inner, "About and open-source notices", self.show_open_source_notices).pack(anchor="w", pady=4)
        self.button(self.page_host, "Exit DailyFit completely", self.exit_app).pack(anchor="e", pady=10)

    def set_theme(self, name):
        DATA["theme"] = name
        save_data()
        self.rebuild_theme()

    def save_reminder_setting(self):
        DATA["reminders_enabled"] = bool(self.reminder_var.get())
        save_data()

    def save_preferences(self):
        DATA["time_format"] = self.time_format_var.get() if self.time_format_var.get() in {"12h", "24h"} else "24h"
        DATA["calendar_language"] = self.language_var.get() if self.language_var.get() in {"en", "ne"} else "ne"
        DATA["week_starts_monday"] = bool(self.week_start_var.get())
        DATA["wellness_enabled"] = bool(self.wellness_var.get())
        save_data()
        self.show_page(self.current_page)

    def save_quiet_hours(self):
        start, end = self.quiet_start_var.get().strip(), self.quiet_end_var.get().strip()
        try:
            datetime.strptime(start, "%H:%M")
            datetime.strptime(end, "%H:%M")
        except ValueError:
            messagebox.showerror("Time format", "Enter quiet hours as HH:MM (24-hour time).", parent=self)
            return
        DATA["quiet_hours"] = {"enabled": bool(self.quiet_enabled_var.get()), "start": start, "end": end}
        DATA["water_reminders_enabled"] = bool(self.water_reminder_var.get())
        DATA["break_reminders_enabled"] = bool(self.break_reminder_var.get())
        save_data()
        messagebox.showinfo("Saved", "Quiet hours saved.", parent=self)

    def automatic_backup(self):
        today = date.today().isoformat()
        if self.last_backup_date != today:
            try:
                folder = Path(DATA.get("backup_dir") or BACKUP_DIR)
                folder.mkdir(parents=True, exist_ok=True)
                if DATA_FILE.exists():
                    target = folder / f"DailyFit-{today}.json"
                    if not target.exists():
                        shutil.copy2(DATA_FILE, target)
                self.last_backup_date = today
            except OSError:
                pass
        self.after(3600000, self.automatic_backup)

    def export_backup(self):
        path = filedialog.asksaveasfilename(parent=self, title="Export DailyFit backup",
                                            defaultextension=".json", filetypes=[("JSON backup", "*.json")],
                                            initialfile=f"DailyFit-{date.today().isoformat()}.json")
        if not path:
            return
        try:
            save_data()
            Path(path).write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("Backup exported", "Your backup was saved. Keep this file private.", parent=self)
        except OSError as exc:
            messagebox.showerror("Backup failed", str(exc), parent=self)

    def choose_backup_folder(self):
        folder = filedialog.askdirectory(parent=self, title="Choose a private auto-backup folder")
        if folder:
            DATA["backup_dir"] = folder
            save_data()
            messagebox.showinfo("Saved", "Automatic backups will use that folder.", parent=self)

    def import_backup(self):
        path = filedialog.askopenfilename(parent=self, title="Restore DailyFit backup",
                                          filetypes=[("JSON backup", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            incoming = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(incoming, dict) or not any(key in incoming for key in ("weekday_schedule", "tasks", "notes_entries")):
                raise ValueError("This file does not look like a DailyFit backup.")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Backup not restored", str(exc), parent=self)
            return
        if not messagebox.askyesno("Restore backup", "This replaces the current app data. A safety backup will be created first. Continue?", parent=self):
            return
        self.write_backup_copy()
        restored = DEFAULTS.copy()
        restored.update(incoming)
        DATA.clear()
        DATA.update(restored)
        save_data()
        messagebox.showinfo("Backup restored", "Saved app data was restored.", parent=self)
        self.show_page("Dashboard")

    def write_backup_copy(self):
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            if DATA_FILE.exists():
                target = BACKUP_DIR / f"DailyFit-before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
                shutil.copy2(DATA_FILE, target)
        except OSError:
            pass

    def clear_all_data(self):
        if not messagebox.askyesno("Clear saved data", "This permanently removes your timetable, notes, tasks, habits, calendar events and tracking logs from this app. Your export and automatic backups are kept. Continue?", parent=self):
            return
        DATA.clear()
        DATA.update(json.loads(json.dumps(DEFAULTS)))
        save_data()
        self.show_page("Dashboard")

    def clear_backups(self):
        folder = Path(DATA.get("backup_dir") or BACKUP_DIR)
        if not folder.exists():
            messagebox.showinfo("No backups", "There are no automatic backups in the selected folder.", parent=self)
            return
        if not messagebox.askyesno("Clear automatic backups", "Permanently delete DailyFit automatic backup files in the selected backup folder?", parent=self):
            return
        try:
            for path in folder.glob("DailyFit-*.json"):
                path.unlink()
            messagebox.showinfo("Backups cleared", "Automatic backup files were removed.", parent=self)
        except OSError as exc:
            messagebox.showerror("Could not clear backups", str(exc), parent=self)

    def show_open_source_notices(self):
        bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        notice_path = bundle_dir / "THIRD_PARTY_NOTICES.md"
        try:
            content = notice_path.read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Notices unavailable", str(exc), parent=self)
            return
        window = tk.Toplevel(self)
        window.title(f"DailyFit v{APP_VERSION} • Open-source notices")
        window.configure(bg=self.theme["bg"])
        window.geometry("720x540")
        frame = tk.Frame(window, bg=self.theme["bg"])
        frame.pack(fill="both", expand=True, padx=12, pady=12)
        text = tk.Text(frame, wrap="word", bg=self.theme["panel"], fg=self.theme["fg"],
                       relief="flat", padx=12, pady=10, font=("Segoe UI", 10))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.insert("1.0", content)
        text.configure(state="disabled")

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
        if self.notes_dirty or self.schedule_dirty:
            if not messagebox.askyesno("Unsaved changes", "Save your open note or timetable before hiding DailyFit?", parent=self):
                # Keep the editor open in memory while the app is minimized.
                self._save_window_geometry()
                self.iconify()
                return
            if self.current_page == "Notes" and self.notes_dirty:
                self.save_notes()
                if self.notes_dirty:
                    return
            if self.current_page == "Timetable" and self.schedule_dirty:
                self.save_schedule()
                if self.schedule_dirty:
                    return
        self._save_window_geometry()
        self.iconify()

    def _save_window_geometry(self):
        try:
            DATA["window_geometry"] = self.geometry()
            save_data()
        except tk.TclError:
            pass

    def exit_app(self):
        if not messagebox.askyesno("Exit DailyFit", "Exit completely? Timetable reminders will stop until reopened.", parent=self):
            return
        if self.notes_dirty or self.schedule_dirty:
            choice = messagebox.askyesnocancel("Unsaved changes", "Save your open note or timetable before exiting?", parent=self)
            if choice is None:
                return
            if choice:
                if self.current_page == "Notes" and self.notes_dirty:
                    self.save_notes()
                    if self.notes_dirty:
                        return
                if self.current_page == "Timetable" and self.schedule_dirty:
                    self.save_schedule()
                    if self.schedule_dirty:
                        return
        self._save_window_geometry()
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
            now = datetime.now()
            if DATA.get("reminders_enabled", True) and not self.is_quiet_now(now):
                current = now.strftime("%H:%M")
                key, _title = self.active_mode()
                schedule = self.get_schedule(key)
                for clock, activity in schedule:
                    event_id = f"{now.date().isoformat()}_{key}_{clock}"
                    if clock == current and event_id not in self.reminded:
                        self.reminded.add(event_id)
                        self.show_notification("DailyFit • Next session", f"Your next session: {activity}")
                for task in DATA.get("tasks", []):
                    reminder_id = f"task_{task.get('id')}_{day_key()}"
                    if (task.get("status") != "Done" and task.get("due") == day_key()
                            and task.get("reminder_time") == current and reminder_id not in self.reminded):
                        self.reminded.add(reminder_id)
                        self.show_notification("DailyFit • Task due", task.get("title", "A task is due today."))
                for note in DATA.get("notes_entries", []):
                    reminder_id = f"note_{note.get('id')}_{day_key()}"
                    if note.get("due") == day_key() and current == "09:00" and reminder_id not in self.reminded:
                        self.reminded.add(reminder_id)
                        self.show_notification("DailyFit • Note due", note.get("title", "A note is due today."))
                self.remind_calendar_events(now, current)
                if (DATA.get("wellness_enabled", True)
                        and DATA.get("exercise_reminder_enabled")
                        and DATA.get("exercise_reminder_time") == current):
                    movement_id = f"movement_{day_key()}"
                    if movement_id not in self.reminded:
                        self.reminded.add(movement_id)
                        self.show_notification("DailyFit • Optional", "If it feels right, take a gentle movement break.")
                self.remind_wellness(now)
            # Keep memory bounded.
            if len(self.reminded) > 100:
                self.reminded.clear()
        except Exception:
            pass
        self.after(15000, self.reminder_tick)

    def is_quiet_now(self, now):
        quiet = DATA.get("quiet_hours", {})
        if not quiet.get("enabled"):
            return False
        try:
            current = now.strftime("%H:%M")
            start, end = quiet.get("start", "21:00"), quiet.get("end", "07:00")
            return start <= current < end if start < end else (current >= start or current < end)
        except (TypeError, ValueError):
            return False

    def remind_calendar_events(self, now, current):
        for event in DATA.get("calendar_events", []):
            try:
                start = date.fromisoformat(event.get("date", ""))
                repeat = event.get("repeat", "Never")
                today = now.date()
                matches = today == start
                if repeat == "Daily":
                    matches = today >= start
                elif repeat == "Weekly":
                    matches = today >= start and today.weekday() == start.weekday()
                elif repeat == "Monthly":
                    matches = today >= start and today.day == start.day
                elif repeat == "Yearly":
                    matches = today >= start and (today.month, today.day) == (start.month, start.day)
                if not matches or not event.get("reminder_minutes"):
                    continue
                event_time = event.get("time") or "09:00"
                target = datetime.combine(today, datetime.strptime(event_time, "%H:%M").time())
                trigger = target - timedelta(minutes=int(event.get("reminder_minutes", 0)))
                reminder_id = f"event_{event.get('id')}_{today.isoformat()}"
                if current == trigger.strftime("%H:%M") and reminder_id not in self.reminded:
                    self.reminded.add(reminder_id)
                    self.show_notification("DailyFit • Event", event.get("title", "Upcoming event"))
            except (ValueError, TypeError):
                continue

    def remind_wellness(self, now):
        if not DATA.get("wellness_enabled", True) or not (8 <= now.hour < 20):
            return
        reminders = []
        if DATA.get("water_reminders_enabled"):
            reminders.append("Water reminder")
        if DATA.get("break_reminders_enabled"):
            reminders.append("Break reminder")
        if not reminders:
            return
        last_text = DATA.get("last_wellness_reminder", "")
        try:
            last = datetime.fromisoformat(last_text) if last_text else None
        except ValueError:
            last = None
        if last and (now - last).total_seconds() < 90 * 60:
            return
        # Keep reminders user-controlled and gentle: at most one combined prompt every 90 minutes.
        if now.minute == 0:
            DATA["last_wellness_reminder"] = now.isoformat(timespec="minutes")
            save_data()
            self.show_notification("DailyFit • Optional", "Take a screen break or drink water if you want.")

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
                    release_notes = str(release.get("body", "")).strip()[:4000]
                    if not exe_url or not hash_url:
                        result = ("missing_assets", tag)
                    else:
                        result = ("available", tag, exe_url, hash_url, release_notes)
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
                        f"Version {result[1]} is available. Install the Windows EXE build to enable one-click self-updating.\n\n{result[4]}",
                        parent=self)
                return
            if not silent and not messagebox.askyesno("Update available",
                    f"DailyFit v{result[1]} is available. Download and install it now?\n\n{result[4]}", parent=self):
                return
            self.download_and_apply_update(result[1], result[2], result[3], result[4])
        elif status == "error":
            if not silent:
                messagebox.showerror("Update check failed", result[1], parent=self)

    def show_pending_release_notes(self):
        notes = str(DATA.get("pending_release_notes", "")).strip()
        version = str(DATA.get("pending_release_version", ""))
        DATA["pending_release_notes"] = ""
        DATA["pending_release_version"] = ""
        save_data()
        if notes:
            messagebox.showinfo(f"DailyFit v{version} update notes", notes, parent=self)

    def download_and_apply_update(self, tag, exe_url, hash_url, release_notes=""):
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
            DATA["pending_release_version"] = tag
            DATA["pending_release_notes"] = str(release_notes).strip()[:4000]
            save_data()
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

