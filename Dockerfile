FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    LANG=C.UTF-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 sentinel \
    && mkdir -p /app/state \
    && chown -R sentinel:sentinel /app

COPY config.example.yaml ./config.example.yaml
COPY samples ./samples
RUN chown -R sentinel:sentinel /app/config.example.yaml /app/samples

USER sentinel

LABEL org.opencontainers.image.title="backup-sentinel" \
      org.opencontainers.image.description="Daily backup digest for Synology, Veeam, and QNAP" \
      org.opencontainers.image.licenses="MIT"

ENTRYPOINT ["backup-sentinel"]
CMD ["--help"]
