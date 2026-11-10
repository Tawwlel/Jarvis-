"""
Privacy router helpers.

Redactor: replaces sensitive details with placeholders like [EMAIL_1] BEFORE text
goes to an online model, and puts the real values back into the reply and into
tool calls, so the user never notices - the online model just never sees them.

Detected: emails, card numbers (Luhn-checked), national ID numbers (Pakistani CNIC
format), IBANs, phone numbers, API keys / tokens, "password is ..." style secrets, and
any private terms the user lists (client names, project code names...).
This is pattern based: it catches the common formats, not every possible secret.
"""
import re

_PASSWORDS = [
    re.compile(r"(?i)\b(password|passcode|passphrase|pin|otp|secret|token)\b(\s*(?:is|:|=)\s*)(\S+)"),
    re.compile(r"(?i)\b(pin|otp)\b(\s+)(\d{4,8})\b"),
]
PATTERNS = [
    ("KEY", re.compile(r"\b(?:sk-ant-[\w-]{10,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}"
                       r"|xox[abp]-[\w-]{10,}|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})\b")),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("ID", re.compile(r"\b\d{5}-?\d{7}-?\d\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("PHONE", re.compile(r"(?<![\w\[])\+?\d[\d\s().-]{7,}\d(?![\w\]])")),
]


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


class Redactor:
    def __init__(self, private_terms=None, enabled: bool = True):
        self.enabled = enabled
        self.terms = [t.strip() for t in (private_terms or []) if t.strip()]
        self.map: dict[str, str] = {}      # placeholder -> original
        self._rev: dict[str, str] = {}     # original -> placeholder
        self._count: dict[str, int] = {}

    def _ph(self, tag: str, original: str) -> str:
        if original in self._rev:
            return self._rev[original]
        self._count[tag] = self._count.get(tag, 0) + 1
        ph = f"[{tag}_{self._count[tag]}]"
        self.map[ph], self._rev[original] = original, ph
        return ph

    def redact(self, text: str) -> str:
        if not self.enabled or not isinstance(text, str) or not text:
            return text
        for term in self.terms:
            text = re.sub(re.escape(term), lambda m: self._ph("TERM", m.group(0)), text, flags=re.I)
        for rx in _PASSWORDS:
            text = rx.sub(lambda m: f"{m.group(1)}{m.group(2)}{self._ph('SECRET', m.group(3))}", text)
        for tag, rx in PATTERNS:
            def sub(m, tag=tag):
                s = m.group(0)
                digits = re.sub(r"\D", "", s)
                if tag == "CARD" and not (13 <= len(digits) <= 19 and luhn_ok(digits)):
                    return s
                if tag == "PHONE" and len(digits) < 9:
                    return s
                return self._ph(tag, s)
            text = rx.sub(sub, text)
        return text

    def categories(self, text: str) -> list[str]:
        """What kinds of sensitive details a text contains (does not keep the mapping)."""
        probe = Redactor(self.terms, True)
        probe.redact(text)
        return sorted({re.match(r"\[([A-Z]+)_", p).group(1) for p in probe.map})

    def restore(self, text: str) -> str:
        if not self.map or not isinstance(text, str):
            return text
        for ph, original in self.map.items():
            text = text.replace(ph, original)
        return text

    def restore_obj(self, obj):
        if isinstance(obj, str):
            return self.restore(obj)
        if isinstance(obj, list):
            return [self.restore_obj(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.restore_obj(v) for k, v in obj.items()}
        return obj

    def redact_obj(self, obj):
        if isinstance(obj, str):
            return self.redact(obj)
        if isinstance(obj, list):
            return [self.redact_obj(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.redact_obj(v) for k, v in obj.items()}
        return obj
