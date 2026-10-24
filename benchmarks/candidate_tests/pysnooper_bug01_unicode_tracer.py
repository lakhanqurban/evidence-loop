# -*- coding: utf-8 -*-
"""Independent oracle candidate for BugsInPy PySnooper bug 1 (fix commit 56f22f8).

Behavioral spec: tracing a function whose source line and variable value contain
non-ASCII characters must succeed on Python 3 without an encoding error, and the
trace log file must be valid UTF-8 containing the traced source line and value.

On the buggy revision the log file is written with the default locale encoding,
which raises UnicodeEncodeError under a C/limited locale; the fixed revision
forces UTF-8 and passes.
"""

import pysnooper


def test_non_ascii_trace_writes_utf8_log(tmp_path):
    log_path = tmp_path / "unicode-trace.log"

    @pysnooper.snoop(str(log_path))
    def traced():
        x = "Łódź"
        y = x.upper()
        return y

    assert traced() == "ŁÓDŹ"

    raw = log_path.read_bytes()
    text = raw.decode("utf-8")

    assert "x = 'Łódź'" in text
    assert "'Łódź'" in text
    assert "'ŁÓDŹ'" in text
