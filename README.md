# DailyFit

DailyFit is a free Windows routine, study, calendar, and personal-tracking app. It uses local files for personal data and free, open-source packages. It has no ads, paid features, paid APIs, subscriptions, or trial services.

## Features

- Offline Bikram Sambat month, week, and day calendar views with matching Gregorian dates, Nepali or English labels, tithi, festivals, and holiday markers.
- Personal calendar events with descriptions, all-day or timed entries, recurrence, reminders, and school-closure or one-day timetable overrides.
- Separate suggested routines for school, home, weekends, and holidays. Edit, copy, restore, add durations, mark sessions complete, or skip and move an activity for today.
- Task lists with subjects, priorities, due dates, exam countdowns, subtasks, status, search, filters, and local reminders.
- Daily and weekly goals, habit tracking, repeat days, completion history, streaks, and weekly summaries.
- Daily counter history with date navigation and per-counter totals for the selected day, previous 7 days, month-to-date, and all saved time.
- Optional study timer, rest timer, movement log and reminder, mood check-in, reflection, sleep-time notes, and user-controlled water or screen-break reminders.
- Searchable notes with dates, categories, tags, due dates, pinning, bold/italic Markdown shortcuts, duplicates, and archive/restore.
- Dark, light, and ocean themes; 12/24-hour display; configurable week start; quiet hours; and Windows startup option.
- Automatic daily backups, manual export/restore, data clearing controls, update notes, and release update checks.

## Free Nepali calendar data

The calendar uses `nepdate-core` and `nepdate-patro`, distributed under the MIT License. The data is bundled with the app, so viewing the calendar does not require internet, an account, or an external calendar API. Date conversion covers BS 1901–2199. The current tithi, event, and public-holiday dataset covers BS 2077-01-01 through 2084-08-20. Data outside that Patro range can show the BS/AD date without tithi or event details. The project describes its holiday and tithi information as informational, not an official Government of Nepal calendar. Confirm important school closures with your school or official notices. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Privacy

Notes, tasks, timetable, habits, calendar events, and personal logs are stored in `%LOCALAPPDATA%\DailyFit\data.json`. The app does not upload them. The updater checks the public GitHub Releases page for DailyFit and downloads a Windows EXE and its SHA-256 checksum when a new version is available. That update check needs an internet connection; everyday planning and the bundled calendar work offline.

## Run from source

Install Python 3.12 or newer on Windows, then run:

```powershell
py -m pip install -r requirements.txt
py dailyfit.py
```

To build a local Windows EXE:

```powershell
py -m PyInstaller --noconfirm --clean --onefile --windowed --name DailyFit --collect-all winotify --collect-all nepdate --collect-all nepdate_patro --add-data "THIRD_PARTY_NOTICES.md;." dailyfit.py
```

## GitHub release builds and app updates

The public repository's GitHub Actions workflow builds the Windows EXE when a release is published, then attaches `DailyFit.exe` and `DailyFit.exe.sha256`. The workflow uses a standard Windows runner; GitHub says standard hosted runners are free for public repositories. This uses only free/open-source project dependencies; there is no paid calendar service.

The installed app defaults its update source to `ayubalemagar90-a11y/Track-App-`. It checks at startup and periodically, verifies the downloaded EXE with SHA-256, applies the update, and shows the release notes on restart. Settings lets you check manually or edit the public repository name. Automatic updating requires internet and a public GitHub release.

