"""
Tiered brain with a privacy router.

Tier 0  local Ollama (free, private)  -> greetings, routing, and anything sensitive
Tier 1  fast online model (Haiku)     -> everyday work, tools
Tier 2  strong online model (Sonnet)  -> hard / multi-step reasoning, computer control

Privacy modes (Settings > Privacy):
  balanced  details like emails, cards, IDs, phone numbers, keys and passwords are replaced
            by placeholders before anything goes online, and restored in the reply.
            Topics the user lists as "keep on this PC" never leave the computer.
  strict    anything sensitive stays on this PC (local model), nothing is sent online.
  off       no filtering.
If a request must stay local but no local model is running, Jarvis says so instead of sending it.
"""
import re
import time

import tools
from memory import Memory
from privacy import Redactor
from providers import LocalLLM, make_llm
from secrets_store import default_store

SYSTEM = (
    "You are {assistant}, a concise, capable personal assistant from Apricot Digital, "
    "speaking aloud (the user may also call you {aliases}). "
    "Keep replies short (1-3 sentences) unless asked for detail. Plain text only: no markdown, no ** or #. "
    "Use tools when they help. Owner: {owner}.\n"
    "Honesty rules: never invent names, chats, files, amounts, dates or results. State only what the user said or what "
    "a tool returned. If a tool finds nothing, say so plainly and do not list unrelated 'closest' items as if they "
    "were answers unless the user asks. Only pass a tool argument (a chat name, file name, amount) that the user "
    "actually said. The user's words come from speech recognition and can be garbled: if the request is unclear, "
    "looks like random words, or you are not sure what was asked, ask them to repeat instead of guessing or acting. "
    "Never claim an action is done unless a tool confirmed it.\nKnown facts:\n{facts}"
)

COMPUTER_RULES = (
    "\nComputer control rules: take a screenshot before clicking and after each important "
    "step. Never enter passwords, card or bank details, or personal IDs - stop and ask the "
    "user to do that part. Do not buy, send, post, delete or accept terms unless the user "
    "clearly asked for exactly that. If you hit a captcha or something unexpected, stop and "
    "tell the user. Prefer the fewest steps."
)

BLOCKED = ("That looks private, so I kept it on this computer, but no local model is running. "
           "Install Ollama and pick a local model in Settings, or change the privacy mode.")
NO_KEY = "I can't reach my language model yet. Add your API key in Settings, under Keys and models."

# Cheap pre-filter: no model call at all.
HARD_HINTS = re.compile(
    r"\b(analy[sz]e|plan|compare|research|debug|write (a|the) (report|code|email)|"
    r"step by step|on my (screen|computer)|click|open the|automate)\b", re.I)
# Requests that need tools (files, documents, reminders, calendar, the computer). Small local models
# can't use tools and would make answers up, so these always need the online model.
ACTION = re.compile(
    r"\b(find|search|look ?up|list|open|show me|get me|send|delete|remove|move|copy|rename|collect|remind|"
    r"schedule|book|add (a |an )?(task|todo|to-do|event|meeting|note)|go (to|through|into)|take notes|"
    r"what'?s on my|do i have|e-?mails?|inbox|digest|mails?|"
    # document words on their own, and Roman-Urdu commands ("invoices dikhao", "WhatsApp se quotation nikalo")
    r"invoices?|quotations?|quotes?|receipts?|challans?|bills?|agreements?|contracts?|documents?|files?|folders?|"
    r"whatsapp|iphone|backup|sync|link|import|total|kul|kitn[aie]|dikha[oe]?|dikhao|nikal[oe]?|dh?oond[oh]?|dhund[oh]?|"
    r"talash|khol[oe]?|bhej[oe]?|jama|raseed|parchi|yaad dila)\b|"
    r"\bmy (files?|folders?|documents?|docs|invoices?|quotations?|quotes|receipts?|pdfs?|photos?|calendar|"
    r"meetings?|reminders?|tasks|todos?|notes|emails?|whatsapp|computer|laptop|screen|desktop|downloads)\b|"
    r"ای میل|میل|فائل|انوائس|کوٹیشن|رسید|یاد دہانی|میٹنگ|کھولو|ڈھونڈ|دکھاؤ|تلاش", re.I)
