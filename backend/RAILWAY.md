# Railway Deploy — OdontoQuiz Pipeline (F8)

## Pré-requisitos

1. **Redis** — Adicionar plugin Redis ao projeto Railway
2. **Variáveis de ambiente** — Configurar no dashboard Railway ou `railway variables`

## Variáveis de ambiente necessárias

```bash
# Banco (Supabase pooler)
DATABASE_URL=postgresql://postgres.xxx:password@aws-0-region.pooler.supabase.com:6543/postgres

# Supabase (API REST)
SUPABASE_URL=https://ywydkdehygqcumgjefya.supabase.co
SUPABASE_SERVICE_ROLE_KEY=***

# OpenAI
OPENAI_API_KEY=***

# OdontoQuiz
ODONTOQUIZ_API_BASE_URL=https://www.odontoquiz.com.br/api/v1/quiz-ai
ODONTOQUIZ_API_KEY=***

# Webhook
WEBHOOK_TOKEN=***

# Redis (auto-configurado pelo plugin Railway)
REDIS_URL=redis://<railway-redis-host>:6379/0
```

## Serviços

### 1. API (web service)
- **Nome:** `odontoquiz-api`
- **Build:** Nixpacks (auto-detect Python)
- **Start command:** `uvicorn backend.src.main:app --host 0.0.0.0 --port ${PORT}`
- **Healthcheck:** `GET /health`

### 2. Worker (background service)
- **Nome:** `odontoquiz-worker`
- **Build:** Nixpacks (mesmo build)
- **Start command:** `celery -A backend.src.workers.celery_app worker --loglevel=info --concurrency=2`
- **Sem healthcheck HTTP** (Celery heartbeat via Redis)

### 3. Flower (opcional — monitoramento)
- **Nome:** `odontoquiz-flower`
- **Start command:** `celery -A backend.src.workers.celery_app flower --port=${PORT}`

## Deploy Manual (CLI)

```bash
# Build local
railway up --service=api
railway up --service=worker

# Ou via Git (automático se conectado ao repo)
git push origin main
```

## Migrations

```bash
# Executar no serviço da API (Railway CLI):
railway run --service=api "cd backend && alembic upgrade head"

# Ou via variável de ambiente no deploy:
# RAILWAY_RUN_BUILD_COMMAND="cd backend && alembic upgrade head"
```
