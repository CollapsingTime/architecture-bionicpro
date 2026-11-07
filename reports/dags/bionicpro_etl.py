from __future__ import annotations

import csv
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import clickhouse_connect
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

INPUT_DIR = Path(os.environ.get("AIRFLOW_INPUT_DIR", "/opt/airflow/sample_files"))
CREATE_MART_SQL = Path("/opt/airflow/dags/sql/create_report_mart.sql")

CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_DATABASE = os.environ.get("CLICKHOUSE_DATABASE", "reports")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "reports")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "reports_password")

MART_TABLE = "reports.prosthesis_report_mart"
STATE_TABLE = "reports.etl_processing_state"

DAG_DOC = """
### BionicPRO отчётность (CRM + телеметрия -> ClickHouse)

`load_crm_fixtures` -> `build_report_mart` -> `update_processed_until`.

Витрина `reports.prosthesis_report_mart` хранит **готовые** дневные агрегаты
по каждому пользователю (`ORDER BY (user_id, prosthesis_id, day)`),
поэтому API не выполняет тяжёлых вычислений в реальном времени.
"""


def read_csv(name: str) -> list[dict[str, str]]:
    with (INPUT_DIR / name).open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def load_crm_fixtures() -> None:
    """Extract: обеспечить таблицы-источники в Postgres и залить данные."""
    hook = PostgresHook(postgres_conn_id="postgres_source")
    hook.run(
        """
        CREATE TABLE IF NOT EXISTS crm_clients (
            buyer_id BIGINT PRIMARY KEY,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            city TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS crm_orders (
            id BIGINT PRIMARY KEY,
            order_number BIGINT NOT NULL,
            total NUMERIC(18, 2) NOT NULL,
            discount NUMERIC(18, 2) NOT NULL,
            buyer_id BIGINT NOT NULL,
            order_date DATE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS crm_prostheses (
            buyer_id BIGINT NOT NULL,
            prosthesis_id TEXT PRIMARY KEY,
            product_model TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_identity_map (
            keycloak_sub TEXT PRIMARY KEY,
            buyer_id BIGINT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telemetry_events (
            prosthesis_id TEXT NOT NULL,
            event_time TIMESTAMP NOT NULL,
            reaction_time_ms DOUBLE PRECISION NOT NULL,
            battery_level DOUBLE PRECISION NOT NULL,
            signal_quality DOUBLE PRECISION NOT NULL
        );
        TRUNCATE crm_clients, crm_orders, crm_prostheses, user_identity_map, telemetry_events;
        """
    )

    hook.insert_rows(
        table="crm_clients",
        rows=[
            (int(row["buyer_id"]), row["full_name"], row["email"], row["city"])
            for row in read_csv("clients.csv")
        ],
        target_fields=["buyer_id", "full_name", "email", "city"],
    )
    hook.insert_rows(
        table="crm_orders",
        rows=[
            (
                int(row["id"]),
                int(row["order_number"]),
                float(row["total"]),
                float(row["discount"]),
                int(row["buyer_id"]),
                row["order_date"],
            )
            for row in read_csv("orders.csv")
        ],
        target_fields=["id", "order_number", "total", "discount", "buyer_id", "order_date"],
    )
    hook.insert_rows(
        table="crm_prostheses",
        rows=[
            (int(row["buyer_id"]), row["prosthesis_id"], row["product_model"])
            for row in read_csv("prostheses.csv")
        ],
        target_fields=["buyer_id", "prosthesis_id", "product_model"],
    )
    hook.insert_rows(
        table="user_identity_map",
        rows=[
            (row["keycloak_sub"], int(row["buyer_id"]))
            for row in read_csv("user_identity_map.csv")
        ],
        target_fields=["keycloak_sub", "buyer_id"],
    )
    hook.insert_rows(
        table="telemetry_events",
        rows=[
            (
                row["prosthesis_id"],
                datetime.fromisoformat(row["event_time"]),
                float(row["reaction_time_ms"]),
                float(row["battery_level"]),
                float(row["signal_quality"]),
            )
            for row in read_csv("telemetry.csv")
        ],
        target_fields=[
            "prosthesis_id",
            "event_time",
            "reaction_time_ms",
            "battery_level",
            "signal_quality",
        ],
    )


def clickhouse_client():
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        database=CLICKHOUSE_DATABASE,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
    )


def ensure_clickhouse_tables(client) -> None:
    for statement in CREATE_MART_SQL.read_text(encoding="utf-8").split(";"):
        statement = statement.strip()
        if statement:
            client.command(statement)