LOCAL_RULES = ("\nYou are running offline on this PC with NO access to files, folders, documents, the internet, "
               "calendar, reminders or the computer. Never pretend to look anything up or list files. If asked for "
               "that, say you need the online model (an API key in Settings) for it. Keep answers to 1-3 sentences.")
NEEDS_ONLINE = ("I need my online model for that, because it means using your files or apps. Add your API key in "
                "Settings, under Keys and models. Offline I can only chat and answer simple questions.")
TRIVIAL = re.compile(r"^(hi|hello|hey|thanks|thank you|ok|okay|bye|good (morning|night))\b", re.I)


def _llm_error_message(e) -> str:
    """Say what actually went wrong instead of one vague line (a wrong key, no credit and no internet need different fixes).
    Customers never hear about keys or credit: a key/credit problem is a plan to renew."""
    t = f"{type(e).__name__} {e}".lower()
    code = getattr(e, "status_code", None)
    try:
        import plan
        if plan.customer_mode() and (code in (401, 403) or any(w in t for w in (
                "credential", "authentication", "invalid x-api-key", "permission", "credit balance", "billing",
                "spend limit", "usage limit", "api key", "api_key"))):
            return plan.BILL
    except Exception:
        pass
    if code in (401, 403) or "credential" in t or "authentication" in t or "invalid x-api-key" in t or "permission" in t:
        return "My language model key was refused. Check the Anthropic key in Settings, under Keys and models."
    if "credit balance" in t or "billing" in t or "spend limit" in t or "usage limit" in t:
        return ("The Anthropic account has no credit left or hit its spend limit. Add credit or raise the limit "
                "at console.anthropic.com, then ask me again.")
    if code == 429 or "rate" in t and "limit" in t:
        return "The language model is busy right now (rate limit). Please ask again in a few seconds."
    if code in (500, 502, 503, 529) or "overloaded" in t:
        return "The language model service is overloaded for a moment. Please ask again in a few seconds."
    if "connection" in t or "timeout" in t or "timed out" in t or "name resolution" in t or "ssl" in t:
        return "I couldn't reach the internet. Check the connection and ask me again."
    if code == 404 or "not_found" in t or "model" in t and "not" in t:
        return "The language model name in Settings is not valid. Check Fast model and Strong model under Keys and models."
    return "I couldn't get an answer from the language model. Ask me again; if it keeps happening, check the key and internet."


