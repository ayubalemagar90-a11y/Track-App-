# DailyFit — personal Windows tracker

DailyFit is a lightweight Tkinter desktop app for personal routines. Notes, timetable, counters and school-closure dates are stored locally in `%LOCALAPPDATA%\DailyFit\data.json`.

## Included

- School-day, home-day (missed school), weekend, and holiday timetables.
- "I missed school today" asks for Yes/No confirmation. Yes switches only today's plan to the home-day schedule. It does not change the regular school timetable. Undo is available.
- Push-up, sit-up, squat, water and custom activity counters.
- Notes, optional rest timer, schedule-start notifications, Windows startup option.
- Nepali Patro date/events/holiday reference via Trisambat API, with local cache and visible attribution.
- GitHub Releases updater that verifies the downloaded EXE with SHA-256 before replacing it.
- Purple, Ocean and Light themes.

## Nepali calendar data

The app calls `https://trisambat.com/api/v1/today.json` and the Gregorian month endpoint `/api/v1/ad/YYYY/MM.json`. It caches data locally to avoid unnecessary requests. Trisambat says the API is free during beta, requires a visible link back, and is informational rather than an official government calendar. Confirm school closure notices with your school. Saturday/Sunday and manual school closure dates are handled separately.

## First run from source

Install Python 3.12+ on Windows, then run:

```powershell
py -m pip install pyinstaller winotify
py dailyfit.py
```

To make a local EXE:

```powershell
py -m PyInstaller --noconfirm --clean --onefile --windowed --name DailyFit --collect-all winotify dailyfit.py
```

The EXE will be in `dist\DailyFit.exe`. A Windows EXE must be built on Windows.

## Set up automatic EXE builds and in-app updates (one time)

1. Create a **public** GitHub repository, for example `your-username/dailyfit`.
2. Upload `dailyfit.py` and the `.github/workflows/release.yml` file while preserving the `.github/workflows` folder.
3. In the repository, create a new GitHub Release with a tag such as `v0.1.0` and publish it.
4. GitHub Actions will build `DailyFit.exe`, calculate its SHA-256 digest, and attach both `DailyFit.exe` and `DailyFit.exe.sha256` to that release. The repository's Actions tab shows the build result.
5. Download `DailyFit.exe` from the release assets and run it.
6. Open DailyFit → Settings → Automatic updates. Enter the repo as `your-username/dailyfit` and save it.

After this setup, publish a new GitHub Release whenever a new app version is ready. The workflow builds and attaches the new EXE automatically. Installed DailyFit checks at launch and periodically; it downloads the release EXE, checks the SHA-256 digest, and applies the update. You do not need to run PyInstaller again on your PC.

## Important update notes

- The repository must be public for the no-login updater to read its releases.
- Do not upload personal notes, your timetable, or `data.json` to GitHub. Only upload the app source and workflow.
- The EXE is replaced in its current folder. Keep it in a permanent folder, not a temporary Downloads cleanup folder.
- The updater expects release assets named exactly `DailyFit.exe` and `DailyFit.exe.sha256`.
- Automatic updates begin only after the GitHub repository and first release are configured.
- The in-app update process is for Windows EXE builds, not when running `dailyfit.py` directly.

## Release routine for future changes

When DailyFit source is changed, upload/commit the updated `dailyfit.py` (and any changed project files) to GitHub, then create a new release with a new tag, e.g. `v0.2.0`. GitHub Actions builds the Windows EXE. Installed copies detect the newer release and update themselves.

## Privacy

Personal data stays on the user's PC. Calendar/API and GitHub requests only retrieve calendar data and public release information; the app does not upload your activity logs, notes, or timetable.
