FROM python:3.11-slim

WORKDIR /workspace
COPY . /workspace
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -e . 'pytest>=8.0' 'pytest-cov>=5.0'
USER nobody

CMD ["python", "-m", "evidenceloop.cli", "--help"]
