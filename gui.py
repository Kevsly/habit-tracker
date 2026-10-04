import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from datetime import date

import storage
import tracker


class HabitTrackerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Coding Habit Tracker")
        self.root.geometry("600x400")

        self.data = storage.load_data()

        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.create_widgets()

    def create_widgets(self):
        # Buttons
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E))
        ttk.Button(btn_frame, text="Mark Today", command=self.mark_today).grid(
            row=0, column=0, padx=5, pady=5
        )
        ttk.Button(btn_frame, text="Mark Yesterday", command=self.mark_yesterday).grid(
            row=0, column=1, padx=5, pady=5
        )
        ttk.Button(btn_frame, text="Clear Selected", command=self.clear_selected).grid(
            row=0, column=2, padx=5, pady=5
        )
        ttk.Button(btn_frame, text="Refresh", command=self.refresh).grid(
            row=0, column=3, padx=5, pady=5
        )
        ttk.Button(btn_frame, text="Set Goal", command=self.set_goal).grid(
            row=0, column=4, padx=5, pady=5
        )

        # Stats
        self.stats_var = tk.StringVar()
        stats_label = ttk.Label(
            self.main_frame, textvariable=self.stats_var, font=("Consolas", 9)
        )
        stats_label.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Week list
        list_frame = ttk.Frame(self.main_frame)
        list_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(2, weight=1)

        columns = ("day", "date", "status", "note")
        self.tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", height=10
        )
        self.tree.heading("day", text="Day")
        self.tree.heading("date", text="Date")
        self.tree.heading("status", text="Status")
        self.tree.heading("note", text="Note")
        self.tree.column("day", width=60)
        self.tree.column("date", width=100)
        self.tree.column("status", width=60)
        self.tree.column("note", width=300)

        scrollbar = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.tree.yview
        )
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.refresh()

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        today = date.today()
        start = tracker.week_start(today)
        done, goal = tracker.week_progress(self.data, start)
        top, top_count = tracker.busiest_weekday(self.data)
        streak = tracker.current_streak(self.data)
        longest = tracker.longest_streak(self.data)
        total = tracker.total_sessions(self.data)

        self.stats_var.set(
            f"Week {start.isoformat()}: {done}/{goal} done | "
            f"Streak: {streak} | Longest: {longest} | Total: {total} | "
            f"Most active: {top} ({top_count})"
        )

        for row in tracker.week_rows(self.data, start, today):
            status = "DONE" if row["done"] else ("FUTURE" if row["future"] else "TODO")
            note = row["note"][:60] if row["note"] else ""
            self.tree.insert(
                "",
                tk.END,
                values=(row["label"], row["day"].isoformat(), status, note),
            )

    def mark_today(self):
        self.mark_day(date.today())

    def mark_yesterday(self):
        self.mark_day(date.today().replace(day=date.today().day) if False else None)  # dummy

    def mark_yesterday(self):
        from datetime import timedelta

        self.mark_day(date.today() - timedelta(days=1))

    def mark_day(self, day):
        prev = tracker.note_for(self.data, day)
        note = simpledialog.askstring(
            "Note", f"What did you work on {day.isoformat()}?", initialvalue=prev
        )
        if note is None:
            return
        tracker.mark_session(self.data, day, note.strip())
        storage.save_data(self.data)
        self.refresh()

    def clear_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No selection", "Select a day from the list.")
            return
        values = self.tree.item(selected[0], "values")
        day_str = values[1]
        from datetime import date

        day = date.fromisoformat(day_str)
        if tracker.clear_session(self.data, day):
            storage.save_data(self.data)
            messagebox.showinfo("Cleared", f"Cleared {day.isoformat()}.")
        else:
            messagebox.showinfo("Nothing", f"Nothing marked on {day.isoformat()}.")
        self.refresh()

    def set_goal(self):
        goal = simpledialog.askinteger(
            "Weekly Goal",
            "Sessions per week (0 turns goal off):",
            minvalue=0,
            initialvalue=self.data["goal"],
        )
        if goal is None:
            return
        self.data["goal"] = goal
        storage.save_data(self.data)
        self.refresh()


def main():
    root = tk.Tk()
    app = HabitTrackerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
