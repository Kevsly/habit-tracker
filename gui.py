import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from datetime import date

import storage
import tracker
import backup
from cal_heatmap import Heatmap
import tags


class HabitTrackerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title('Habit Tracker')
        self.root.geometry('750x550')

        self.data = storage.load_data()

        self.main_frame = ttk.Frame(root, padding='10')
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.create_widgets()

    def create_widgets(self):
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E))
        ttk.Button(btn_frame, text='Mark Today', command=self.mark_today).grid(row=0, column=0, padx=3, pady=5)
        ttk.Button(btn_frame, text='Mark Yesterday', command=self.mark_yesterday).grid(row=0, column=1, padx=3, pady=5)
        ttk.Button(btn_frame, text='Clear Selected', command=self.clear_selected).grid(row=0, column=2, padx=3, pady=5)
        ttk.Button(btn_frame, text='Refresh', command=self.refresh).grid(row=0, column=3, padx=3, pady=5)
        ttk.Button(btn_frame, text='Set Goal', command=self.set_goal).grid(row=0, column=4, padx=3, pady=5)
        ttk.Button(btn_frame, text='Export', command=self.export).grid(row=0, column=5, padx=3, pady=5)
        ttk.Button(btn_frame, text='Import', command=self.import_data).grid(row=0, column=6, padx=3, pady=5)

        self.stats_var = tk.StringVar()
        stats_label = ttk.Label(self.main_frame, textvariable=self.stats_var, font=('Consolas', 9))
        stats_label.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        self.progress = ttk.Progressbar(self.main_frame, orient='horizontal', mode='determinate', length=200)
        self.progress.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        notebook = ttk.Notebook(self.main_frame)
        notebook.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.main_frame.rowconfigure(3, weight=1)

        week_tab = ttk.Frame(notebook)
        notebook.add(week_tab, text='Week')
        heatmap_tab = ttk.Frame(notebook)
        notebook.add(heatmap_tab, text='Heatmap')
        tags_tab = ttk.Frame(notebook)
        notebook.add(tags_tab, text='Tags')

        list_frame = ttk.Frame(week_tab)
        list_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        week_tab.columnconfigure(0, weight=1)
        week_tab.rowconfigure(0, weight=1)
        columns = ('day', 'date', 'status', 'note')
        self.tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        self.tree.heading('day', text='Day')
        self.tree.heading('date', text='Date')
        self.tree.heading('status', text='Status')
        self.tree.heading('note', text='Note')
        self.tree.column('day', width=60)
        self.tree.column('date', width=100)
        self.tree.column('status', width=70)
        self.tree.column('note', width=320)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        self.heatmap = Heatmap(heatmap_tab, self.data)
        self.heatmap.pack(padx=10, pady=10)

        tags_frame = ttk.Frame(tags_tab, padding='10')
        tags_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tags_tab.columnconfigure(0, weight=1)
        tags_tab.rowconfigure(0, weight=1)
        self.tags_tree = ttk.Treeview(tags_frame, columns=('tag', 'count'), show='headings')
        self.tags_tree.heading('tag', text='Tag')
        self.tags_tree.heading('count', text='Count')
        self.tags_tree.column('tag', width=200)
        self.tags_tree.column('count', width=100)
        tags_scroll = ttk.Scrollbar(tags_frame, orient=tk.VERTICAL, command=self.tags_tree.yview)
        self.tags_tree.configure(yscroll=tags_scroll.set)
        self.tags_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tags_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))

        self.refresh()

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for item in self.tags_tree.get_children():
            self.tags_tree.delete(item)

        today = date.today()
        start = tracker.week_start(today)
        done, goal = tracker.week_progress(self.data, start)
        top, top_count = tracker.busiest_weekday(self.data)
        streak = tracker.current_streak(self.data)
        longest = tracker.longest_streak(self.data)
        total = tracker.total_sessions(self.data)

        self.stats_var.set(
            f'Week {start.isoformat()}: {done}/{goal} done | Streak: {streak} | Longest: {longest} | Total: {total} | Most active: {top} ({top_count})'
        )
        if goal > 0:
            pct = min(max(done / goal * 100, 0), 100)
        else:
            pct = 100 if done >= 0 else 0
        self.progress.configure(value=pct)

        for row in tracker.week_rows(self.data, start, today):
            status = 'DONE' if row['done'] else ('FUTURE' if row['future'] else 'TODO')
            note = row['note'][:60] if row['note'] else ''
            self.tree.insert('', tk.END, values=(row['label'], row['day'].isoformat(), status, note))

        self.heatmap.refresh(self.data)

        tag_counts = {}
        for note in self.data.get('sessions', {}).values():
            for t in tags.get_tags(note):
                tag_counts[t] = tag_counts.get(t, 0) + 1
        for tag, count in sorted(tag_counts.items(), key=lambda x: (-x[1], x[0])):
            self.tags_tree.insert('', tk.END, values=(tag, count))

    def mark_today(self):
        self.mark_day(date.today())

    def mark_yesterday(self):
        from datetime import timedelta
        self.mark_day(date.today() - timedelta(days=1))

    def mark_day(self, day):
        try:
            prev = tracker.note_for(self.data, day)
            note = simpledialog.askstring('Note', f'What did you work on {day.isoformat()}?', initialvalue=prev)
            if note is None:
                return
            tracker.mark_session(self.data, day, note.strip())
            storage.save_data(self.data)
            self.refresh()
        except Exception as e:
            messagebox.showerror('Error', str(e))

    def clear_selected(self):
        try:
            selected = self.tree.selection()
            if not selected:
                messagebox.showwarning('No selection', 'Select a day from the list.')
                return
            values = self.tree.item(selected[0], 'values')
            day_str = values[1]
            day = date.fromisoformat(day_str)
            if messagebox.askyesno('Confirm', f'Clear session on {day.isoformat()}?'):
                if tracker.clear_session(self.data, day):
                    storage.save_data(self.data)
                    messagebox.showinfo('Cleared', f'Cleared {day.isoformat()}.')
                else:
                    messagebox.showinfo('Nothing', f'Nothing marked on {day.isoformat()}.')
                self.refresh()
        except Exception as e:
            messagebox.showerror('Error', str(e))

    def set_goal(self):
        try:
            goal = simpledialog.askinteger('Weekly Goal', 'Sessions per week (0 turns goal off):', minvalue=0, initialvalue=self.data['goal'])
            if goal is None:
                return
            self.data['goal'] = int(goal)
            storage.save_data(self.data)
            self.refresh()
        except ValueError:
            messagebox.showerror('Error', 'Invalid goal value')
        except Exception as e:
            messagebox.showerror('Error', str(e))

    def export(self):
        try:
            backup.export_data()
        except Exception as e:
            messagebox.showerror('Error', str(e))

    def import_data(self):
        try:
            result = backup.import_data()
            if result is not None:
                self.data = result
                self.refresh()
        except Exception as e:
            messagebox.showerror('Error', str(e))


def main():
    root = tk.Tk()
    app = HabitTrackerGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
