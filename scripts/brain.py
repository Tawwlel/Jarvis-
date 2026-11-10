"""
Tiered brain.

Tier 0  local (Ollama, free)  -> greetings, trivial chat, and ROUTING
Tier 1  Haiku                 -> everyday work, tools
Tier 2  Sonnet                -> hard / multi-step reasoning

Flow: cheap rules first -> local model classifies -> escalate only if needed.
"""
import json
import re
import urllib.request

import tools
from memory import Memory

SYSTEM = (
    "You are Jarvis, a concise, capable personal assistant speaking aloud. "
    "Keep replies short (1-3 sentences) unless asked for detail. "
    "Use tools when they help. Owner: {owner}.\nKnown facts:\n{facts}"
)

# Cheap pre-filter: no model call at all.
HARD_HINTS = re.compile(
    r"\b(analy[sz]e|plan|compare|research|debug|write (a|the) (report|code|email)|"
    r"step by step|on my (screen|computer)|click|open the|automate)\b", re.I)
TRIVIAL = re.compile(r"^(hi|hello|hey|thanks|thank you|ok|okay|bye|good (morning|night))\b", re.I)


class Brain:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mem = Memory()
        tools.CTX["memory"] = self.mem
        self.tools = tools.enabled_tools(cfg)
        self.models = cfg["models"]
        self._client = None

    # ---------- clients ----------
    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.cfg["anthropic_api_key"])
        return self._client

    def _local(self, prompt: str, system: str = "") -> str | None:
        """Call Ollama if it's running; None if unavailable (we then fall back to Haiku)."""
        model = self.models.get("tier0_local")
        if not model:
            return None
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=json.dumps({"model": model, "prompt": prompt, "system": system,
                                 "stream": False}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())["response"].strip()
        except Exception:
            return None

    # ---------- routing ----------
    def route(self, text: str) -> str:
        if TRIVIAL.match(text.strip()) and len(text) < 40:
            return "local"
        if HARD_HINTS.search(text):
            return "sonnet" if re.search(r"screen|computer|click|automate|analy|research|debug", text, re.I) else "haiku"
        verdict = self._local(
            "Classify the request. Reply with ONE word: SIMPLE (greeting/chitchat), "
            "NORMAL (needs tools, facts, or short help), HARD (multi-step reasoning, "
            f"planning, analysis).\nRequest: {text}")
        if verdict:
            v = verdict.upper()
            if "SIMPLE" in v: return "local"
            if "HARD" in v: return "sonnet"
        return "haiku"

    # ---------- main entry ----------
    def respond(self, text: str) -> str:
        self.mem.add_message("user", text)
        system = SYSTEM.format(owner=self.cfg.get("owner_name", "the user"),
                               facts=self.mem.facts_text() or "(none yet)")
        tier = self.route(text)
        reply = None
        if tier == "local":
            reply = self._local(text, system)
        if reply is None:
            model = self.models["tier2_cloud"] if tier == "sonnet" else self.models["tier1_cloud"]
            reply = self._cloud(model, system)
        self.mem.add_message("assistant", reply)
        return reply

    def _cloud(self, model: str, system: str) -> str:
        messages = self.mem.recent(8)
        while messages and messages[0]["role"] != "user":
            messages.pop(0)  # API requires the first message to be from the user
        schemas = [t["schema"] for t in self.tools]
        for _ in range(6):  # tool loop cap keeps cost bounded
            resp = self.client.messages.create(
                model=model, max_tokens=500, system=system,
                messages=messages, tools=schemas)
            if resp.stop_reason != "tool_use":
                return "".join(b.text for b in resp.content if b.type == "text").strip()
            messages.append({"role": "assistant", "content": resp.content})
            results = [{"type": "tool_result", "tool_use_id": b.id,
                        "content": tools.run_tool(b.name, b.input)}
                       for b in resp.content if b.type == "tool_use"]
            messages.append({"role": "user", "content": results})
        return "I got stuck in a loop on that one."
