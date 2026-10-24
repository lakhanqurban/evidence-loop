FROM python:3.8-slim

WORKDIR /workspace
RUN pip install --no-cache-dir \
    appdirs==1.4.3 \
    click==7.0 \
    mypy-extensions==0.4.3 \
    pathspec==0.7.0 \
    pytest==5.4.3 \
    pytest-cov==2.12.1 \
    coverage==5.5 \
    regex==2020.2.20 \
    toml==0.10.0 \
    typed-ast==1.4.0
ENV LANG=C LC_ALL=C PYTHONCOERCECLOCALE=0 PYTHONUTF8=0
USER nobody