from datetime import date, timedelta

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ONE_DAY = timedelta(days=1)


def resolve_day(text, today=None):
    today = today or date.today()
    cleaned = text.strip().lower()

    if cleaned in ("", "t", "today"):
        return today
    if cleaned in ("y", "yesterday"):
        return today - ONE_DAY
    return date.fromisoformat(cleaned)


def week_start(day):
    return day - timedelta(days=day.weekday())


def week_days(day):
    first = week_start(day)
    return [first + timedelta(days=offset) for offset in range(7)]


def mark_session(data, day, note):
    data["sessions"][day.isoformat()] = note
    return data


def clear_session(data, day):
    removed = data["sessions"].pop(day.isoformat(), None)
    return removed is not None


def has_session(data, day):
    return day.isoformat() in data["sessions"]


def note_for(data, day):
    return data["sessions"].get(day.isoformat(), "")


def week_rows(data, day, today=None):
    today = today or date.today()
    return [
        {
            "day": current,
            "label": WEEKDAY_NAMES[current.weekday()],
            "done": has_session(data, current),
            "note": note_for(data, current),
            "future": current > today,
        }
        for current in week_days(day)
    ]


def week_progress(data, day):
    done = sum(1 for row in week_rows(data, day) if row["done"])
    return done, data["goal"]


def current_streak(data, today=None):
    today = today or date.today()
    sessions = data["sessions"]

    cursor = today if today.isoformat() in sessions else today - ONE_DAY
    streak = 0
    while cursor.isoformat() in sessions:
        streak += 1
        cursor -= ONE_DAY
    return streak


def longest_streak(data):
    days = sorted(date.fromisoformat(key) for key in data["sessions"])
    best = 0
    run = 0
    previous = None

    for current in days:
        run = run + 1 if previous and current - previous == ONE_DAY else 1
        best = max(best, run)
        previous = current

    return best


def total_sessions(data):
    return len(data["sessions"])


def busiest_weekday(data):
    counts = {name: 0 for name in WEEKDAY_NAMES}
    for key in data["sessions"]:
        day = date.fromisoformat(key)
        counts[WEEKDAY_NAMES[day.weekday()]] += 1

    top = max(counts, key=counts.get)
    return top, counts[top]