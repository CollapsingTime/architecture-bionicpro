# BionicPRO

# Задание 1 задача 1
C4-диаграмма: `Task1/C4_BionicPRO_container_diagram.drawio`

# Задание 1 задача 2

## Запуск

```bash
docker compose up --build -d
```

далее в http://localhost:3000 -> Login -> `user1`/`password123`

## Проверка

```bash
# без code_challenge (PKCE обязателен)
curl -s -o /dev/null -w '%{redirect_url}\n' "http://localhost:8080/realms/reports-realm/protocol/openid-connect/auth?client_id=reports-frontend&response_type=code&redirect_uri=http://localhost:3000/*"

# password grant -> 400 unauthorized_client
curl -s -X POST "http://localhost:8080/realms/reports-realm/protocol/openid-connect/token" -d "grant_type=password&client_id=reports-frontend&username=user1&password=password123"
```

---

# Задание 2 задача 1
C4-диаграмма архитектуры отчетности (ETL Airflow -> витрина в ClickHouse -> API /reports): `Task2/C4_BionicPRO_reports_diagram.drawio`

# Задание 2 задача 2

Airflow-код отчётности в `reports/`

# Запуск проекта

## Первый запуск

1. Стек Keycloak + frontend из корня проекта:

```bash
docker compose up -d --build
```

2. Стек отчетности (Airflow + PostgreSQL + ClickHouse):

```bash
docker compose -f reports/docker-compose.yaml up -d --build
```

`airflow-init` при первом запуске создает базу Airflow, пользователя `admin` и снимает DAG с паузы

## Доступы

```text
Frontend:   http://localhost:3000  (user1 / password123)
Keycloak:   http://localhost:8080  (console: admin / admin)
Airflow UI: http://localhost:8081  (admin / admin)
ClickHouse: http://localhost:8123  (reports / reports_password)
```

## Перезапуск

```bash
docker compose up -d
docker compose -f reports/docker-compose.yaml up -d
```


# Задание 2 задача 3

Бэкенд API отчётов: `reports/api/` (Python + FastAPI), сервис `reports-api` в стеке `reports/`

## Проверка

```bash
curl -s http://localhost:8001/health

curl -s http://localhost:8001/reports/00000000-0000-0000-0000-000000000001
```
