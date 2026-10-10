"""Migration eval graders (tests/evals/migration/tasks.yaml): the checks pass right answers
and fail wrong ones. All replies below are made up."""

from jarvis.evals import runner


def _task(task_id: str) -> dict:
    return next(t for t in runner.load_tasks() if t["id"] == task_id)


def test_weather_needs_a_real_temperature_reading():
    task = _task("tool-weather")
    for reply in ("Sir, Punyat aata 27.5°C ahe, aakash nirabhra.",
                  "Pune today: 22–31 °C, light wind.",
                  "It is about 29 degrees in Pune, sir.",
                  "पुण्यात आज २८ अंश सेल्सिअस तापमान आहे.",
                  "Pune madhe aaj 30 C, paus nahi."):
        assert runner.check(task, reply, None, ["weather"]) == (True, "ok"), reply


def test_weather_rejects_replies_without_a_temperature():
    task = _task("tool-weather")
    # the old check accepted any "c", so these passed ("correct", "chance", "cloudy")
    for reply in ('I could not find the weather for "Punyachi". Please give the correct place.',
                  "Pune: cloudy, 40% chance of rain, wind 6 km/h.",
                  "Sir, mala Punyacha weather sapadla nahi."):
        ok, detail = runner.check(task, reply, None, ["weather"])
        assert not ok and detail.startswith("matches none of"), reply
    # a reading without the tool call still fails
    assert not runner.check(task, "Pune: 27°C.", None, [])[0]


def test_devanagari_greeting_needs_a_marathi_reply():
    task = _task("greet-mr-deva-morning")
    for reply in ("सुप्रभात, sir. आज मी तुमच्यासाठी काय करू?", "शुभ सकाळ! आजचा दिवस छान जावो."):
        assert runner.check(task, reply, None, []) == (True, "ok"), reply


def test_devanagari_greeting_rejects_an_english_reply():
    task = _task("greet-mr-deva-morning")
    for reply in ("Good morning, sir.", "Good morning, sir! सुप्रभात. How can I help you today?"):
        ok, detail = runner.check(task, reply, None, [])
        assert not ok and detail.startswith("Devanagari share"), reply
    # Marathi without a morning greeting still fails, as before
    assert not runner.check(task, "नमस्कार, सर. आज काय करायचं?", None, [])[0]


def test_devanagari_share():
    assert runner.devanagari_share("नमस्कार") == 1.0
    assert runner.devanagari_share("Hello") == 0.0
    assert runner.devanagari_share("123 ...") == 0.0
    assert 0.5 < runner.devanagari_share("सुप्रभात, sir.") < 1.0
