import os

import psycopg
from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str


app = FastAPI(title="Bricky API")


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    database_url = os.environ["DATABASE_URL"]

    with psycopg.connect(database_url, connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

    if result != (1,):
        raise RuntimeError("PostgreSQL health query returned an unexpected result")

    return HealthResponse(status="ok", database="ok")