def build_report_mart() -> str:
    """Transform + Load: агрегаты телеметрии в разрезе клиентов -> витрина OLAP БД."""
    hook = PostgresHook(postgres_conn_id="postgres_source")

    metrics = hook.get_records(
        """
        SELECT
            identity.keycloak_sub,
            identity.buyer_id,
            telemetry.prosthesis_id,
            prostheses.product_model,
            telemetry.event_time::date AS day,
            count(*) AS events_count,
            avg(telemetry.reaction_time_ms) AS avg_reaction,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY telemetry.reaction_time_ms) AS p95_reaction,
            avg(telemetry.battery_level) AS avg_battery,
            min(telemetry.battery_level) AS min_battery,
            avg(telemetry.signal_quality) AS avg_signal
        FROM telemetry_events AS telemetry
        JOIN crm_prostheses AS prostheses
          ON prostheses.prosthesis_id = telemetry.prosthesis_id
        JOIN user_identity_map AS identity
          ON identity.buyer_id = prostheses.buyer_id
        GROUP BY
            identity.keycloak_sub,
            identity.buyer_id,
            telemetry.prosthesis_id,
            prostheses.product_model,
            telemetry.event_time::date
        ORDER BY identity.keycloak_sub, telemetry.prosthesis_id, day
        """
    )

    profiles = {
        row[0]: row[1:]
        for row in hook.get_records(
            """
            SELECT
                clients.buyer_id,
                clients.full_name,
                clients.email,
                clients.city,
                count(orders.id) AS orders_count,
                coalesce(sum(orders.total - orders.discount), 0) AS total_spent,
                max(orders.order_date) AS last_order_date
            FROM crm_clients AS clients
            LEFT JOIN crm_orders AS orders
              ON orders.buyer_id = clients.buyer_id
            GROUP BY clients.buyer_id, clients.full_name, clients.email, clients.city
            """
        )
    }

    client = clickhouse_client()
    ensure_clickhouse_tables(client)
    client.command(f"TRUNCATE TABLE {MART_TABLE}")

    mart_rows = []
    for user_id, buyer_id, prosthesis_id, product_model, event_day, events_count, avg_reaction, p95_reaction, avg_battery, min_battery, avg_signal in metrics:
        profile = profiles.get(buyer_id)
        if profile is None:  # клиент CRM без профиля не попадает в витрину
            continue
        mart_rows.append(
            (
                user_id,
                prosthesis_id,
                event_day,
                str(product_model),
                str(profile[0]),
                str(profile[1]),
                str(profile[2]),
                int(profile[3]),
                float(profile[4]),
                profile[5],
                int(events_count),
                float(avg_reaction),
                float(p95_reaction),
                float(avg_battery),
                float(min_battery),
                float(avg_signal),
            )
        )
    if not mart_rows:
        raise ValueError("Витрина пуста: телеметрия не соотнесена с данными CRM")

    client.insert(
        MART_TABLE,
        mart_rows,
        column_names=[
            "user_id",
            "prosthesis_id",
            "day",
            "product_model",
            "full_name",
            "email",
            "city",
            "orders_count",
            "total_spent",
            "last_order_date",
            "events_count",
            "avg_reaction_time_ms",
            "p95_reaction_time_ms",
            "avg_battery_level",
            "min_battery_level",
            "avg_signal_quality",
        ],
        column_type_names=[
            "String",
            "String",
            "Date",
            "LowCardinality(String)",
            "String",
            "String",
            "LowCardinality(String)",
            "UInt32",
            "Float64",
            "Nullable(Date)",
            "UInt64",
            "Float64",
            "Float64",
            "Float64",
            "Float64",
            "Float64",
        ],
    )
    return max(row[2] for row in mart_rows).isoformat()


def update_processed_until(**context) -> None:
    """Фиксация обработанного периода: отчёты отдаём только за эти дни."""
    processed_until = context["ti"].xcom_pull(task_ids="build_report_mart")
    if not processed_until:
        raise ValueError("Витрина пуста; processed_until не может быть обновлён")

    client = clickhouse_client()
    ensure_clickhouse_tables(client)
    client.command(f"TRUNCATE TABLE {STATE_TABLE}")
    client.insert(
        STATE_TABLE,
        [
            (
                "reports_etl",
                date.fromisoformat(processed_until),
                context["run_id"],
                datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0),
            )
        ],
        column_names=["pipeline_name", "processed_until", "run_id", "updated_at"],
    )


with DAG(
    dag_id="bionicpro_reports_etl",
    description="ETL: CRM + телеметрия -> витрина отчётов в ClickHouse",
    schedule="0 3 * * *",
    start_date=datetime(2025, 12, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "depends_on_past": False,
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["bionicpro", "reports"],
    doc_md=DAG_DOC,
) as dag:
    load = PythonOperator(task_id="load_crm_fixtures", python_callable=load_crm_fixtures)
    build = PythonOperator(task_id="build_report_mart", python_callable=build_report_mart)
    mark_state = PythonOperator(
        task_id="update_processed_until", python_callable=update_processed_until
    )

    load >> build >> mark_state
