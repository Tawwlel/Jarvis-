"""Background thread: speaks due reminders and warns before meetings."""
import threading
import time


class Scheduler(threading.Thread):
    def __init__(self, cfg: dict, memory, say, calendar_on: bool):
        super().__init__(daemon=True)
        self.mem, self.say, self.calendar_on = memory, say, calendar_on
        self.lead = int(cfg.get("meeting_reminder_minutes", 10))
        self.announced: set = set()

    def run(self):
        while True:
            try:
                for text in self.mem.due_reminders():
                    self.say(f"Reminder: {text}")
                if self.calendar_on:
                    import jcalendar

                    for ev in jcalendar.upcoming_within(self.lead):
                        key = (ev["title"], ev["start"].isoformat())
                        if key not in self.announced:
                            self.announced.add(key)
                            mins = max(0, int((ev["start"].timestamp() - time.time()) / 60))
                            self.say(f"Heads up: {ev['title']} starts in {mins} minutes.")
            except Exception as e:  # never let the thread die
                print("[scheduler]", e)
            time.sleep(30)
