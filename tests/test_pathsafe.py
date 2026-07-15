"""engine.pathsafe.sanitize_for_log — log-injection defence."""

from engine.pathsafe import sanitize_for_log


def test_sanitize_strips_newlines_and_control_chars():
    # CR/LF/TAB and other control chars become spaces so a user-supplied value
    # cannot forge or split a log line.
    assert sanitize_for_log("line1\nline2\r\tX") == "line1 line2  X"


def test_sanitize_coerces_non_strings():
    assert sanitize_for_log(123) == "123"


def test_sanitize_leaves_clean_text_untouched():
    assert sanitize_for_log("technical-spike v2") == "technical-spike v2"
