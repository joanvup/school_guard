import io
import math


def read_excel(data: bytes):
    import pandas as pd

    return pd.read_excel(io.BytesIO(data), dtype=str)


def clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def normalize_excel_id(value) -> str | None:
    text = clean_text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text or "." in text or len(text) > 20:
        return None
    if "/" in text or "\\" in text:
        return None
    return text


def normalize_rfid(value) -> str | None:
    text = clean_text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text or len(text) > 50:
        return None
    return text
