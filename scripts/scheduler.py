"""Background thread: spoken reminders, meeting heads-up, and the "take notes?" offer."""
import threading
import time


class Scheduler(threading.Thread):
    def __init__(self, cfg: dict, memory, say, calendar_on: bool, notes=None):
        super().__init__(daemon=True)
        self.mem, self.say, self.calendar_on, self.notes = memory, say, calendar_on, notes
        self.lead = int(cfg.get("meeting_reminder_minutes", 10))
        self.notes_on = cfg.get("tools_enabled", {}).get("notes", False)
        self.announced: set = set()

    def run(self):
        while True:
            try:
                self.tick()
            except Exception as e:  # never let the thread die
                print("[scheduler]", e)
            time.sleep(30)

    def tick(self):
        for text in self.mem.due_reminders():
            self.say(f"Reminder: {text}")
        if not self.calendar_on:
            return
        import jcalendar

        for ev in jcalendar.upcoming_within(self.lead):
            key = ("soon", ev["title"], ev["start"].isoformat())
            if key not in self.announced:
                self.announced.add(key)
                mins = max(0, round((ev["start"].timestamp() - time.time()) / 60))
                self.say(f"Heads up: {ev['title']} starts in {mins} minutes.")
        if self.notes_on and self.notes:
            for ev in jcalendar.starting_now():
                key = ("start", ev["title"], ev["start"].isoformat())
                if key not in self.announced:
                    self.announced.add(key)
                    self.notes.offer(ev["title"])
                    self.say(f"{ev['title']} is starting. Want me to take notes? "
                             "Press Enter and say yes.")
