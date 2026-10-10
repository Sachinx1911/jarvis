"""`jarvis app --url`: the Mac app reads the local dashboard link from it."""

import io

from jarvis.cli_app import main


def test_url_prints_one_local_link_with_the_token(isolated):
    out = io.StringIO()
    import sys

    old = sys.stdout
    sys.stdout = out
    try:
        assert main(["--url"]) == 0
    finally:
        sys.stdout = old
    line = out.getvalue().strip()
    assert line.startswith("http://127.0.0.1:") and "#token=" in line and len(line.splitlines()) == 1
    # the same token every time (it is created once and kept in the OS secret store)
    out2 = io.StringIO()
    sys.stdout = out2
    try:
        main(["--url"])
    finally:
        sys.stdout = old
    assert out2.getvalue().strip() == line
