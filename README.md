# OdontoQuiz Pipeline

Pipeline de processamento de materiais de concurso odontológico — migração dos workflows n8n para Python (FastAPI + Supabase + OpenAI).

## Arquitetura

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Lovable     │────▶│  FastAPI (Railway)│────▶│  Supabase     │
│  (Frontend)  │     │  /mcp/ingestao   │     │  (DB+Storage) │
└─────────────┘     │  /portal/decisao  │     └──────────────┘
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐     ┌──────────────┐
                    │  GPT-4o (OpenAI)  │────▶│  OdontoQuiz   │
                    │  Análise Imagem   │     │  API (Import) │
                    └──────────────────┘     └──────────────┘
```

## Workflows Migrados

| n8n | Python | Função |
|-----|--------|--------|
| WF1 | `OCRLevePipeline._ocr_leve()` | Classifica documento (prova/gabarito) |
| WF2 | `Etapa2Pipeline._etapa2_ocr()` | Extrai questões, gabarito, disciplinas |
| WF3 | `/portal/decisao` + `_importar_questoes()` | Portal de decisão + importação |
| WF4 | `/mcp/ingestao-materiais` | Ingestão de arquivos |

## Correções Aplicadas

Todas as 10 correções do handoff de 28/07 estão incorporadas:

| # | Correção | Implementação |
|---|----------|---------------|
| 1 | try/catch | `try/except` em todas as chamadas OpenAI |
| 2 | Fallback disciplinas | `_buscar_disciplinas_com_fallback()` |
| 3 | Mapear IDs | `_montar_payload_etapa2()` — fuzzy match |
| 4 | Remover hardcoded | Validação explícita sem IDs mágicos |
| 5 | Validar erro Analyze | `if resultado.get("error")` antes de processar |
| 6 | parseJsonSeguro | Contador `{`/`}` no lugar de regex greedy |
| 7 | Encoding | UTF-8 nativo do Python |
| 8 | deduplicarQuestoes | Score por `confianca_extracao * 200` |
| 9 | Validar schema | `len(alternativas) < 2` → skip |
| 10 | Credential | Service Role Key no `.env`, nunca em plain-text |

## Setup

```bash
# 1. Clone
git clone <repo>
cd odontoquiz-pipeline

# 2. Configure o ambiente
cp .env.example .env
# Edite .env com suas keys

# 3. Instale
pip install -r requirements.txt

# 4. Rode
uvicorn src.main:app --reload --port 8000
```

## Deploy no Railway

```bash
# 1. Instale o Railway CLI
npm i -g @railway/cli

# 2. Login
railway login

# 3. Link ao projeto
railway link

# 4. Configure as variáveis
railway variables set \
  SUPABASE_URL=https://ywydkdehygqcumgjefya.supabase.co \
  SUPABASE_SERVICE_ROLE_KEY=sua_key \
  OPENAI_API_KEY=sk-sua_key \
  ODONTOQUIZ_API_KEY=sua_key \
  WEBHOOK_TOKEN=seu_token

# 5. Deploy
railway up
```

## API Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| `GET` | `/` | Healthcheck |
| `GET` | `/health` | Healthcheck detalhado |
| `POST` | `/mcp/ingestao-materiais` | Ingestão de lote (WF4) |
| `POST` | `/portal/decisao` | Decisão do portal (WF3) |
| `GET` | `/lotes/{id}/status` | Status do lote |
| `GET` | `/lotes/{id}/arquivos/{id}` | Resultado do arquivo |

## Testes

```bash
# Enviar um lote de teste
curl -X POST http://localhost:8000/mcp/ingestao-materiais \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer seu_token" \
  -d '{
    "arquivos": [
      {
        "nome_original": "gabarito_oficial.jpg",
        "storage_path": "lotes/test/originais/gabarito.jpg",
        "tipo_hint": "gabarito"
      },
      {
        "nome_original": "prova_tipo1.jpg",
        "storage_path": "lotes/test/originais/prova_tipo1.jpg",
        "tipo_hint": "prova"
      }
    ]
  }'
```
