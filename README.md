# Habit Tracker

A habit tracker for coding sessions. One pure, dependency-free core with three
front-ends on top: a scriptable **CLI**, an interactive **terminal menu**, and a
**Tkinter desktop window**.

Mark the days you coded, set a weekly goal, track streaks, and file your sessions
under `#hashtags`. Everything is stored locally in a single file you can read,
back up, and move between machines.

## Features

- Track several habits in one file, each with its own sessions and weekly goal
- Mark or clear a session for any day, with an optional note
- Weekly goal with a progress bar
- Current and longest streaks, totals, busiest weekday
- Month grid view, sharing one model between the CLI and the desktop window
- GitHub-style heatmap of the last 12 weeks, one column per calendar week
- `#hashtag` tags, ranked by how often you used them
- Undo for any change, with `ht history` showing what is still reversible
- Webhook notifications with no new dependency
- JSON export and import for backups and moving between machines
- Optional SQLite backend for a schema that can grow
- JSON output on every command, for scripting
- IANA timezone support, so "today" is right when you travel

## Install

```bash
pipx install habit-tracker          # recommended: isolated CLI install
```

or, for a development checkout:

```bash
python -m pip install -e ".[dev]"
```

Requires Python 3.11 or newer. The core has no third-party runtime
dependencies; everything else is an opt-in extra.

## Usage

### Terminal

```bash
ht mark                                  # mark today
ht mark yesterday -n "shipped #python"   # mark with a note
ht unmark 2026-10-01 -y                 # clear a day, no prompt
ht week                                  # this week, with a progress bar
ht week --week-of 2026-10-01             # any other week
ht month                                 # this month as a grid
ht month --month 2026-09                 # any other month
ht stats                                 # streaks and totals
ht tags                                  # ranked note tags
ht goal 4                                # sessions per week
ht goal 0                                # turn the goal off
ht undo                                  # roll back the last change
ht history                               # what is still reversible
ht export ~/backup.json                  # write a JSON backup
ht import ~/backup.json --force          # restore it
ht env                                   # resolved settings and optional packages
```

Running `ht` with no subcommand opens the interactive menu.

Day arguments accept `today`, `t`, `yesterday`, `y`, or an ISO `YYYY-MM-DD`.
Future dates are rejected unless you pass `--allow-future`.

### Several habits

Every habit has its own sessions, goal and streaks. The stored default decides
which one a command touches; `--habit` overrides it for a single command.

```bash
ht habit list                            # mark the active one with *
ht habit add "Reading" --goal 7
ht habit use reading                      # switch the default
ht habit rename "Daily reading" --habit reading
ht habit rm reading                       # remove it and its sessions

ht mark -n "chapter four #books" --habit reading
ht stats --habit reading
ht month --habit reading
ht tags --all                             # tags across every habit
```

`--habit` accepts a habit's id or its exact name. An unknown name is an error
rather than a silent write to the active habit. Removing a habit deletes its
sessions, so it asks for confirmation; pass `--force` to skip that, and `ht undo`
brings it back. The last habit cannot be removed.

### Undo

Every change records an undo step, so `ht undo` reverses the last thing you did
whether that was a mark, a clear, a goal change or a habit change.

```bash
ht history                                # newest first, with labels
ht undo                                   # roll back the newest step
```

Up to 50 steps are kept. Steps are snapshots rather than an event log, so undo
restores a whole previous state instead of replaying an inverse operation.

### Notifications

`ht notify` posts a summary to a webhook using only the standard library.

```bash
ht notify --url https://hooks.slack.com/services/...
ht notify --dry-run                       # print the payload, send nothing
ht notify --include-note --habit reading
```

Set `HABIT_TRACKER_WEBHOOK_URL` or `"webhook_url"` in `config.json` to skip the
flag. Slack-style (`text`) and Discord-style (`content`) bodies are both sent.

Session notes are **excluded by default**: a webhook endpoint is usually a shared
third-party URL, and habit notes tend to be personal. Pass `--include-note` only
when you want the prose included.

### Scripting

Every command emits JSON with `--json`, and prompts are skipped when stdin is
not a terminal:

```bash
ht mark yesterday -n "refactor #python"     # non-interactive
ht week --json | jq '.done'
if [ "$(ht --json stats | jq '.current_streak')" -eq 0 ]; then ht mark; fi
```

### Desktop window

```bash
ht gui
```

