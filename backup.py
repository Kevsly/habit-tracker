import json
from pathlib import Path
from tkinter import filedialog, messagebox

import storage


def export_data():
    filetypes = [("JSON files", "*.json"), ("All files", "*.*")]
    filename = filedialog.asksaveasfilename(
        defaultextension=".json",
        filetypes=filetypes,
        title="Export Data",
    )
    if not filename:
        return False
    try:
        data = storage.load_data()
        with Path(filename).open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        messagebox.showinfo("Export", f"Data exported to {filename}")
        return True
    except Exception as e:
        messagebox.showerror("Export Error", str(e))
        return False


def import_data():
    filetypes = [("JSON files", "*.json"), ("All files", "*.*")]
    filename = filedialog.askopenfilename(
        filetypes=filetypes,
        title="Import Data",
    )
    if not filename:
        return None
    try:
        with Path(filename).open("r", encoding="utf-8") as f:
            data = json.load(f)
        # Basic validation
        if not isinstance(data, dict):
            raise ValueError("Invalid data format")
        if "goal" not in data:
            data["goal"] = storage.DEFAULT_GOAL
        if "sessions" not in data or not isinstance(data["sessions"], dict):
            data["sessions"] = {}
        # Save imported data
        storage.save_data(data)
        messagebox.showinfo("Import", f"Data imported from {filename}")
        return data
    except Exception as e:
        messagebox.showerror("Import Error", str(e))
        return None
