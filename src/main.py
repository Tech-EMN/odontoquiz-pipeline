"""
OdontoQuiz Pipeline — API Principal (FastAPI)
Substitui os webhooks do n8n (WF4: /mcp/ingestao-materiais, WF3: Webhook de Decisão Portal).
Hospedagem: Railway
"""
import logging
import sys
import tempfile
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Header, Request, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

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
    Webhook de ingestão de materiais — JSON (substitui WF4).
    Recebe um lote de arquivos (provas + gabaritos) com storage_paths.
    """
    validar_token(authorization)
    pipeline = get_pipeline()
    resultado = await pipeline.processar_ingestao(payload.model_dump())
    return resultado


@app.post("/mcp/ingestao-upload")
async def ingestao_upload(
    provas: List[UploadFile] = File(default_factory=list),
    gabaritos: List[UploadFile] = File(default_factory=list),
    origem: str = Form(default="upload_manual"),
    criado_por: str = Form(default="anon"),
    observacoes: str = Form(default=""),
    tracking_id: str = Form(default=""),
    session_id: str = Form(default=""),
    authorization: str = Header(None),
):
    """
    Webhook de ingestão com upload direto (multipart/form-data).
    Aceita arquivos enviados diretamente do frontend Lovable.

    Campos:
    - provas: lista de arquivos de imagem/PDF das provas
    - gabaritos: lista de arquivos de imagem/PDF dos gabaritos
    - origem: fonte do upload (default: upload_manual)
    - criado_por: identificador do usuário
    - observacoes: notas adicionais
    """
    validar_token(authorization)

    from .utils.file_utils import normalize_filename, validate_file

    pipeline = get_pipeline()
    lotes_dir = f"lotes/{tracking_id}" if tracking_id else f"lotes/manual_{criado_por}"
    arquivos_entrada = []

    # Processar provas
    for f in provas:
        nome_normalizado = normalize_filename(f.filename or "prova.jpg")
        storage_path = f"{lotes_dir}/originais/{nome_normalizado}"

        # Salvar temporariamente para upload ao Supabase
        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            content = await f.read()
            tmp.write(content)
            tmp_path = tmp.name

        # Validar qualidade
        validation = validate_file(tmp_path, f.filename or nome_normalizado)

        # Upload para Supabase Storage
        content_type = f.content_type or "image/jpeg"
        pipeline.supabase.upload_arquivo(tmp_path, storage_path, content_type)

        # Limpar temp
        import os
        os.unlink(tmp_path)

        arquivos_entrada.append({
            "nome_original": f.filename or "prova.jpg",
            "storage_path": storage_path,
            "tipo_hint": "prova",
            "validation": validation,
        })

    # Processar gabaritos
    for f in gabaritos:
        nome_normalizado = normalize_filename(f.filename or "gabarito.jpg")
        storage_path = f"{lotes_dir}/originais/{nome_normalizado}"

        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            content = await f.read()
            tmp.write(content)
            tmp_path = tmp.name

        validation = validate_file(tmp_path, f.filename or nome_normalizado)
        content_type = f.content_type or "image/jpeg"
        pipeline.supabase.upload_arquivo(tmp_path, storage_path, content_type)
        import os
        os.unlink(tmp_path)

        arquivos_entrada.append({
            "nome_original": f.filename or "gabarito.jpg",
            "storage_path": storage_path,
            "tipo_hint": "gabarito",
            "validation": validation,
        })

    if not arquivos_entrada:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado")

    # Criar payload e processar
    payload = {
        "lote_id": tracking_id or None,
        "arquivos": arquivos_entrada,
        "metadados": {
            "origem": origem,
            "criado_por": criado_por,
            "observacoes": observacoes,
            "tracking_id": tracking_id,
            "session_id": session_id,
        },
    }

    resultado = await pipeline.processar_ingestao(payload)

    # Adicionar warnings de validação
    warnings = [
        a["validation"].get("warning")
        for a in arquivos_entrada
        if a.get("validation", {}).get("warning")
    ]
    if warnings:
        resultado["warnings"] = warnings

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
