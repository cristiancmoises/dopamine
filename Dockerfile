# syntax=docker/dockerfile:1
# Multi-architecture official CPython image. Pull security updates at each release.
# Pin an approved digest after your own image audit for byte-identical base selection.
FROM python:3.13-slim AS tested
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --only-binary=:all: -r requirements.txt && python -m pip check
COPY app ./app
COPY data ./data
COPY tests ./tests
COPY scripts ./scripts
COPY manage.py gunicorn.conf.py ./
RUN python manage.py test \
    && python -m gunicorn --check-config --config gunicorn.conf.py app.web:application
# Downloads occur during build, not when a visitor opens the site.
# No deploy secrets are needed or copied during image construction.
RUN --mount=type=cache,id=dopamine-real-catalog-v120,target=/catalog-cache,sharing=locked \
    DOPAMINE_CATALOG_CACHE=/catalog-cache python manage.py photos && python manage.py verify-photos
RUN python -m pip freeze > /app/data/installed-packages.txt

FROM python:3.13-slim AS runtime
LABEL org.opencontainers.image.title="Dopamine" org.opencontainers.image.version="1.2.0"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY --from=tested /usr/local /usr/local
COPY --from=tested /app /app
COPY LICENSE NOTICE README.md ./
COPY docs ./docs
RUN chmod -R a+rX /app \
    && groupadd --gid 10001 dopamine \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin dopamine \
    && mkdir -p /data \
    && chown 10001:10001 /data \
    && chmod 700 /data
USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "/app/scripts/entrypoint.py"]