class Brain:
    def __init__(self, cfg: dict, secrets=None):
        self.cfg = cfg
        self.secrets = secrets or default_store()
        self.mem = Memory()
        tools.CTX["memory"] = self.mem
        self.tools = tools.enabled_tools(cfg)
        self.models = cfg["models"]
        self.local = LocalLLM(self.models.get("tier0_local"))  # light: quick, simple answers
        self.local_heavy = LocalLLM(None)  # no heavy model: one small model keeps memory use low
        self._llm = None
        self.deny = set()
        self._last_agent = None  # (name, time): lets a short follow-up stay with the same agent
        self._local_ok = (0.0, False)
        self._heavy_ok = (0.0, False)

    # ---------- basics ----------
    @property
    def assistant_name(self) -> str:
        return (self.cfg.get("assistant_names") or ["Jarvis"])[0]

    @property
    def llm(self):
        if self._llm is None:
            self._llm = make_llm(self.cfg, self.secrets)
        return self._llm

    def llm_ready(self) -> bool:
        provider = self.cfg.get("slots", {}).get("llm", {}).get("provider", "anthropic")
        key = "openai" if provider == "openai_compatible" else "anthropic"
        return bool(self.secrets.get(key)) or hasattr(self._llm, "_fake")

    def _light_ok(self) -> bool:
        t, ok = self._local_ok
        if time.time() - t > 60:
            ok = self.local.available()
            self._local_ok = (time.time(), ok)
        return ok

    def heavy_ok(self) -> bool:
        t, ok = self._heavy_ok
        if time.time() - t > 60:
            ok = self.local_heavy.available()
            self._heavy_ok = (time.time(), ok)
        return ok

    def local_ok(self) -> bool:
        return self._light_ok() or self.heavy_ok()

    def local_answer(self, system: str, heavy: bool = False, max_tokens: int = 160) -> str | None:
        """Answer on this PC. heavy=True prefers the bigger model; falls back to whichever exists."""
        order = [(self.local_heavy, self.heavy_ok), (self.local, self._light_ok)]
        if not heavy:
            order.reverse()
        for model, ok in order:
            if ok():
                reply = model.chat(system + LOCAL_RULES, self._history(), max_tokens=max_tokens)
                if reply:
                    return reply
        return None

    def _history(self) -> list:
        msgs = []
        for m in self.mem.recent(8):
            if m["role"] == "user":
                msgs.append({"role": "user", "content": m["content"]})
            elif m["content"]:
                msgs.append({"role": "assistant", "text": m["content"]})
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)  # APIs need the first message to be from the user
        return msgs

    # ---------- privacy ----------
    @property
    def _privacy(self) -> dict:
        return self.cfg.get("privacy", {})

    def _redactor(self) -> Redactor:
        p = self._privacy
        return Redactor(p.get("private_terms", []), enabled=p.get("mode", "balanced") != "off")

    def _policy(self, corpus: str, red: Redactor) -> str:
        """'cloud' (after redaction), 'local', or 'blocked' (must stay local, none available)."""
        p = self._privacy
        mode = p.get("mode", "balanced")
        if mode == "off":
            return "cloud"
        low = corpus.lower()
        term_hit = any(t.strip().lower() in low for t in p.get("local_only_terms", []) if t.strip())
        if term_hit or (mode == "strict" and red.categories(corpus)):
            return "local" if self.local_ok() else "blocked"
        return "cloud"

    # ---------- routing ----------
    def route(self, text: str) -> str:
        if self.llm_ready():  # the online model answers in seconds; the small local model took 30-120 s on laptops
            if HARD_HINTS.search(text) and re.search(
                    r"screen|computer|click|automate|open|browser|window|analy|research|debug", text, re.I):
                return "sonnet"
            return "haiku"
        if TRIVIAL.match(text.strip()) and len(text) < 40:
            return "local"
        if HARD_HINTS.search(text):
            return "sonnet" if re.search(
                r"screen|computer|click|automate|open|browser|window|analy|research|debug", text, re.I) else "haiku"
        # short small talk goes to the free local model; no extra model call to decide (that was slow)
        if self.local_ok() and len(text.split()) <= 6 and not ACTION.search(text):
            return "local"
        return "haiku"

    # ---------- instant answers (free, no model) ----------
    def _quick(self, text: str) -> str | None:
        import datetime as dt
        t = text.lower()
        if len(t) > 80:
            return None
        now = dt.datetime.now()
        if re.fullmatch(r"(hi|hello|hey|salam|assalam o alaikum|assalamualaikum|good (morning|evening))\W*"
                        r"( jarvis)?\W*", t.strip()):
            return f"Hello {self.cfg.get('owner_name') or ''}! How can I help?".replace("Hello !", "Hello!")
        if re.search(r"\bwhat(?:'s| is)? (?:the )?time\b|\btime (?:is it|right now)\b|وقت کیا|کتنے بجے", t):
            return now.strftime("It's %I:%M %p.").replace(" 0", " ")
        if re.search(r"\bwhat(?:'s| is)? (?:the |today'?s )?date\b|\bwhat day is (?:it|today)\b|آج کیا تاریخ|آج کون سا دن", t):
            return now.strftime("Today is %A, %d %B %Y.")
        return None

    # ---------- main entry ----------
    def respond(self, text: str, phone: bool = False) -> str:
        """phone=True: the question came from the owner's phone - read-only tools only (see phone_bridge.PHONE_DENY)."""
        self.deny = set(__import__("phone_bridge").PHONE_DENY) if phone else set()
        self.mem.add_message("user", text)
        tools.CTX["last_user_text"] = text  # tools can check what the owner actually said this time
        quick = self._quick(text)
        if quick:
            self.mem.add_message("assistant", quick)
            return quick
        if self.cfg.get("tools_enabled", {}).get("computer_control"):
            import computer
            computer.reset()  # each request needs fresh approval
        system = SYSTEM.format(owner=self.cfg.get("owner_name", "the user"),
                               assistant=self.assistant_name,
                               aliases=", ".join(self.cfg.get("assistant_names", ["Jarvis"])),
                               facts=self.mem.facts_text() or "(none yet)")
        from lang import instruction
        system += instruction(self.cfg.get("language", "auto"))
        try:
            from lang import tone_rule
            t = tone_rule(self.cfg)
            if t:
                system += "\n" + t
        except Exception:
            pass
        if any(t["schema"]["name"].startswith("computer_") for t in self.tools):
            system += COMPUTER_RULES
        red = self._redactor()
        policy = self._policy(text, red)
        reply = None
        if policy == "blocked":
            reply = BLOCKED
        elif policy == "local":
            reply = self.local_answer(system, heavy=True) or BLOCKED
        else:
            tier = self.route(text)
            if tier == "local" and self.local_ok():
                reply = self.local_answer(system, heavy=False)
            if reply is None:
                if not self.llm_ready():
                    # no online key: let the local model answer what it can (no tools)
                    import plan
                    if ACTION.search(text):
                        reply = plan.NOT_READY if plan.customer_mode() else NEEDS_ONLINE
                    else:  # light model by default (fast); heavy only for clearly harder questions
                        reply = self.local_answer(system, heavy=bool(HARD_HINTS.search(text))) or (
                            plan.NOT_READY if plan.customer_mode() else NO_KEY)
                elif __import__("usage").blocked() and not re.search(r"budget|usage|limit", text, re.I):
                    lic = __import__("licence")
                    import plan
                    reply = (lic.message() + " I can still find your files." if lic.blocked() else
                             plan.BILL if plan.customer_mode() else
                             "This month's usage is at 100 out of 100, so I can't think online right now. Contact Apricot Digital "
                             "for a top-up code. I can still find your files.")
                else:
                    model = self.models["tier2_cloud"] if tier == "sonnet" else self.models["tier1_cloud"]
                    import agents
                    agent = agents.pick(text, self._last_agent)
                    if agent == "operator" or (tier == "sonnet" and agents.tools_for("operator", self.tools)
                                               and agent in ("jarvis", "finder")):
                        agent = "operator"
                    try:
                        reply = self._cloud(model, system, red, agent)
                    except Exception as e:
                        print("[llm]", repr(e)[:400])
                        reply = _llm_error_message(e)
        self.mem.add_message("assistant", reply)
        return reply

    # ---------- one-shot helper (summaries, briefs) with the same privacy rules ----------
    def ask(self, system: str, user: str, max_tokens: int = 400) -> str:
        red = self._redactor()
        policy = self._policy(user, red)
        if policy == "blocked":
            return BLOCKED
        msg = [{"role": "user", "content": user}]
        local = self.local_heavy if self.heavy_ok() else self.local
        if policy == "local":
            return (local.chat(system, msg, max_tokens) if self.local_ok() else None) or BLOCKED
        if not self.llm_ready():
            return (local.chat(system, msg, max_tokens) if self.local_ok() else None) or NO_KEY
        res = self.llm.complete(self.models["tier1_cloud"], red.redact(system),
                                [{"role": "user", "content": red.redact(user)}], None, max_tokens)
        return red.restore(res.text).strip()

    def summarize_notes(self, key: str) -> str:
        """One cheap call turns raw meeting notes into a short spoken summary."""
        raw = self.mem.notes_text(key)[:30000]
        if not raw:
            return "I don't have any notes for that meeting."
        summary = self.ask(
            "Summarize these raw meeting notes for the user. Plain sentences, no markdown or bullet "
            "symbols, because this is read aloud. Cover: the main points, any decisions, and action "
            "items with owners if mentioned. Under 120 words.", raw, 500)
        if summary not in (BLOCKED, NO_KEY):
            self.mem.add_note(key, summary, kind="summary")
        return summary

    # ---------- the tool loop ----------
    def _cloud(self, model: str, system: str, red: Redactor, agent: str = "jarvis") -> str:
        """One agent answers, with only its own tools. The coordinator may hand over once with ask_agent."""
        import agents
        messages = self._history()
        base = system
        # Computer control needs many steps; everything else stays tightly capped.
        max_steps = 30 if agent == "operator" else 7
        handed = False
        for _ in range(max_steps):
            mine = [t for t in agents.tools_for(agent, self.tools) if t["schema"]["name"] not in self.deny]
            if handed:  # an agent that received the work does it; it cannot pass it on again
                mine = [t for t in mine if t["schema"]["name"] != "ask_agent"]
            elif agent != "jarvis":  # the first agent may pass a misrouted request on, once
                mine = mine + [t for t in self.tools if t["schema"]["name"] == "ask_agent"]
            if agent == "operator" and self.deny:
                agent = "jarvis"  # a phone can never drive the mouse and keyboard
            schemas = [t["schema"] for t in mine] or None
            system = base + agents.prompt_for(agent, self.tools)
            self._last_agent = (agent, time.time())
            self._prune_images(messages)
            res = self.llm.complete(model, red.redact(system), self._redacted(messages, red), schemas, 1500)
            text = red.restore(res.text)
            if not res.tool_calls:
                print(f"[agent] {agent}")
                return text.strip()
            calls = [{"id": c["id"], "name": c["name"], "input": red.restore_obj(c["input"])}
                     for c in res.tool_calls]
            hand = next((c for c in calls if c["name"] == "ask_agent"), None)
            if hand:  # switch agent and let it start clean with the same conversation
                target = str(hand["input"].get("agent", "")).strip().lower()
                if not handed and target in agents.AGENTS and target != agent and agents.tools_for(target, self.tools):
                    agent, handed = target, True
                    continue
                handed = True
                calls = [c for c in calls if c["name"] != "ask_agent"]
                if not calls:
                    continue
            allowed = {t["schema"]["name"] for t in mine}
            calls = [c for c in calls if c["name"] in allowed]  # an agent can only use its own tools
            if not calls:
                continue
            messages.append({"role": "assistant", "text": text, "tool_calls": calls})
            results = []
            for c in calls:
                _t0 = time.time()
                r = tools.run_tool(c["name"], c["input"])
                print(f"[timing] tool {c['name']} {time.time() - _t0:.1f}s")
                if isinstance(r, dict):
                    results.append({"id": c["id"], "text": r.get("note", "Screenshot"), "image_b64": r["image_b64"]})
                else:
                    results.append({"id": c["id"], "text": r})
            messages.append({"role": "tool", "results": results})
        return "I ran out of steps on that one. Tell me if you want me to continue."

    @staticmethod
    def _redacted(messages: list, red: Redactor) -> list:
        """A copy of the conversation with sensitive details swapped for placeholders."""
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": red.redact(m["content"])})
            elif m["role"] == "assistant":
                out.append({"role": "assistant", "text": red.redact(m.get("text", "")),
                            "tool_calls": red.redact_obj(m.get("tool_calls", []))})
            else:
                out.append({"role": "tool", "results": [
                    {**r, "text": red.redact(r.get("text", ""))} for r in m["results"]]})
        return out

    @staticmethod
    def _prune_images(messages: list, keep: int = 2):
        """Old screenshots are the biggest token cost; keep only the newest few."""
        seen = 0
        for m in reversed(messages):
            if m["role"] != "tool":
                continue
            for r in m["results"]:
                if r.get("image_b64"):
                    seen += 1
                    if seen > keep:
                        r["image_b64"], r["text"] = None, "(older screenshot removed to save tokens)"
