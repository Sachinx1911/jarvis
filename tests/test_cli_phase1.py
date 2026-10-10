import io

from jarvis.cli import main


def test_init_creates_soul_and_memory_index(isolated):
    main(["init"], out=io.StringIO())
    assert (isolated / "profile" / "SOUL.md").exists()
    assert (isolated / "memory" / "MEMORY.md").exists()


def test_chat_remember_then_search(isolated):
    out = io.StringIO()
    inp = io.StringIO("/remember the demo garage closes at 7 pm\n/memory garage\n/exit\n")
    assert main(["chat", "--provider", "fake"], out=out, inp=inp) == 0
    text = out.getvalue()
    assert "Remembered as m-0001" in text
    assert "m-0001 [fact]" in text


def test_memory_commands(isolated):
    out = io.StringIO()
    main(["memory", "add", "--provider", "fake", "demo", "office", "is", "on", "floor", "3"], out=out)
    main(["memory", "list"], out=out)
    main(["memory", "show", "m-0001"], out=out)
    main(["memory", "archive", "m-0001"], out=out)
    main(["memory", "list"], out=(after := io.StringIO()))
    text = out.getvalue()
    assert "Remembered as m-0001" in text and "evidence: demo office is on floor 3" in text
    assert after.getvalue() == ""


def test_memory_add_rejects_secret(isolated):
    out = io.StringIO()
    assert main(["memory", "add", "--provider", "fake", "password:", "hunter22"], out=out) == 1
    assert "Not saved" in out.getvalue()


def test_stop_and_resume(isolated):
    out = io.StringIO()
    main(["stop", "testing"], out=out)
    assert main(["chat", "--provider", "fake", "-m", "hello"], out=out) == 1
    assert "Stopped" in out.getvalue()
    main(["resume"], out=out)
    assert main(["chat", "--provider", "fake", "-m", "hello"], out=out) == 0


def test_sessions_search(isolated):
    main(["chat", "--provider", "fake", "-m", "remember the purple umbrella"], out=io.StringIO())
    out = io.StringIO()
    main(["sessions", "search", "umbrella"], out=out)
    assert "purple umbrella" in out.getvalue()


def test_interview_saves_answers(isolated):
    out = io.StringIO()
    inp = io.StringIO("Call me boss, English and Marathi\n\n/stop\n")
    assert main(["interview", "--provider", "fake"], out=out, inp=inp) == 0
    assert "saved m-0001" in out.getvalue()


def test_eval_runner_with_fake(isolated):
    out = io.StringIO()
    assert main(["eval", "--provider", "fake"], out=out) == 0
    text = out.getvalue()
    assert "PASS greet-en-evening" in text  # the fake greets
    assert "PASS extract-ignores-small-talk" in text
    assert "passed. Saved:" in text
    assert list((isolated / "data" / "evals").glob("*-fake.jsonl"))
