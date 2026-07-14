"""Log-sanitization helper.

The engine logs user- and LLM-supplied values (pack names, template titles,
etc.). This strips control characters from such values before they are logged so
they cannot forge or split log lines — the log-injection class SonarCloud flags
(S5145).
"""

from __future__ import annotations

import re

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_for_log(value: object) -> str:
    """Strip CR/LF and other control characters so user-supplied data cannot
    forge or split log lines (log injection)."""
    return _CONTROL_RE.sub(" ", str(value))
