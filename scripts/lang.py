"""Language helpers: Urdu/English detection and the instruction given to the model."""
import re

ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
LETTER = re.compile(r"[^\W\d_]", re.U)


def is_urdu(text: str) -> bool:
    letters = LETTER.findall(text)
    return bool(letters) and len(ARABIC.findall(text)) / len(letters) > 0.3


def instruction(mode: str) -> str:
    if mode == "ur":
        return ("\nLanguage: always reply in Urdu (Urdu script), in short natural spoken sentences. "
                "Keep names, numbers and file names as they are. Tool inputs stay in English.")
    if mode == "en":
        return "\nLanguage: always reply in English."
    return ("\nLanguage: reply in the language the user spoke: Urdu (Urdu script) or English. "
            "If they mix, follow the main language. Keep names and numbers as they are. "
            "Tool inputs stay in English letters.")
