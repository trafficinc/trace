ARG PYTHON_IMAGE=python:3.13-slim-bookworm
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TRACE_STORAGE_ROOT=/storage DJANGO_SETTINGS_MODULE=config.settings.production
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements /app/requirements
ARG WITH_POSTGRES=0
RUN python -m pip install --no-cache-dir -r requirements/runtime.txt \
    && if [ "$WITH_POSTGRES" = "1" ]; then python -m pip install --no-cache-dir -r requirements/postgres.txt; fi
# Explicit allowlist: no uploads, SQLite files, backups, secrets or test artifacts.
COPY apps /app/apps
COPY config /app/config
COPY templates /app/templates
COPY report_templates /app/report_templates
COPY static /app/static
COPY scripts /app/scripts
COPY manage.py pyproject.toml README.md LICENSE /app/
RUN python scripts/vendor_assets.py --check \
    && useradd --uid 10001 --create-home trace \
    && mkdir -p /storage && chown trace:trace /storage \
    && TRACE_STORAGE_ROOT=/tmp/trace-static python manage.py collectstatic --noinput --settings=config.settings.development \
    && chmod -R a+rX /app/staticfiles \
    && rm -rf /tmp/trace-static
USER trace
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["python", "scripts/healthcheck.py"]
CMD ["python", "scripts/serve.py", "--host", "0.0.0.0", "--allow-lan"]
