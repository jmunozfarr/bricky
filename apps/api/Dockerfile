FROM python:3.14-slim AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock


FROM dependencies AS development

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM dependencies AS production

ARG APP_UID=1000
ARG APP_GID=1000

RUN groupadd --gid "${APP_GID}" bricky \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home bricky

COPY --chown=bricky:bricky app ./app
COPY --chown=bricky:bricky alembic ./alembic
COPY --chown=bricky:bricky alembic.ini ./

USER bricky

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-server-header"]
