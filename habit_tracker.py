import os

import storage
import tracker

MENU = """
  Coding Habit Tracker
  --------------------
  1) Mark a session
  2) Unmark a day
  3) This week
  4) Stats
  5) Set weekly goal
  6) Quit
"""


def clear():
    os.system("cls")


def pause():
    input("\n  Press Enter to continue...")


def ask_day():
    raw = input("  Which day? (today / yesterday / YYYY-MM-DD): ")
    try:
        return tracker.resolve_day(raw)
    except ValueError:
        print("  Could not read that date. Try 2026-10-05 style input.")
        return None


def do_mark(data):
    day = ask_day()
    if day is None:
        return

    previous = tracker.note_for(data, day)
    note = input("  What did you work on? (optional): ").strip()
    tracker.mark_session(data, day, note)
    print(f"  Marked {day.isoformat()}.")
    if previous:
        print(f"  Replaced previous note: {previous}")


def do_unmark(data):
    day = ask_day()
    if day is None:
        return

    confirm = input(f"  Clear session on {day.isoformat()}? (y/N): ").strip().lower()
    if confirm not in ("y", "yes"):
        print("  Cancelled.")
        return

    if tracker.clear_session(data, day):
        print(f"  Cleared {day.isoformat()}.")
    else:
        print(f"  Nothing was marked on {day.isoformat()}.")


def show_week(data):
    start = tracker.week_start(tracker.resolve_day("today"))
    done, goal = tracker.week_progress(data, start)

    print(f"\n  Week of {start.isoformat()}    {done} / {goal} done\n")
    for row in tracker.week_rows(data, start):
        if row["future"]:
            marker, note = "  .", ""
        elif row["done"]:
            marker, note = "[x]", row["note"]
        else:
            marker, note = "[ ]", ""
        suffix = f"  {note}" if note else ""
        print(f"  {marker} {row['label']}  {row['day'].isoformat()}{suffix}")

    if goal:
        print(f"\n  {'Goal reached' if done >= goal else f'{goal - done} to go'}")


def show_stats(data):
    top, top_count = tracker.busiest_weekday(data)
    streak = tracker.current_streak(data)

    print("\n  Stats\n")
    print(f"  Current streak     {streak} day(s)")
    print(f"  Longest streak     {tracker.longest_streak(data)} day(s)")
    print(f"  Total sessions     {tracker.total_sessions(data)}")
    print(f"  Weekly goal        {data['goal']}")
    print(f"  Most active day    {top} ({top_count})")


def set_goal(data):
    raw = input("  Sessions per week (0 turns the goal off): ")
    try:
        goal = int(raw)
    except ValueError:
        print("  That is not a number.")
        return

    if goal < 0:
        print("  Goal cannot be negative.")
        return

    data["goal"] = goal
    print(f"  Weekly goal set to {goal}.")


ACTIONS = {
    "1": do_mark,
    "2": do_unmark,
    "3": show_week,
    "4": show_stats,
    "5": set_goal,
}


def main():
    data = storage.load_data()

    while True:
        clear()
        print(MENU)
        choice = input("  Pick an option: ").strip()

        if choice == "6":
            storage.save_data(data)
            print("  Saved. See you tomorrow.")
            return

        action = ACTIONS.get(choice)
        if action is None:
            print("  Unknown option.")
            pause()
            continue

        action(data)
        if choice in ("1", "2", "5"):
            storage.save_data(data)
        pause()


if __name__ == "__main__":
    main()
