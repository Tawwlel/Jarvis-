"""
Swappable slots. Each slot (speech-to-text, language model, text-to-speech) has a
small interface and several providers, chosen in Settings:

  llm  : anthropic | openai_compatible (OpenAI, OpenRouter, Groq, LM Studio...) | local Ollama
  stt  : local_whisper (free, private) | openai_whisper
  tts  : piper (free, private)         | elevenlabs

Messages use one neutral shape so the brain doesn't care which provider is active:
  {"role": "user", "content": str}
  {"role": "assistant", "text": str, "tool_calls": [{"id", "name", "input"}]}
  {"role": "tool", "results": [{"id", "text", "image_b64"?}]}
"""
import io
import json
import wave
from dataclasses import dataclass, field


@dataclass
class LLMResult:
    text: str = ""
    tool_calls: list = field(default_factory=list)


def _tool_content_anthropic(r: dict):
    if r.get("image_b64"):
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": r["image_b64"]}},
                {"type": "text", "text": r.get("text") or "Screenshot"}]
    return r.get("text", "")


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, api_key: str):
        self.api_key, self._client = api_key, None

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    @staticmethod
    def convert(messages: list) -> list:
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                blocks = ([{"type": "text", "text": m["text"]}] if m.get("text") else []) + [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["input"]}
                    for c in m.get("tool_calls", [])]
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": _tool_content_anthropic(r)}
                    for r in m["results"]]})
        return out

    def complete(self, model, system, messages, tools=None, max_tokens=500) -> LLMResult:
        kw = {"tools": tools} if tools else {}
        resp = self.client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                           messages=self.convert(messages), **kw)
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [{"id": b.id, "name": b.name, "input": b.input}
                 for b in resp.content if b.type == "tool_use"]
        return LLMResult(text, calls)


class OpenAICompatLLM:
    """Any service that speaks the OpenAI chat-completions format."""
    name = "openai_compatible"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key, self.base_url = api_key, base_url.rstrip("/")

    @staticmethod
    def convert(system: str, messages: list) -> list:
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                msg = {"role": "assistant", "content": m.get("text") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                          "function": {"name": c["name"], "arguments": json.dumps(c["input"])}}
                                         for c in m["tool_calls"]]
                out.append(msg)
            else:
                images = []
                for r in m["results"]:
                    out.append({"role": "tool", "tool_call_id": r["id"], "content": r.get("text") or ""})
                    if r.get("image_b64"):
                        images.append({"type": "image_url",
                                       "image_url": {"url": "data:image/jpeg;base64," + r["image_b64"]}})
                if images:  # this format can't put images inside tool results
                    out.append({"role": "user", "content": [{"type": "text", "text": "Screenshot:"}] + images})
        return out

    def complete(self, model, system, messages, tools=None, max_tokens=500) -> LLMResult:
        import requests

        body = {"model": model, "max_tokens": max_tokens, "messages": self.convert(system, messages)}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
                for t in tools]
        r = requests.post(f"{self.base_url}/chat/completions", json=body, timeout=90,
                          headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        calls = [{"id": c["id"], "name": c["function"]["name"],
                  "input": json.loads(c["function"].get("arguments") or "{}")}
                 for c in msg.get("tool_calls") or []]
        return LLMResult(msg.get("content") or "", calls)


class LocalLLM:
    """Ollama on this PC. Free and private; small models, so no tool use."""
    name = "local"

    def __init__(self, model: str | None, host: str = "http://localhost:11434"):
        self.model, self.host = model, host

    def available(self) -> bool:
        if not self.model:
            return False
        try:
            import requests

            return requests.get(self.host + "/api/tags", timeout=1.5).ok
        except Exception:
            return False

    def chat(self, system: str, messages: list, max_tokens=400) -> str | None:
        try:
            import requests

            msgs = [{"role": "system", "content": system}] + [
                {"role": m["role"], "content": m.get("content") or m.get("text", "")}
                for m in messages if m["role"] in ("user", "assistant")]
            r = requests.post(self.host + "/api/chat", timeout=60, json={
                "model": self.model, "messages": msgs, "stream": False,
                "options": {"num_predict": max_tokens}})
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
        except Exception:
            return None


def make_llm(cfg: dict, secrets):
    slot = cfg.get("slots", {}).get("llm", {})
    provider = slot.get("provider", "anthropic")
    if provider == "openai_compatible":
        return OpenAICompatLLM(secrets.get("openai") or "", slot.get("base_url") or "https://api.openai.com/v1")
    return AnthropicLLM(secrets.get("anthropic") or "")


# ---------------- speech to text ----------------
class OpenAIWhisper:
    name = "openai_whisper"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key, self.base_url = api_key, base_url.rstrip("/")

    def transcribe_array(self, audio) -> str:
        import requests

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio.tobytes())
        r = requests.post(f"{self.base_url}/audio/transcriptions", timeout=60,
                          headers={"Authorization": f"Bearer {self.api_key}"},
                          files={"file": ("speech.wav", buf.getvalue(), "audio/wav")},
                          data={"model": "whisper-1"})
        r.raise_for_status()
        return r.json().get("text", "").strip()


def make_stt(cfg: dict, secrets):
    slot = cfg.get("slots", {}).get("stt", {})
    if slot.get("provider") == "openai_whisper":
        return OpenAIWhisper(secrets.get("openai") or "")
    from stt import JarvisEars

    return JarvisEars(slot.get("model", "base.en"))


# ---------------- text to speech ----------------
class ElevenLabsVoice:
    name = "elevenlabs"

    def __init__(self, api_key: str, voice_id: str):
        self.api_key, self.voice_id = api_key, voice_id

    def speak(self, text, voice_name=None, out_path=None, play=False) -> str:
        import requests
        from tts import AUDIO_DIR

        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}?output_format=pcm_22050",
            headers={"xi-api-key": self.api_key}, timeout=60,
            json={"text": text, "model_id": "eleven_multilingual_v2"})
        r.raise_for_status()
        path = out_path or str(AUDIO_DIR / "out_elevenlabs.wav")
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(r.content)
        return path


def make_tts(cfg: dict, secrets):
    slot = cfg.get("slots", {}).get("tts", {})
    if slot.get("provider") == "elevenlabs" and secrets.get("elevenlabs") and slot.get("elevenlabs_voice_id"):
        return ElevenLabsVoice(secrets.get("elevenlabs"), slot["elevenlabs_voice_id"])
    from tts import JarvisVoice

    return JarvisVoice()
