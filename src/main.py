"""
OdontoQuiz Pipeline — API Principal (FastAPI)
Substitui os webhooks do n8n (WF4: /mcp/ingestao-materiais, WF3: Webhook de Decisão Portal).
Hospedagem: Railway
"""
import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .core.config import get_settings
from .core.pipeline import get_pipeline
from .models.schemas import (
    PayloadIngestao,
    PayloadDecisao,
    IngestaoResponse,
    StatusResponse,
    StatusArquivo,
)

# ─── Logging ──────────────────────────────────────────────────────────────────

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("odontoquiz")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialização e shutdown da aplicação."""
    logger.info(f"🚀 {settings.app_name} v{settings.app_version} iniciando...")
    logger.info(f"   OdontoQuiz API: {settings.odontoquiz_api_base_url}")
    logger.info(f"   Supabase: {settings.supabase_url}")
    yield
    logger.info("👋 OdontoQuiz Pipeline encerrado.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
)

# ─── CORS ────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.lovableproject\.com",
    allow_origins=[
        "https://ae3ac8e8-0445-4116-9b09-467f7ab0ea10.lovableproject.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ─── Middleware ────────────────────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log de todas as requisições."""
    start = __import__("time").time()
    response = await call_next(request)
    duration = __import__("time").time() - start
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration:.3f}s)")
    return response


# ─── Auth Helper ──────────────────────────────────────────────────────────────

def validar_token(authorization: Optional[str] = Header(None)) -> str:
    """Valida o token de autorização do webhook."""
    if not settings.webhook_token:
        # Token não configurado = modo dev (sem validação)
        return "dev"

    if not authorization:
        raise HTTPException(status_code=401, detail="Token de autorização ausente")

    token = authorization.replace("Bearer ", "").strip()
    if token != settings.webhook_token:
        raise HTTPException(status_code=401, detail="Token inválido")

    return token


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Healthcheck."""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "online",
        "deploy": "opt-handler-fix",
    }


@app.get("/health")
async def health():
    """Healthcheck detalhado."""
    return {"status": "healthy", "timestamp": __import__("datetime").datetime.now().isoformat()}


# ─── CORS Preflight ───────────────────────────────────────────────────────────

@app.options("/{rest_of_path:path}")
async def cors_preflight(rest_of_path: str):
    """Handler explícito de preflight CORS para todos os paths."""
    return Response(status_code=200)


@app.post("/mcp/ingestao-materiais", response_model=IngestaoResponse)
async def ingestao_materiais(
    payload: PayloadIngestao,
    authorization: str = Header(None),
):
    """
    Webhook de ingestão de materiais (substitui WF4).
    Recebe um lote de arquivos (provas + gabaritos) e inicia o processamento.

    Payload esperado:
    ```json
    {
      "lote_id": "opcional-uuid",
      "arquivos": [
        {
          "nome_original": "prova_tipo1_pag1.jpg",
          "storage_path": "lotes/xxx/originais/prova_tipo1_pag1.jpg",
          "tipo_hint": "prova"
        }
      ],
      "metadados": {}
    }
    ```
    """
    validar_token(authorization)

    pipeline = get_pipeline()
    resultado = await pipeline.processar_ingestao(payload.model_dump())

    return resultado


@app.post("/portal/decisao")
async def portal_decisao(
    payload: PayloadDecisao,
    authorization: str = Header(None),
):
    """
    Webhook de decisão do portal (substitui WF3).
    Recebe a decisão humana sobre questões que precisam de revisão.
    """
    validar_token(authorization)

    # TODO: implementar lógica completa de decisão
    return {"status": "recebido", "decisoes": len(payload.decisoes)}


@app.get("/lotes/{lote_id}/status", response_model=StatusResponse)
async def status_lote(lote_id: str):
    """Consulta o status de um lote."""
    pipeline = get_pipeline()
    lote = pipeline.supabase.buscar_lote(lote_id)

    if not lote:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    arquivos = pipeline.supabase.listar_arquivos_lote(lote_id)
    pares = pipeline.supabase.listar_pares_lote(lote_id)

    return StatusResponse(
        lote_id=lote_id,
        status=lote.get("status", "desconhecido"),
        arquivos=arquivos,
        pares=pares,
    )


@app.get("/lotes/{lote_id}/arquivos/{arquivo_id}")
async def resultado_arquivo(lote_id: str, arquivo_id: str):
    """Retorna o resultado do processamento de um arquivo específico."""
    pipeline = get_pipeline()
    arquivo = pipeline.supabase.buscar_arquivo(arquivo_id)

    if not arquivo:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")

    return arquivo


# ─── Error Handlers ────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handler global de exceções."""
    logger.exception(f"Erro não tratado: {exc}")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc)},
    )


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
