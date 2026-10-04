import json
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data.json"
DEFAULT_GOAL = 5


def load_data(path=DATA_FILE):
    if not Path(path).exists():
        return {"goal": DEFAULT_GOAL, "sessions": {}}

    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    data.setdefault("goal", DEFAULT_GOAL)
    data.setdefault("sessions", {})
    return data


def save_data(data, path=DATA_FILE):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)