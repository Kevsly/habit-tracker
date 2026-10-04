"""Command-line front-end.

Subcommands are the primary interface, so the tracker can be scripted:

    ht mark yesterday -n "shipped #python"
    ht week --json | jq '.done'
    ht goal 4
    ht mark --habit reading 20-10-01

Running ``ht`` with no subcommand opens the interactive menu in
:mod:`habit_tracker.tui`. ``--gui`` is kept as a deprecated alias for ``ht gui``.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import __version__, backup, calendar, notify, state, storage, tags, tracker, tui
from .config import APP_TITLE, BACKENDS, THEMES, ConfigError
from .console import HAS_RICH, Console
from .dates import HAS_DATEPARSER, DateParseError, accepted_formats, parse_date
from .session import Session, SessionError, UnknownHabit
from .theme import ThemeError, normalise_mode, resolve_palette

log = logging.getLogger("habit_tracker")

OPTIONAL_PACKAGES = (
    ("rich", "prettier tables, panels and progress output", "rich"),
    ("textual", "full-screen terminal interface", "tui"),
    ("dateparser", 'phrases like "last friday"', "dates"),
    ("platformdirs", "correct per-user data directory", "dirs"),
    ("tkcalendar", "month calendar picker in the GUI", "gui"),
)


@dataclass
class Context:
    """A loaded session plus the console to report through."""

    session: Session
    console: Console

    @classmethod
    def build(cls, args: argparse.Namespace) -> Context:
        color = False if args.no_color else (True if args.color else None)
        console = Console(color=color, json_mode=args.json)
        return cls(session=Session.from_args(args), console=console)

    @property
    def view(self) -> dict:
        """Read-only single-habit projection for the analytics layer."""
        return self.session.view

    def today(self) -> date:
        return self.session.today()

    def habit_label(self) -> str:
        return self.session.habit_label


class UserError(Exception):
    """An error caused by user input rather than a bug."""


def interactive_input(prompt: str, fallback: str = "") -> str:
    """Read a line, returning ``fallback`` when stdin is not a terminal."""
    if not sys.stdin.isatty():
        return fallback
    try:
        return input(prompt).strip()
    except EOFError:
        return fallback


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    return input(prompt).strip().lower() in ("y", "yes")


def parse_day(text: str, today: date, allow_future: bool = False) -> date:
    """Parse a day argument, reporting problems through the console."""
    try:
        return parse_date(text, today=today, allow_future=allow_future)
    except DateParseError as exc:
        raise UserError(str(exc)) from exc


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def cmd_mark(ctx: Context, args: argparse.Namespace) -> int:
    session = ctx.session
    day = parse_day(args.day or "today", ctx.today(), args.allow_future)
    note = args.note if args.note is not None else interactive_input("  Note (optional): ")
    for tag in tags.parse_tag_input(args.tag or ""):
        note = tags.add_tag_to_note(note, tag)

    previous = session.note(day)
    session.mark(day, note)
    session.save()

    ctx.console.emit(
        {
            "ok": True,
            "habit": session.habit,
            "habit_name": session.habit_label,
            "day": day.isoformat(),
            "note": note,
            "replaced": previous or None,
        }
    )
    ctx.console.success(f"Marked {day.isoformat()} for {session.habit_label}.")
    if previous:
        ctx.console.line(f"  Replaced previous note: {previous}")
    ctx.console.line(f"  Undo with: ht undo  ({session.undo_depth()} step(s) available)")
    return 0


def cmd_unmark(ctx: Context, args: argparse.Namespace) -> int:
    session = ctx.session
    day = parse_day(args.day or "today", ctx.today(), allow_future=True)
    if not confirm(f"  Clear {day.isoformat()}? (y/N): ", args.yes):
        ctx.console.warn("Cancelled.")
        return 1

    cleared = session.clear(day)
    session.save()

    ctx.console.emit(
        {
            "ok": cleared,
            "habit": session.habit,
            "day": day.isoformat(),
            "undo_available": session.undo_depth() > 0,
        }
    )
    if cleared:
        ctx.console.success(f"Cleared {day.isoformat()}.")
        ctx.console.line("  Undo with: ht undo")
    else:
        ctx.console.line(f"  Nothing was marked on {day.isoformat()}.")
    return 0 if cleared else 1


def cmd_undo(ctx: Context, args: argparse.Namespace) -> int:
    session = ctx.session
    restored = session.undo()
    if restored is None:
        ctx.console.emit({"ok": False, "undo_available": False})
        ctx.console.warn("Nothing to undo.")
        return 1

    session.save()
    ctx.console.emit(
        {
            "ok": True,
            "restored": restored,
            "habit": session.habit,
            "undo_available": session.undo_depth() > 0,
        }
    )
    ctx.console.success(f"Undone. {restored}.")
    if session.undo_depth():
        ctx.console.line(f"  {session.undo_depth()} more step(s) available.")
    return 0


def cmd_history(ctx: Context, args: argparse.Namespace) -> int:
    """List the undoable steps, newest first."""
    entries = ctx.session.history()
    ctx.console.emit({"steps": entries, "undo_available": bool(entries)})
    if not entries:
        ctx.console.line("No changes recorded yet.")
        return 0

    rows = []
    for step, entry in enumerate(entries, start=1):
        when = entry["at"].replace("T", " ") if entry["at"] else "-"
        rows.append(
            (
                f"{step}",
                when,
                entry["action"] or "(unlabelled change)",
                f"{entry['sessions']}",
            )
        )
    ctx.console.line("Undo history (newest first):")
    ctx.console.table(["#", "Recorded", "Change", "Sessions"], rows)
    ctx.console.line("")
    ctx.console.line("  Run 'ht undo' to roll back the newest step.")
    return 0


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def cmd_week(ctx: Context, args: argparse.Namespace) -> int:
    session = ctx.session
    today = ctx.today()
    anchor = parse_day(args.week_of, today, allow_future=True) if args.week_of else today
    start = tracker.week_start(anchor)
    done, goal = tracker.week_progress(session.view, start, today)
    rows = tracker.week_rows(session.view, start, today)

    ctx.console.emit(
        {
            "habit": session.habit,
            "habit_name": session.habit_label,
            "week_of": start.isoformat(),
            "done": done,
            "goal": goal,
            "days": [
                {
                    "date": row["day"].isoformat(),
                    "day": row["label"],
                    "done": row["done"],
                    "future": row["future"],
                    "note": row["note"],
                }
                for row in rows
            ],
        }
    )

    ctx.console.heading(f"Week of {start.isoformat()} - {session.habit_label}")
    ctx.console.table(
        ["", "Day", "Date", "Note"],
        [
            (
                "." if row["future"] else ("x" if row["done"] else " "),
                row["label"],
                row["day"].isoformat(),
                row["note"],
            )
            for row in rows
        ],
    )
    ctx.console.progress(done, goal)
    if goal and done >= goal:
        ctx.console.success("Goal reached.")
    return 0


def cmd_month(ctx: Context, args: argparse.Namespace) -> int:
    """Month grid plus completion percentage, over the whole month."""
    session = ctx.session
    today = ctx.today()
    try:
        anchor = calendar.parse_month(args.month) if args.month else today
    except ValueError as exc:
        raise UserError(str(exc)) from exc
    view = session.view
    summary = calendar.month_summary(anchor, view, today=today)
    weeks = calendar.month_grid(anchor, view, today=today)

    ctx.console.emit(
        {
            "habit": session.habit,
            "habit_name": session.habit_label,
            "month": anchor.strftime("%Y-%m"),
            "done": summary.done,
            "elapsed": summary.elapsed,
            "possible": summary.possible,
            "completion_rate": summary.rate,
            "best_day": summary.best_day,
            "weeks": [
                [
                    {
                        "date": cell.day.isoformat() if cell.day else None,
                        "done": cell.done,
                        "future": cell.future,
                        "today": cell.today,
                        "note": cell.note,
                    }
                    for cell in week
                ]
                for week in weeks
            ],
        }
    )

    ctx.console.heading(f"{anchor.strftime('%B %Y')} - {session.habit_label}")
    ctx.console.line("  " + "  ".join(calendar.MONTH_HEADER))
    for week in weeks:
        ctx.console.line("  " + "  ".join(cell.render() for cell in week))

    ctx.console.progress(summary.done, summary.possible)
    ctx.console.line(
        f"  {summary.done}/{summary.possible} days ({summary.rate:.0%})"
        + (f", best run {summary.best_day} days" if summary.best_day else "")
    )
    if summary.future_days:
        ctx.console.line(f"  {summary.future_days} day(s) still ahead.")
    return 0


def cmd_stats(ctx: Context, args: argparse.Namespace) -> int:
    session = ctx.session
    view = session.view
    today = ctx.today()

    done, goal = tracker.week_progress(view, today)
    streak = tracker.current_streak(view, today)
    longest = tracker.longest_streak(view)
    total = tracker.total_sessions(view)
    top, top_count = tracker.busiest_weekday(view)

    ctx.console.emit(
        {
            "habit": session.habit,
            "habit_name": session.habit_label,
            "current_streak": streak,
            "longest_streak": longest,
            "total_sessions": total,
            "all_habits_sessions": session.total_sessions(),
            "weekly_goal": goal,
            "week_done": done,
            "busiest_weekday": top,
            "busiest_count": top_count,
        }
    )

    ctx.console.heading(f"Stats - {session.habit_label}")
    ctx.console.detail("Current streak", f"{streak} day(s)")
    ctx.console.detail("Longest streak", f"{longest} day(s)")
    ctx.console.detail("Total sessions", total)
    ctx.console.detail("Weekly goal", goal or "off")
    ctx.console.detail("This week", f"{done}/{goal}" if goal else "no goal set")
    ctx.console.detail("Most active day", f"{top} ({top_count})" if top else "no data yet")
    ctx.console.detail("All habits", f"{session.total_sessions()} session(s)")
    ctx.console.detail("Undo available", f"{session.undo_depth()} step(s)")
    return 0


def cmd_tags(ctx: Context, args: argparse.Namespace) -> int:
    session = ctx.session
    if args.all:
        notes = session.notes_all()
        scope = "all habits"
    else:
        notes = session.notes_list()
        scope = session.habit_label

    ranked = tags.ranked_tag_counts(notes)
    ctx.console.emit(
        {
            "habit": None if args.all else session.habit,
            "scope": scope,
            "tags": [{"tag": tag, "count": count} for tag, count in ranked],
        }
    )
    ctx.console.heading(f"Tags - {scope}")
    if not ranked:
        ctx.console.line("  No tags yet. Add #hashtags to a session note.")
        return 0
    ctx.console.table(["Tag", "Count"], [(f"#{tag}", count) for tag, count in ranked])
    return 0


# --------------------------------------------------------------------------
# Goals and habits
# --------------------------------------------------------------------------


def cmd_goal(ctx: Context, args: argparse.Namespace) -> int:
    session = ctx.session
    if args.value is None:
        current = session.goal()
        ctx.console.emit({"habit": session.habit, "goal": current})
        ctx.console.line(f"  Weekly goal for {session.habit_label} is {current or 'off'}.")
        return 0
    if args.value < 0:
        raise UserError("Goal cannot be negative. Use 0 to turn the goal off.")

    applied = session.set_goal(args.value)
    session.save()
    ctx.console.emit({"habit": session.habit, "goal": applied})
    ctx.console.success(f"Weekly goal for {session.habit_label} set to {applied or 'off'}.")
    return 0


def cmd_habit(ctx: Context, args: argparse.Namespace) -> int:
    """Dispatch a ``ht habit ACTION`` subcommand.

    ``state`` reports unknown habits and impossible removals as ``KeyError``
    and ``ValueError``; both are user mistakes, so they are reported as such.
    """
    try:
        return _run_habit_action(ctx, args.habit_command, args)
    except KeyError as exc:
        raise UserError(str(exc).strip("'\"")) from exc
    except ValueError as exc:
        raise UserError(str(exc)) from exc


def _run_habit_action(ctx: Context, action: str, args: argparse.Namespace) -> int:
    session = ctx.session

    if action == "list":
        rows = session.habits()
        ctx.console.emit(
            {
                "active": session.habit,
                "habits": [
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "goal": row["goal"],
                        "sessions": row["sessions"],
                        "created": row["created"],
                        "active": row["active"],
                    }
                    for row in rows
                ],
            }
        )
        ctx.console.heading("Habits")
        ctx.console.table(
            ["", "Name", "Id", "Goal", "Sessions", "Created"],
            [
                (
                    "*" if row["active"] else " ",
                    row["name"],
                    row["id"],
                    row["goal"] or "off",
                    row["sessions"],
                    row["created"],
                )
                for row in rows
            ],
        )
        ctx.console.line("  Target one with --habit, or switch with: ht habit use <name>")
        return 0

    if action == "add":
        name = args.name
        goal = 5 if args.goal is None else args.goal
        if goal < 0:
            raise UserError("Goal cannot be negative.")
        habit_id = session.add_habit(name, goal=goal, activate=args.activate)
        ctx.console.emit({"ok": True, "id": habit_id, "goal": goal})
        ctx.console.success(f"Added habit {name!r} with id {habit_id!r} (goal {goal or 'off'}).")
        return 0

    if action == "rename":
        previous = session.habit_label
        session.rename_habit(args.name)
        ctx.console.emit({"ok": True, "habit": session.habit})
        ctx.console.success(f"Renamed {previous!r} to {args.name!r} (id unchanged).")
        return 0

    if action == "use":
        habit_id = session.use_habit(args.name)
        ctx.console.emit({"ok": True, "habit": habit_id})
        ctx.console.success(f"Now tracking {session.habit_label!r}.")
        return 0

    if action == "rm":
        name = args.name or session.habit
        # Resolve first so an unknown habit fails before the confirmation prompt.
        habit_id = state.resolve_strict(session.document, name)
        label = state.habit_name(session.document, habit_id)
        if not confirm(f"  Remove habit {label!r} and all of its sessions? (y/N): ", args.force):
            ctx.console.warn("Cancelled.")
            return 1
        removed = session.remove_habit(habit_id)
        ctx.console.emit({"ok": True, "removed": removed})
        ctx.console.success(f"Removed habit {removed!r} and its sessions.")
        if session.undo_depth():
            ctx.console.line("  Undo with: ht undo")
        return 0

    raise UserError(f"Unknown habit command {action!r}.")  # pragma: no cover


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------


def cmd_notify(ctx: Context, args: argparse.Namespace) -> int:
    """Send a streak or goal summary to a configured webhook."""
    session = ctx.session
    settings = ctx.session.settings

    try:
        report = notify.build_report(
            session.view,
            today=ctx.today(),
            habit=session.habit_label,
            include_note=args.include_note,
            note=session.note(args.day) if args.day else "",
        )
    except notify.NotificationError as exc:
        raise UserError(str(exc)) from exc

    target = getattr(args, "url", None) or settings.webhook_url
    ctx.console.emit(
        {
            "habit": session.habit,
            "message": report.message,
            "dry_run": bool(args.dry_run),
            "configured": bool(target),
        }
    )
    ctx.console.heading("Notification")
    ctx.console.line(f"  {report.message}")

    if args.dry_run:
        ctx.console.line("  Dry run; nothing was sent.")
        return 0
    if not target:
        raise UserError(
            "No webhook configured. Set HABIT_TRACKER_WEBHOOK_URL or "
            '"webhook_url" in config.json, or pass --dry-run.'
        )

    try:
        notify.send(target, report)
    except notify.NotificationError as exc:
        ctx.console.warn(f"Could not send notification: {exc}")
        return 1
    ctx.console.success(f"Sent to {target}.")
    return 0


# --------------------------------------------------------------------------
# Backup and maintenance
# --------------------------------------------------------------------------


def legacy_checkout_file() -> Path | None:
    """A pre-package ``data.json`` next to the source checkout, if present.

    Only ``ht migrate-legacy`` wants this, so it lives here rather than in
    :mod:`habit_tracker.config`. Installed copies have no checkout to find.
    """
    candidate = Path(__file__).resolve().parent.parent / "data.json"
    return candidate if candidate.is_file() else None


def cmd_migrate_legacy(ctx: Context, args: argparse.Namespace) -> int:
    """Import a pre-package ``data.json`` sitting next to the source checkout."""
    session = ctx.session
    legacy = legacy_checkout_file()
    if legacy is None:
        raise UserError("No pre-package data.json was found.")
    if session.settings.data_file.exists() and not args.force:
        raise UserError(
            f"{session.settings.data_file} already exists. Re-run with --force to overwrite it."
        )

    imported = backup.import_from(legacy)
    session.document = imported
    session.save()
    count = sum(len(notes) for notes in imported.get("sessions", {}).values())
    ctx.console.emit({"ok": True, "source": str(legacy), "sessions": count})
    ctx.console.success(f"Imported {count} session(s) from {legacy}")
    return 0


def cmd_export(ctx: Context, args: argparse.Namespace) -> int:
    written = backup.export_to(args.path, ctx.session.document)
    ctx.console.emit({"ok": True, "path": str(written)})
    ctx.console.success(f"Exported to {written}")
    return 0


def cmd_import(ctx: Context, args: argparse.Namespace) -> int:
    session = ctx.session
    imported = backup.import_from(args.path)
    existing = session.total_sessions()
    if (
        not args.force
        and existing
        and not confirm(f"  Replace {existing} existing session(s)? (y/N): ", False)
    ):
        ctx.console.warn("Cancelled.")
        return 1
    session.document = imported
    session.save()
    ctx.console.emit({"ok": True, "sessions": sum(len(v) for v in imported["sessions"].values())})
    counted = sum(len(v) for v in imported["sessions"].values())
    ctx.console.success(f"Imported {counted} session(s).")
    return 0


def cmd_migrate(ctx: Context, args: argparse.Namespace) -> int:
    session = ctx.session
    target = storage.migrate_json_to_sqlite(session.settings.data_file, args.output)
    ctx.console.emit({"ok": True, "path": str(target)})
    ctx.console.success(f"Wrote {target}. Run future commands with --backend sqlite.")
    return 0


def cmd_env(ctx: Context, args: argparse.Namespace) -> int:
    session = ctx.session
    installed = {}
    for module_name, _purpose, _extra in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(module_name)
        except ImportError:
            installed[module_name] = False
        else:
            installed[module_name] = True

    ctx.console.emit(
        {
            "data_dir": str(session.settings.data_dir),
            "data_file": str(session.settings.data_file),
            "backend": session.settings.backend,
            "timezone": session.settings.timezone or "system local",
            "today": ctx.today().isoformat(),
            "version": __version__,
            "schema_version": storage.SCHEMA_VERSION,
            "active_habit": session.habit,
            "habits": [row["id"] for row in session.habits()],
            "webhook_configured": bool(session.settings.webhook_url),
            "theme": session.settings.theme,
            "theme_resolved": resolve_palette(session.settings.theme).name,
            "optional_packages": installed,
        }
    )

    ctx.console.heading("Configuration")
    ctx.console.detail("Version", __version__)
    ctx.console.detail("Schema version", storage.SCHEMA_VERSION)
    ctx.console.detail("Data directory", session.settings.data_dir)
    ctx.console.detail("Data file", session.settings.data_file)
    ctx.console.detail("Backend", session.settings.backend)
    ctx.console.detail("Timezone", session.settings.timezone or "system local")
    ctx.console.detail("Today", ctx.today().isoformat())
    ctx.console.detail("Active habit", f"{session.habit_label} ({session.habit})")
    ctx.console.detail("Habits", f"{len(session.habits())} defined")
    webhook = session.settings.webhook_url
    ctx.console.detail("Webhook", "configured" if webhook else "not configured")
    ctx.console.detail(
        "Theme",
        f"{session.settings.theme} (renders as {resolve_palette(session.settings.theme).name})",
    )
    ctx.console.detail("Rich output", "yes" if HAS_RICH else "no (pip install habit-tracker[rich])")
    ctx.console.detail("Date phrases", "yes" if HAS_DATEPARSER else "no (install [dates])")

    ctx.console.heading("Optional packages")
    ctx.console.table(
        ["Package", "Provides", "Installed"],
        [
            (name, purpose, "yes" if installed[name] else f"no (install [{extra}])")
            for name, purpose, extra in OPTIONAL_PACKAGES
        ],
    )
    return 0


def cmd_gui(ctx: Context, args: argparse.Namespace) -> int:
    from . import gui

    try:
        theme_mode = normalise_mode(args.theme or ctx.session.settings.theme)
    except ThemeError as exc:
        raise UserError(str(exc)) from exc
    gui.main(ctx.session.settings, theme=theme_mode)
    return 0


def cmd_tui(ctx: Context, args: argparse.Namespace) -> int:
    return tui.run(ctx.session.settings, ctx.console, habit=args.habit)


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


def add_habit_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-H",
        "--habit",
        metavar="NAME",
        help="operate on this habit instead of the active one",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ht",
        description=f"{APP_TITLE}: a habit tracker for coding sessions.",
        epilog=f"Day arguments accept: {accepted_formats()}",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--data-dir", metavar="PATH", help="directory holding the data file")
    parser.add_argument("--backend", choices=BACKENDS, help="storage backend")
    parser.add_argument("--tz", metavar="ZONE", help="IANA timezone, e.g. Europe/London")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument("--color", action="store_true", help="force coloured output")
    parser.add_argument("--no-color", action="store_true", help="disable coloured output")
    parser.add_argument("-v", "--verbose", action="store_true", help="log to stderr for debugging")
    parser.add_argument(
        "--gui",
        dest="legacy_gui",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    subparsers = parser.add_subparsers(dest="command")

    mark = subparsers.add_parser("mark", help="record a session")
    mark.add_argument("day", nargs="?", help="day to mark (default: today)")
    mark.add_argument("-n", "--note", help="session note; #hashtags are indexed")
    mark.add_argument("--tag", help="extra tags, comma or space separated")
    mark.add_argument("--allow-future", action="store_true", help="permit a future date")
    add_habit_flags(mark)
    mark.set_defaults(handler=cmd_mark)

    unmark = subparsers.add_parser("unmark", help="remove a session")
    unmark.add_argument("day", nargs="?", help="day to clear (default: today)")
    unmark.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    add_habit_flags(unmark)
    unmark.set_defaults(handler=cmd_unmark)

    week = subparsers.add_parser("week", help="show the current or a given week")
    week.add_argument("--week-of", metavar="DAY", help="any day in the week to show")
    add_habit_flags(week)
    week.set_defaults(handler=cmd_week)

    month = subparsers.add_parser("month", help="show a month grid and completion rate")
    month.add_argument("--month", metavar="YYYY-MM", help="month to show (default: this month)")
    add_habit_flags(month)
    month.set_defaults(handler=cmd_month)

    stats_parser = subparsers.add_parser("stats", help="show streaks and totals")
    add_habit_flags(stats_parser)
    stats_parser.set_defaults(handler=cmd_stats)

    tags_parser = subparsers.add_parser("tags", help="list note tags")
    tags_parser.add_argument("-a", "--all", action="store_true", help="include every habit")
    add_habit_flags(tags_parser)
    tags_parser.set_defaults(handler=cmd_tags)

    goal = subparsers.add_parser("goal", help="show or set the weekly goal")
    goal.add_argument("value", nargs="?", type=int, help="sessions per week, 0 to disable")
    add_habit_flags(goal)
    goal.set_defaults(handler=cmd_goal)

    undo_parser = subparsers.add_parser("undo", help="roll back the last change")
    undo_parser.set_defaults(handler=cmd_undo)

    history_parser = subparsers.add_parser("history", help="list undoable changes")
    history_parser.set_defaults(handler=cmd_history)

    habit = subparsers.add_parser("habit", help="list, add, rename, switch or remove habits")
    habit_sub = habit.add_subparsers(dest="habit_command", metavar="ACTION")
    habit_sub.required = True

    habit_list = habit_sub.add_parser("list", help="show every habit")
    habit_list.set_defaults(handler=cmd_habit)

    habit_add = habit_sub.add_parser("add", help="create a habit")
    habit_add.add_argument("name", help="display name")
    habit_add.add_argument("--goal", type=int, help="weekly goal (default 5, 0 disables)")
    habit_add.add_argument("--activate", action="store_true", help="switch to it immediately")
    habit_add.set_defaults(handler=cmd_habit)

    habit_rename = habit_sub.add_parser("rename", help="rename a habit, keeping its id")
    habit_rename.add_argument("name", help="new display name")
    add_habit_flags(habit_rename)
    habit_rename.set_defaults(handler=cmd_habit)

    habit_use = habit_sub.add_parser("use", help="change the default habit")
    habit_use.add_argument("name", help="habit id or name")
    habit_use.set_defaults(handler=cmd_habit)

    habit_rm = habit_sub.add_parser("rm", help="delete a habit and its sessions")
    habit_rm.add_argument("name", nargs="?", help="habit id or name (default: active)")
    habit_rm.add_argument("-f", "--force", action="store_true", help="skip the confirmation")
    habit_rm.set_defaults(handler=cmd_habit)

    notify_parser = subparsers.add_parser("notify", help="send a summary to a webhook")
    notify_parser.add_argument(
        "--dry-run", action="store_true", help="print the message without sending"
    )
    notify_parser.add_argument(
        "--include-note", action="store_true", help="include the session note in the payload"
    )
    notify_parser.add_argument("--day", metavar="DAY", help="day whose note may be included")
    notify_parser.add_argument(
        "-u", "--url", metavar="URL", help="webhook URL, overriding the configured one"
    )
    add_habit_flags(notify_parser)
    notify_parser.set_defaults(handler=cmd_notify)

    export = subparsers.add_parser("export", help="write a JSON backup")
    export.add_argument("path", help="destination file")
    export.set_defaults(handler=cmd_export)

    importer = subparsers.add_parser("import", help="restore from a JSON backup")
    importer.add_argument("path", help="source file")
    importer.add_argument("-f", "--force", action="store_true", help="skip confirmation")
    importer.set_defaults(handler=cmd_import)

    migrate = subparsers.add_parser("migrate-to-sqlite", help="copy the data file into SQLite")
    migrate.add_argument("--output", metavar="PATH", help="destination database")
    migrate.set_defaults(handler=cmd_migrate)

    legacy = subparsers.add_parser(
        "migrate-legacy", help="import a pre-package data.json from a source checkout"
    )
    legacy.add_argument("-f", "--force", action="store_true", help="overwrite existing data")
    legacy.set_defaults(handler=cmd_migrate_legacy)

    subparsers.add_parser("env", help="show resolved settings and optional packages").set_defaults(
        handler=cmd_env
    )
    gui_parser = subparsers.add_parser("gui", help="open the desktop window")
    gui_parser.add_argument(
        "--theme",
        choices=THEMES,
        help="window appearance: system (default), light or dark",
    )
    gui_parser.set_defaults(handler=cmd_gui)
    tui_parser = subparsers.add_parser("tui", help="open the interactive terminal menu")
    add_habit_flags(tui_parser)
    tui_parser.set_defaults(handler=cmd_tui)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    console = Console(color=False if args.no_color else None, json_mode=args.json)

    try:
        if not args.command:
            if args.legacy_gui:
                return cmd_gui(Context.build(args), args)
            if sys.stdin.isatty():
                ctx = Context.build(args)
                return tui.run(ctx.session.settings, ctx.console)
            parser.print_help()
            return 0

        ctx = Context.build(args)
        return args.handler(ctx, args)
    except UserError as exc:
        console.error(str(exc))
        return 2
    except UnknownHabit as exc:
        console.error(str(exc))
        return 2
    except ValueError as exc:
        console.error(str(exc))
        return 2
    except (ConfigError, storage.StorageError, backup.BackupError) as exc:
        console.error(str(exc))
        return 1
    except SessionError as exc:
        console.error(str(exc))
        return 1
    except KeyboardInterrupt:
        console.error("Interrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
