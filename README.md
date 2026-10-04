# Habit Tracker

A simple habit tracker for coding sessions with both CLI and GUI interfaces.

## Features
- Mark/unmark coding sessions by day
- View current week progress with visual progress bar
- GitHub-style heatmap calendar view
- Tag sessions with #hashtags (e.g., #python #learning)
- View stats by tag and busiest weekdays
- Track streaks (current and longest)
- Set weekly goal
- Export/import data backup
- Error handling and input validation

## Usage

### CLI
`ash
python main.py
`

### GUI (Tkinter)
`ash
python main.py --gui
`

Or run directly:
`ash
python gui.py
`

### Backup/Export
Use the GUI's Export/Import buttons to backup your data.

## Data
Data is stored in data.json (ignored by git).

## Tags
Add hashtags to your session notes (e.g., "Worked on #python #fastapi") to track time by topic.

## Requirements
No external dependencies. Uses built-in modules: json, pathlib, datetime, tkinter, sys, os.

## License
MIT License - see LICENSE file for details.
