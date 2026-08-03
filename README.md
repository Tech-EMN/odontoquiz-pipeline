# OdontoQuiz Pipeline

Pipeline de processamento de materiais de concurso odontológico — migração dos workflows n8n para Python (FastAPI + Supabase + OpenAI + Celery).

**Fases concluídas:** F0 ✓ F1 ✓ F2 ✓ F3 ✓ F4 ✓ F5 ✓ F6 ✓ F7 ✓ F8 ✓ F9 ✓ F10 ✓

## Estrutura do Monorepo

```
odontoquiz-pipeline/
├── .github/
│   └── workflows/ci.yml       # CI/CD (F9)
├── backend/
│   ├── src/
│   │   ├── main.py            # FastAPI — 6 endpoints
│   │   ├── core/
│   │   │   ├── config.py      # pydantic-settings
│   │   │   ├── pipeline.py    # Pipeline principal (7 etapas)
│   │   │   └── logging.py     # structlog + trace_id (F4)
│   │   ├── models/
│   │   │   └── schemas.py     # Pydantic models
│   │   ├── services/
│   │   │   ├── supabase.py     # DB + Storage
│   │   │   ├── openai_client.py
│   │   │   ├── odontoquiz_api.py
│   │   │   └── discipline_cache.py
│   │   ├── workers/
│   │   │   ├── celery_app.py   # Celery config (F2)
│   │   │   ├── tasks.py        # Pipeline tasks
│   │   │   └── decisao_tasks.py # Portal decisions (F6)
│   │   └── utils/
│   │       └── file_utils.py
│   ├── tests/
│   │   ├── conftest.py         # Fixtures (F5)
│   │   └── test_pipeline.py    # Unit tests (F5)
│   ├── migrations/             # Alembic (F3)
│   │   ├── env.py
│   │   └── versions/
│   │       └── 7d9590245845_initial_schema.py
│   ├── alembic.ini
│   ├── Dockerfile              # Multi-purpose (F2)
│   ├── docker-compose.yml      # Dev env: redis + api + worker + flower (F2)
│   ├── requirements.txt
│   └── RAILWAY.md              # Deploy guide (F8)
├── frontend/
│   └── README.md               # Placeholder (export Lovable pendente)
├── railway.toml
└── README.md
```

## Arquitetura

```
POST /mcp/ingestao  ──▶  200 OK <1s   ──▶  Celery Task (Redis)
        │                                        │
        │                                   ┌────▼────────────┐
        │                                   │  OCR Leve (WF1)  │
        │                                   │  Classificação   │
        │                                   └────┬────────────┘
        │                                   ┌────▼────────────┐
        │                                   │  Pareamento      │
        │                                   │  Prova↔Gabarito  │
        │                                   └────┬────────────┘
        │                                   ┌────▼────────────┐
        │                                   │  ETAPA 2 (WF2)   │
        │                                   │  Extração + IA   │
        │                                   └────┬────────────┘
        │                                        │
   GET /tasks/{id}/status ◀── Progress ─────────┘
        │
   POST /portal/decisao  ──▶  Import OdontoQuiz
```

## Setup

```bash
# 1. Clone
git clone https://github.com/Tech-EMN/odontoquiz-pipeline
cd odontoquiz-pipeline

# 2. Ambiente
cp backend/.env.example backend/.env
# Edite backend/.env com suas keys

# 3. Dependências
cd backend
pip install -r requirements.txt

# 4. Redis (necessário para Celery F2)
# Opção A: Docker
docker compose up redis -d

# Opção B: Redis local
redis-server

# 5. Migrations (F3)
DATABASE_URL="postgresql://..." alembic upgrade head

# 6. API
uvicorn backend.src.main:app --reload --port 8000

# 7. Worker (outro terminal)
celery -A backend.src.workers.celery_app worker --loglevel=info -c 2
```

## Deploy (Railway — F8)

Ver [backend/RAILWAY.md](backend/RAILWAY.md) para guia completo.

**Serviços:**
| Serviço | Start Command |
|---------|--------------|
| `api` | `uvicorn backend.src.main:app --host 0.0.0.0 --port ${PORT}` |
| `worker` | `celery -A backend.src.workers.celery_app worker --loglevel=info -c 2` |
| `flower` | `celery -A backend.src.workers.celery_app flower --port=${PORT}` |

## API Endpoints

| Método | Path | Descrição | Fase |
|--------|------|-----------|------|
| `GET` | `/` | Healthcheck | — |
| `GET` | `/health` | Healthcheck detalhado | — |
| `POST` | `/mcp/ingestao-materiais` | Ingestão JSON (WF4) | — |
| `POST` | `/mcp/ingestao-upload` | Upload multipart | — |
| `POST` | `/portal/decisao` | Decisão portal (F6) | F6 |
| `GET` | `/tasks/{id}/status` | Status Celery task (F2) | F2 |
| `GET` | `/lotes/{id}/status` | Status lote + progresso (F7) | F7 |
| `GET` | `/lotes/{id}/arquivos/{id}` | Resultado arquivo | — |

## Observabilidade (F4)

- **structlog** — JSON estruturado em produção
- **trace_id** — UUID único por requisição (header `X-Trace-ID`)
- **lote_id** — Rastreabilidade por lote em todos os logs

```json
{"event":"request","method":"POST","path":"/mcp/ingestao-materiais","status":200,"duration_ms":45,"trace_id":"a1b2c3d4e5f6","timestamp":"2026-08-03T21:00:00.000Z"}
```

## Testes (F5)

```bash
cd backend
pytest tests/ -v --cov=src --cov-report=term-missing
```

## CI/CD (F9)

Push para `main` dispara:
1. **Test** — pytest + coverage
2. **Lint** — Ruff (W, E, F)
3. **Migration check** — Alembic dry-run (upgrade + downgrade)
4. **Deploy** — Railway push-to-deploy automático

## Workflows Migrados

| n8n | Python | Função |
|-----|--------|--------|
| WF1 | `_ocr_leve()` | Classificar documento (prova/gabarito) |
| WF2 | `_etapa2_ocr()` | Extrair questões, gabarito, disciplinas |
| WF3 | `/portal/decisao` + `processar_decisao()` | Decisão + importação (F6) |
| WF4 | `/mcp/ingestao-materiais` | Ingestão + dedup + dispatcher Celery (F0/F2) |
