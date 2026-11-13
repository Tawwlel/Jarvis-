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
import re
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
        import time as _t
        kw = {"tools": tools} if tools else {}
        t0 = _t.time()
        resp = self.client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                           messages=self.convert(messages), **kw)
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [{"id": b.id, "name": b.name, "input": b.input}
                 for b in resp.content if b.type == "tool_use"]
        _count(model, resp)
        u = getattr(resp, "usage", None)
        print(f"[timing] llm {_t.time() - t0:.1f}s {model} in={getattr(u, 'input_tokens', '?')} out={getattr(u, 'output_tokens', '?')}")
        if getattr(resp, "stop_reason", "") == "max_tokens" and not calls:
            text = text.rstrip() + "\n...(there is more: ask me to continue)"  # never end an answer mid-sentence silently
        return LLMResult(text, calls)


def _count(model, resp):
    """Feed the usage meter (never let counting break an answer)."""
    try:
        import usage
        u = resp.usage
        usage.record(model, int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0),
                     int(getattr(u, "cache_read_input_tokens", 0) or 0))
    except Exception as e:
        print("[usage]", e)


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

    def __init__(self, model: str | None, host: str = "http://localhost:11434", keep_alive: str = "30m"):
        self.model, self.host, self.keep_alive = model, host, keep_alive

    def available(self) -> bool:
        """True when Ollama is running AND this model has been downloaded."""
        if not self.model:
            return False
        try:
            import requests

            names = {m.get("name", "") for m in requests.get(self.host + "/api/tags", timeout=1.5).json().get("models", [])}
            want = self.model if ":" in self.model else self.model + ":latest"
            return want in names or self.model in names
        except Exception:
            return False

    def warm_up(self):
        """Loads the model into memory now so the first answer is quick."""
        if not self.model:
            return
        try:
            import requests

            requests.post(self.host + "/api/generate", timeout=120,
                          json={"model": self.model, "keep_alive": self.keep_alive})
        except Exception:
            pass

    def chat(self, system: str, messages: list, max_tokens=400) -> str | None:
        try:
            import requests

            msgs = [{"role": "system", "content": system}] + [
                {"role": m["role"], "content": m.get("content") or m.get("text", "")}
                for m in messages if m["role"] in ("user", "assistant")]
            r = requests.post(self.host + "/api/chat", timeout=120, json={
                "model": self.model, "messages": msgs, "stream": False, "keep_alive": self.keep_alive,
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

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", language: str | None = None):
        self.api_key, self.base_url, self.language = api_key, base_url.rstrip("/"), language
        self.hint = None  # words Jarvis expects to hear (document types, the owner's customer names)

    def transcribe_array(self, audio, prompt: str | None = None) -> str:
        import requests
        import audio as _audio
        from pathlib import Path

        audio = _audio.clean_audio(audio)
        _audio.save_debug_clip(audio, Path(__file__).parent.parent / "data" / "last_voice.wav")
        base = "Jarvis, WhatsApp, sync, email, invoice, document, Urdu and English."
        text_prompt = (prompt or "") + " " + base + " " + (self.hint or "")

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio.tobytes())
        wavbytes = buf.getvalue()

        def call(lang):
            r = requests.post(f"{self.base_url}/audio/transcriptions", timeout=60,
                              headers={"Authorization": f"Bearer {self.api_key}"},
                              files={"file": ("speech.wav", wavbytes, "audio/wav")},
                              data={"model": "whisper-1", "temperature": "0", "response_format": "verbose_json",
                                    "prompt": text_prompt.strip()[:800], **({"language": lang} if lang else {})})
            r.raise_for_status()
            j = r.json()
            return (j.get("text") or "").strip(), str(j.get("language") or "").lower()

        text, detected = call(self.language)
        if self.language is None:
            # Pakistani Urdu is often labelled Hindi/Punjabi/etc. Only English and Urdu are supported here:
            # anything that is not English is written again as Urdu (never Hindi/Devanagari).
            if detected not in ("english", "en", "") or re.search(r"[\u0900-\u097F]", text):
                again, _ = call("ur")
                if again:
                    text = again
        return text


def make_stt(cfg: dict, secrets):
    slot = cfg.get("slots", {}).get("stt", {})
    mode = cfg.get("language", "auto")
    lang = None if mode == "auto" else mode
    if slot.get("provider") == "openai_whisper":
        return OpenAIWhisper(secrets.get("openai") or "", language=lang)
    from stt import JarvisEars

    model = slot.get("model", "base.en")
    if mode == "en":
        return JarvisEars(model if model.endswith(".en") else "small.en", language="en")
    urdu = model if not model.endswith(".en") and model not in ("tiny", "base") else "medium"
    if mode == "ur":
        return JarvisEars(urdu, language="ur")
    # auto: the fast "base" model only spots the language; English is written by small.en (much more accurate
    # than base), Urdu by the bigger model
    return JarvisEars("base", language=None, urdu_model=urdu, english_model="small.en")


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


class EdgeVoice:
    """Urdu (and other) neural voices through Microsoft Edge's free text-to-speech. Needs internet."""
    name = "edge"

    def __init__(self, voice: str = "ur-PK-AsadNeural"):
        self.voice = voice

    def speak(self, text, voice_name=None, out_path=None, play=False) -> str:
        import asyncio

        import edge_tts
        import miniaudio
        from tts import AUDIO_DIR

        async def run():
            data = b""
            async for chunk in edge_tts.Communicate(text, voice_name or self.voice).stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            return data

        mp3 = asyncio.run(run())
        if not mp3:
            raise RuntimeError("no audio from the Urdu voice")
        pcm = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
        path = out_path or str(AUDIO_DIR / "out_urdu.wav")
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm.samples.tobytes())
        return path


class BilingualVoice:
    """Speaks Urdu text with the Urdu voice and everything else with the chosen English voice."""

    def __init__(self, base, urdu_voice: str, urdu_fallback=None):
        self.base, self.urdu, self.fallback = base, EdgeVoice(urdu_voice), urdu_fallback

    def speak(self, text, voice_name="amy", out_path=None, play=False) -> str:
        from lang import is_urdu

        if is_urdu(text):
            try:
                return self.urdu.speak(text, out_path=out_path)
            except Exception as e:
                print("[urdu voice]", e)
                if self.fallback:
                    return self.fallback.speak(text, out_path=out_path)
                raise
        return self.base.speak(text, voice_name=voice_name, out_path=out_path, play=play)


def make_tts(cfg: dict, secrets):
    slot = cfg.get("slots", {}).get("tts", {})
    eleven = None
    if secrets.get("elevenlabs") and slot.get("elevenlabs_voice_id"):
        eleven = ElevenLabsVoice(secrets.get("elevenlabs"), slot["elevenlabs_voice_id"])
    if slot.get("provider") == "elevenlabs" and eleven:
        base = eleven  # ElevenLabs multilingual handles Urdu too
        return base
    from tts import JarvisVoice

    base = JarvisVoice()
    if cfg.get("language", "auto") == "en":
        return base
    return BilingualVoice(base, slot.get("urdu_voice") or "ur-PK-AsadNeural", urdu_fallback=eleven)
