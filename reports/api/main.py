from __future__ import annotations

import os
from datetime import date
from typing import Any

import clickhouse_connect
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "reports")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "reports")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "reports_password")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

PIPELINE_NAME = "reports_etl"


class ReportItem(BaseModel):
    day: date
    prosthesis_id: str
    product_model: str
    events_count: int
    avg_reaction_time_ms: float
    p95_reaction_time_ms: float
    avg_battery_level: float
    min_battery_level: float
    avg_signal_quality: float


class ClientProfile(BaseModel):
    full_name: str
    email: str
    city: str
    orders_count: int
    total_spent: float
    last_order_date: date | None


class ReportResponse(BaseModel):
    user_id: str
    profile: ClientProfile | None
    period_from: date | None
    period_to: date
    processed_until: date
    items: list[ReportItem]


app = FastAPI(title="BionicPRO Reports API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Authorization", "Content-Type"],
)


def clickhouse_client():
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        database=CLICKHOUSE_DATABASE,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
    )


def get_processed_until(client) -> date:
    result = client.query(
        """
        SELECT processed_until
        FROM etl_processing_state
        WHERE pipeline_name = {pipeline:String}
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        parameters={"pipeline": PIPELINE_NAME},
    ).result_rows
    if not result:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Report data is not ready yet",
        )
    value = result[0][0]
    return value if isinstance(value, date) else date.fromisoformat(str(value))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/reports/{user_id}", response_model=ReportResponse)
def get_report(
    user_id: str,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
) -> ReportResponse:
    if from_ and to and from_ > to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from must not be after to",
        )

    client = clickhouse_client()
    processed_until = get_processed_until(client)
    if to and to > processed_until:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Requested period has not been processed by Airflow yet",
                "processed_until": processed_until.isoformat(),
            },
        )

    filters = ["user_id = {user_id:String}"]
    parameters: dict[str, Any] = {"user_id": user_id}
    if from_:
        filters.append("day >= {from_date:Date}")
        parameters["from_date"] = from_
    parameters["to_date"] = to or processed_until
    filters.append("day <= {to_date:Date}")

    rows = client.query(
        f"""
        SELECT
            full_name, email, city, orders_count, total_spent, last_order_date,
            day, prosthesis_id, product_model, events_count, avg_reaction_time_ms,
            p95_reaction_time_ms, avg_battery_level, min_battery_level,
            avg_signal_quality
        FROM prosthesis_report_mart
        WHERE {' AND '.join(filters)}
        ORDER BY day, prosthesis_id
        """,
        parameters=parameters,
    ).result_rows

    profile = None
    if rows:
        profile = ClientProfile(
            full_name=rows[0][0],
            email=rows[0][1],
            city=rows[0][2],
            orders_count=rows[0][3],
            total_spent=rows[0][4],
            last_order_date=rows[0][5],
        )
    items = [
        ReportItem(
            day=row[6],
            prosthesis_id=row[7],
            product_model=row[8],
            events_count=row[9],
            avg_reaction_time_ms=row[10],
            p95_reaction_time_ms=row[11],
            avg_battery_level=row[12],
            min_battery_level=row[13],
            avg_signal_quality=row[14],
        )
        for row in rows
    ]
    return ReportResponse(
        user_id=user_id,
        profile=profile,
        period_from=from_,
        period_to=to or processed_until,
        processed_until=processed_until,
        items=items,
    )
