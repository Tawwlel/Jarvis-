"""Background thread: reminders, daily brief, meeting heads-up (with prep), notes offer."""
import datetime as dt
import threading
import time


class Scheduler(threading.Thread):
    def __init__(self, cfg: dict, memory, say, notes=None, brief_fn=None, on_offer=None):
        super().__init__(daemon=True)
        self.cfg, self.mem, self.say, self.notes, self.brief_fn = cfg, memory, say, notes, brief_fn
        self.on_offer = on_offer  # called after "want notes?" so the assistant starts listening
        self.announced: set = set()

    @property
    def flags(self):
        return self.cfg.get("tools_enabled", {})

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
        self.daily_brief()
        if not self.flags.get("calendar"):
            return
        import jcalendar

        lead = int(self.cfg.get("meeting_reminder_minutes", 10))
        for ev in jcalendar.upcoming_within(lead):
            key = ("soon", ev["title"], ev["start"].isoformat())
            if key not in self.announced:
                self.announced.add(key)
                mins = max(0, round((ev["start"].timestamp() - time.time()) / 60))
                msg = f"Heads up: {ev['title']} starts in {mins} minutes."
                last = self.mem.last_summary(ev["title"])
                if last:
                    msg += f" Last time: {last[:240]}"
                self.say(msg)
        if self.flags.get("notes") and self.notes:
            for ev in jcalendar.starting_now():
                key = ("start", ev["title"], ev["start"].isoformat())
                if key not in self.announced:
                    self.announced.add(key)
                    self.notes.offer(ev["title"])
                    self.say(f"{ev['title']} is starting. Want me to take notes?")
                    if self.on_offer:
                        self.on_offer()

    def daily_brief(self):
        if not (self.brief_fn and self.cfg.get("briefing_enabled", True)):
            return
        now = dt.datetime.now()
        hh, mm = map(int, self.cfg.get("briefing_time", "08:30").split(":"))
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        today = now.date().isoformat()
        # deliver at the set time, or at launch if started within 3 hours after it
        if due <= now <= due + dt.timedelta(hours=3) and self.mem.get_fact("last_brief_date") != today:
            self.mem.remember("last_brief_date", today)
            self.say(self.brief_fn())