The window shows your stats, the week, the heatmap, a clickable month calendar and
your tags. **Any square in the heatmap and any day in the month grid is
clickable**, so you can mark or edit any recent date without typing. Use "Pick
date" for anything older. A habit selector switches every tab at once.

It ships with a light and a dark theme. "Theme" in the toolbar cycles
system → light → dark, and the default follows your desktop setting, so the
window already looks right on a machine set to dark mode. To pin it:

```bash
ht gui --theme dark
```

See [Configuration](#configuration) for the setting and environment variable.

## Optional extras

Everything is optional. `ht env` reports what is installed and how to add it.

| Extra | Installs | Gives you | Status |
| --- | --- | --- | --- |
| `rich` | `rich` | Tables, panels and coloured output | **wired up** |
| `dirs` | `platformdirs` | Correct per-user data directory | **wired up** |
| `dates` | `dateparser` | Phrases like `last friday`, `2 days ago` | **wired up** |
| `tui` | `textual` | Full-screen terminal interface | **wired up** |
| `gui` | `tkcalendar` | Month calendar picker | **wired up** |
| `build` | `pyinstaller` | Standalone `.exe` | spec included |
| `dev` | `pytest`, `ruff` | Tests and linting | **wired up** |

The window's colours are built in, so light and dark mode need no extra
package.

```bash
pipx install "habit-tracker[all]"     # everything except the build tools
```

With none of them installed, every feature still works: the core is standard
library only.

## Data

Your data lives in one file:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\habit-tracker\data.json` |
| macOS | `~/Library/Application Support/habit-tracker/data.json` |
| Linux | `~/.local/share/habit-tracker/data.json` |

```bash
ht env        # prints the exact path in use
```

Older versions kept `data.json` next to the source code. To bring that file
across from a checkout:

```bash
ht migrate-legacy
```

Writes are atomic: the new content is staged alongside the old file and moved
into place, so an interrupted save cannot truncate your history. Every save also
keeps the previous version as `data.json.bak`, and an unreadable file is moved
aside as `data.json.corrupt` rather than silently discarded.

### File format

Schema version 2 stores habits and their sessions separately:

```json
{
  "schema_version": 2,
  "active_habit": "coding",
  "habits": {
    "coding":  { "name": "Coding",  "goal": 5, "created": "2026-10-01" },
    "reading": { "name": "Reading", "goal": 7, "created": "2026-10-04" }
  },
  "sessions": {
    "coding":  { "2026-10-03": "wrote the parser #python" },
    "reading": { "2026-10-04": "chapter four #books" }
  },
  "history": []
}
```

Version 1 files held a single `goal` and one flat `sessions` map. They are
converted automatically on load into a one-habit version 2 document, so nothing
needs doing. Version 2 also reads single-habit view
(`{"goal", "sessions"}`) projections, which is what the statistics layer works
on.

A file that declares a *newer* schema version is left exactly as it is, with a
warning, rather than being rewritten by an older build that could drop fields it
does not understand.

The SQLite backend stores the same document as relational tables: `meta`,
`habits`, `sessions` and `history`. Databases written by version 1, which had a
flat `sessions` table, are rebuilt on first load and keep their data.

### SQLite backend

JSON is a good fit for one session per day. If you outgrow it:

```bash
ht migrate-to-sqlite --output ~/habit-tracker.sqlite3
ht --backend sqlite stats
```

You can also set `"backend": "sqlite"` in `config.json` to make it permanent.

## Configuration

Settings are resolved in this order, highest priority first:

1. command-line flags — `--data-dir`, `--backend`, `--tz`
2. environment variables
3. `config.json` in the data directory
4. built-in defaults

| Environment variable | Flag | Meaning |
| --- | --- | --- |
| `HABIT_TRACKER_DATA_DIR` | `--data-dir` | Where the data file lives |
| `HABIT_TRACKER_BACKEND` | `--backend` | `json` or `sqlite` |
| `HABIT_TRACKER_TZ` | `--tz` | IANA timezone, e.g. `Europe/London` |
| `HABIT_TRACKER_WEBHOOK_URL` | `--url` | Default target for `ht notify` |
| `HABIT_TRACKER_THEME` | `--theme` | Window appearance: `system`, `light` or `dark` |

```json
{
  "backend": "json",
  "timezone": "Europe/London",
  "webhook_url": "https://hooks.slack.com/services/...",
  "theme": "dark"
}
```

`theme` only affects the desktop window. `system` follows the desktop setting,
which on Windows is read from the registry and elsewhere from `GTK_THEME`,
falling back to light when the platform cannot be asked. `ht env` shows both the
configured mode and what it resolves to.

Use `--data-dir` to keep separate profiles, for example one per project:

```bash
ht --data-dir ~/work/journal mark -n "wrote the parser #python"
ht --data-dir ~/personal/journal stats
```

## Architecture

The core is pure: no I/O, no UI, and every function that needs the current date
accepts an optional `today` so it can be pinned in a test.

```
habit_tracker/
  state.py      document schema, habits, sessions, migration, undo history
  session.py    the shared session used by all three front-ends
  tracker.py    domain logic: streaks, goals, heatmap grid
  calendar.py   month grid and completion maths, shared by CLI and GUI
  tags.py       hashtag extraction and ranking
  dates.py      calendar helpers and lenient date parsing
  storage.py    JSON and SQLite backends behind one interface
  config.py     data locations, timezone, settings resolution
  backup.py     export/import, with no Tkinter import
  notify.py     webhook payloads and delivery, standard library only
  console.py    output layer (rich when available, plain otherwise)
  cli.py        argparse subcommands
  tui.py        interactive menu plus the Textual interface
  gui.py        Tkinter window
  monthgrid.py  clickable month widget, drawn from calendar.py
  heatmap.py    week-aligned heatmap widget
  picker.py     date and note prompts (tkcalendar when available)
```

Dependency direction is one-way: `cli`, `tui` and `gui` depend on the core, and
the core depends on nothing. `gui` is imported lazily, so the CLI runs on a
machine with no Tkinter installed.

`session.py` exists so the three front-ends stopped each implementing their own
copy of the same rules: which habit is active, that every mutation records an
undo step, and that a write to an unknown habit fails loudly instead of landing
in the wrong one. `calendar.py` exists for the same reason in the other
direction: the CLI's `ht month` and the GUI's month grid read one model, so they
cannot disagree about what a month looks like.

Where each optional library plugs in:

- **textual** → a `Textual` app inside `tui.py`, reusing the same `Session` that
  the plain menu uses.
- **rich** → already the default renderer in `console.py`; no other module
  formats output.
- **dateparser** → already consulted by `dates.parse_date` when installed.
- **platformdirs** → already consulted by `config.default_data_dir`.
- **tkcalendar** → already used by `picker.py` when installed.

The window's appearance is not an optional library. `theme.py` holds the light and
dark `Palette`, and `ui.apply_theme` pushes it into `tkinter.ttk` through the
bundled `clam` theme, because the native Windows and macOS themes ignore
`background` on most widgets. Every colour in the GUI comes from a palette
lookup; there are no hex literals outside `theme.py`.

`ttkbootstrap` used to be listed here. It is gone because version 2 replaced its
`ttk` theme with a separate widget library, so it stopped being a drop-in, and the
old call to it was silently failing anyway. `tkcalendar` is genuinely used and
stays.

- **sqlite** → already available as `storage.SqliteBackend`.

## Development

```bash
python -m pip install -e ".[dev,all]"

python -m pytest                    # 624 tests
python -m ruff check .
python -m ruff format .
python -m pytest --cov=habit_tracker
```

Tests cover the core modules, the CLI end to end, and the regressions worth
guarding: future days never count towards the weekly goal, the heatmap grid
stays week-aligned, the month grid and its summary agree, the CLI never imports
Tkinter, and a disabled goal never reads as 100% complete.

GUI tests need a display. They skip themselves when there is none, so the suite
still passes headless, but CI installs `xvfb` and treats a skip as a failure so
the window code is actually exercised on Linux.

GitHub Actions runs lint, tests across Windows and Ubuntu on Python 3.12 and
3.14, and builds a wheel, an sdist and the frozen desktop app on every push.
The frozen build is in CI because a bad entry script only fails at runtime:
PyInstaller will happily package a binary that dies on its first import.

### Building a standalone app

```bash
python -m pip install -e ".[all,build]"
pyinstaller habit_tracker.spec
```

Produces `dist/HabitTracker.exe` on Windows, or `dist/HabitTracker` elsewhere.
The spec collects the optional GUI extras only when they are installed.

The spec's entry script is `build_gui.py`, not `habit_tracker/gui.py`. PyInstaller
runs its entry script as a top-level `__main__`, so a module from inside the
package would fail on its first relative import.

## Roadmap

- Reminders, via a `ht remind` command and Windows Task Scheduler or cron
- Charts of monthly and weekday trends

## License

MIT. See [LICENSE](LICENSE).
