FROM python:3.8-slim

WORKDIR /workspace
COPY benchmarks/requirements/fastapi_bug12.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt pytest-cov==2.12.1 coverage==5.5
USER nobody