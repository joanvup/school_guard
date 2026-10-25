import math

from app.utils.data import clean_text, normalize_excel_id, normalize_rfid


def test_excel_ids_strip_numeric_suffix():
    assert normalize_excel_id(2023001.0) == "2023001"
    assert normalize_excel_id("2023002.0") == "2023002"
    assert normalize_excel_id(" 2023003 ") == "2023003"


def test_invalid_ids_are_rejected():
    assert normalize_excel_id("12.345") is None
    assert normalize_excel_id("../../etc/passwd") is None
    assert normalize_excel_id(None) is None
    assert normalize_excel_id(math.nan) is None
    assert normalize_excel_id("") is None


def test_rfid_empty_and_numeric_values():
    assert normalize_rfid("123.0") == "123"
    assert normalize_rfid("  ABC  ") == "ABC"
    assert normalize_rfid(None) is None
    assert normalize_rfid(math.nan) is None
    assert normalize_rfid("") is None


def test_clean_text_normalizes_excel_nan():
    assert clean_text(math.nan) == ""
    assert clean_text("  texto  ") == "texto"
    assert clean_text(None) == ""
