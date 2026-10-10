import pytest

from jarvis.privacy import allowed, find_p3, redact_p3


@pytest.mark.parametrize("text,kind", [
    ("my key is sk-ant-api03-abcdefghijklmnop", "api_key"),
    ("token ghp_abcdefghijklmnopqrstuvwxyz123456", "github_token"),
    ("password: hunter22", "password"),
    ("wifi पासवर्ड आहे xyz123", "password"),
    ("your OTP is 482913", "otp"),
    ("card 4111 1111 1111 1111", "card_number"),
    ("PAN ABCDE1234F", "pan"),
    ("aadhaar 2345 6789 0123", "aadhaar"),
])
def test_p3_detected(text, kind):
    assert kind in find_p3(text)


@pytest.mark.parametrize("text", [
    "run pwd to see the folder",
    "my demo project runs with make run",
    "call me at 9 am, order 1234",
    "card 4111 1111 1111 1112",  # fails the Luhn check
    "मी उद्या पुण्याला जाणार आहे",
])
def test_normal_text_not_flagged(text):
    assert find_p3(text) == []


def test_redact():
    text, n = redact_p3("key sk-ant-abcdefghijk and card 4111111111111111 ok")
    assert n == 2 and "sk-ant" not in text and "4111" not in text and text.endswith("ok")


def test_allowed():
    assert allowed("P1", "P1") and allowed("P0", "P1")
    assert not allowed("P2", "P1")
    assert not allowed("P3", "P3")


def test_p3_in_devanagari_digits_is_found_and_redacted_in_place():
    from jarvis.privacy import find_p3, redact_p3

    text = "माझा आधार २३४५ ६७८९ ०१२३ आहे, बिल ८४० रुपये"   # made-up number, pattern only
    assert "aadhaar" in find_p3(text)
    out, n = redact_p3(text)
    assert n == 1 and "२३४५" not in out and "[WITHHELD]" in out
    assert out.startswith("माझा आधार ") and out.endswith("आहे, बिल ८४० रुपये")   # the rest is untouched
    assert find_p3("OTP ४८२९१७ आहे") == ["otp"]
