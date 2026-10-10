"""Effect previews for approvals (jarvis/control/preview.py): one per tool, never raising."""

from jarvis.control.approvals import ApprovalRequest
from jarvis.control.preview import preview, roots_for, target_folder
from jarvis.db import Store


def _roots(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    return [ws]


def test_overwrite_shows_a_diff(tmp_path):
    roots = _roots(tmp_path)
    (roots[0] / "plan.txt").write_text("line one\nline two\nline three\n", encoding="utf-8")
    text = preview("overwrite_file", {"path": "plan.txt", "content": "line one\nline 2\nline three\n"}, roots)
    assert "Replace the content of: [[plan.txt]]" in text
    assert "- line two" in text and "+ line 2" in text
    assert "1 lines added, 1 lines removed" in text
    assert ".trash" in text  # the old version is kept


def test_overwrite_same_content_says_no_change(tmp_path):
    roots = _roots(tmp_path)
    (roots[0] / "a.txt").write_text("same", encoding="utf-8")
    assert "No change" in preview("overwrite_file", {"path": "a.txt", "content": "same"}, roots)


def test_write_shows_path_size_and_head(tmp_path):
    roots = _roots(tmp_path)
    text = preview("write_file", {"path": "notes/day.md", "content": "hello\nworld"}, roots)
    assert "Create new file: [[notes/day.md]]" in text
    assert "11 characters, 11 bytes" in text
    assert "New folder will be created: notes" in text
    assert "| hello" in text


def test_write_existing_file_is_flagged(tmp_path):
    roots = _roots(tmp_path)
    (roots[0] / "x.md").write_text("x", encoding="utf-8")
    assert "already exists" in preview("write_file", {"path": "x.md", "content": "y"}, roots)


def test_move_shows_both_paths_and_size(tmp_path):
    roots = _roots(tmp_path)
    (roots[0] / "a.txt").write_text("12345", encoding="utf-8")
    (roots[0] / "old").mkdir()
    text = preview("move_file", {"source": "a.txt", "destination": "old/"}, roots)
    assert "Move: [[a.txt]]" in text and "to: [[old/a.txt]]" in text and "5 bytes" in text


def test_delete_says_what_goes_to_trash(tmp_path):
    roots = _roots(tmp_path)
    (roots[0] / "bye.txt").write_text("abc", encoding="utf-8")
    text = preview("delete_file", {"path": "bye.txt"}, roots)
    assert "Delete: [[bye.txt]]" in text and "3 bytes" in text and "workspace/.trash" in text


def test_paths_outside_or_secret_are_called_out(tmp_path):
    roots = _roots(tmp_path)
    assert "outside the allowed folders" in preview("write_file", {"path": str(tmp_path / "x.txt"), "content": ""}, roots)
    assert "secret location" in preview("delete_file", {"path": ".env"}, roots)


def test_calendar_event_exactly(tmp_path):
    text = preview("calendar_create_event", {"title": "Dentist visit", "start": "2026-10-12T11:00:00+05:30",
                                             "location": "Clinic"}, tz_name="Asia/Kolkata")
    assert "Title:    [[Dentist visit]]" in text
    assert "[[Monday 12 Oct 2026, 11:00 to 11:30]]" in text
    assert "Where:    Clinic" in text
    bad = preview("calendar_create_event", {"title": "x", "start": "tomorrow"}, tz_name="Asia/Kolkata")
    assert "not an exact time" in bad


def test_gmail_send_and_draft(tmp_path):
    args = {"to": "asha@example.com, ravi@example.org", "subject": "Trip plan",
            "body": "Hi,\nsee https://example.com/plan\nthanks"}
    sent = preview("gmail_send", args)
    assert sent.startswith("SEND this email now")
    assert "[[asha@example.com]], [[ravi@example.org]]" in sent
    assert "Subject: Trip plan" in sent and "| see https://" in sent and "Site: [[example.com]]" in sent
    assert preview("gmail_draft", args).startswith("Save this email as a Gmail draft")


def test_url_domain_marked_and_warnings():
    text = preview("open_url", {"url": "https://www.example.com/a?b=1"})
    assert "https://[[www.example.com]]/a?b=1" in text and "Site: [[www.example.com]]" in text
    sneaky = preview("browser_open", {"url": "https://user:pw@evil.example/x"})
    assert "WARNING" in sneaky


def test_secrets_redacted_and_unknown_tools_empty(tmp_path):
    roots = _roots(tmp_path)
    text = preview("write_file", {"path": "k.txt", "content": "api key sk-ant-abcdefghijklmnopqrstuvwxyz123456"}, roots)
    assert "sk-ant-abcdefghijklmnop" not in text
    assert preview("weather", {"place": "Pune"}) == ""
    assert preview("write_file", {"path": 5}, roots).startswith(("Create", "(no preview"))  # never raises


def test_describe_puts_the_effect_first():
    req = ApprovalRequest("open_url", "T2", {"url": "https://example.com"}, "significant change",
                          preview="Open in the browser:\nURL: https://[[example.com]]", scope="also X")
    text = req.describe()
    assert text.index("WHAT WILL HAPPEN") < text.index("with:")
    assert "ALSO: also X" in text
    assert "WHAT WILL HAPPEN" not in ApprovalRequest("t", "T2", {}, "r").describe()


def test_target_folder_and_roots_for(tmp_path, monkeypatch):
    roots = _roots(tmp_path)
    assert target_folder("write_file", {"path": "notes/a.md"}, roots) == (roots[0] / "notes").resolve()
    assert target_folder("write_file", {"path": "../x.md"}, roots) is None
    store = Store(tmp_path / "data" / "jarvis.db")
    try:
        found = roots_for(store.conn)
        assert found and found[0] == tmp_path / "workspace"
    finally:
        store.close()
