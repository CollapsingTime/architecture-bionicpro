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
