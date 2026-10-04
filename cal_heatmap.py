from datetime import date, timedelta
from tkinter import ttk
import tkinter as tk


class Heatmap(tk.Frame):
    def __init__(self, master, data, **kwargs):
        super().__init__(master, **kwargs)
        self.data = data
        self.days = []
        self.cells = []
        self._build()

    def _build(self):
        # Show last 12 weeks (84 days)
        end = date.today()
        start = end - timedelta(days=83)
        # align to Sunday? start from start
        days = []
        cur = start
        while cur <= end:
            days.append(cur)
            cur += timedelta(days=1)
        self.days = days
        # grid: 12 cols (weeks) x 7 rows (days)
        for i, d in enumerate(days):
            row = i % 7
            col = i // 7
            status = self._status(d)
            btn = tk.Canvas(self, width=16, height=16, bg=self._color(status), bd=1, relief=tk.FLAT, highlightthickness=0)
            btn.grid(row=row, column=col, padx=1, pady=1)
            self.cells.append(btn)

    def _status(self, d):
        key = d.isoformat()
        sessions = self.data.get('sessions', {})
        if key in sessions:
            return 'done'
        if d > date.today():
            return 'future'
        return 'miss'

    def _color(self, status):
        if status == 'done':
            return '#2da44e'  # green
        if status == 'future':
            return '#f6f8fa'  # light
        return '#ebedf0'  # grey

    def refresh(self, data):
        self.data = data
        for i, d in enumerate(self.days):
            status = self._status(d)
            self.cells[i].configure(bg=self._color(status))
