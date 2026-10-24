FROM python:3.8-slim

WORKDIR /workspace
RUN pip install --no-cache-dir \
    pytest==5.4.3 \
    pytest-cov==2.12.1 \
    coverage==5.5
# PySnooper bug 1: log writing must use UTF-8; a limited locale must not crash it.
# PYTHONCOERCECLOCALE=0 + PYTHONUTF8=0 keep the C locale meaningful (PEP 538 would
# otherwise silently coerce C -> C.UTF-8 and hide the bug).
ENV LANG=C LC_ALL=C PYTHONCOERCECLOCALE=0 PYTHONUTF8=0
USER nobody
