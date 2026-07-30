"""
OdontoQuiz Pipeline — API Principal (FastAPI)
Substitui os webhooks do n8n (WF4: /mcp/ingestao-materiais, WF3: Webhook de Decisão Portal).
Hospedagem: Railway
"""
import logging
import sys
import tempfile
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Request, BackgroundTasks
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
    allow_origins=["*"],  # TODO: Restringir em produção
    allow_credentials=False,
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
    request: Request,
    authorization: str = Header(None),
):
    """
    Webhook de ingestão com upload direto (multipart/form-data).
    Compatível com o frontend Lovable (campos dinâmicos prova_1, prova_2, gabarito_1, etc).

    Formato esperado (igual ao que o Lovable envia):
    - provas: JSON string ["prova_1", "prova_2"]
    - gabaritos: JSON string ["gabarito_1"]
    - prova_1: File
    - prova_2: File
    - gabarito_1: File
    - origem: string
    - criado_por: string
    - observacoes: string (opcional)
    - tracking_id: string
    - session_id: string
    - metadata: JSON string (opcional)
    - token: string (autenticação)
    """
    validar_token(authorization)

    from .utils.file_utils import normalize_filename, validate_file
    import json as json_mod

    # Parse multipart form data manualmente (campo dinâmicos)
    form = await request.form()

    # Extrair metadados
    origem = (form.get("origem") or "upload_manual")
    if hasattr(origem, 'file'):
        origem = await origem.read()
        origem = origem.decode() if isinstance(origem, bytes) else str(origem)
    else:
        origem = str(origem)

    criado_por = form.get("criado_por") or "anon"
    if hasattr(criado_por, 'file'):
        criado_por = await criado_por.read()
        criado_por = criado_por.decode() if isinstance(criado_por, bytes) else str(criado_por)
    else:
        criado_por = str(criado_por)

    observacoes = form.get("observacoes") or ""
    if hasattr(observacoes, 'file'):
        observacoes = await observacoes.read()
        observacoes = observacoes.decode() if isinstance(observacoes, bytes) else str(observacoes)
    else:
        observacoes = str(observacoes)

    tracking_id = form.get("tracking_id") or ""
    if hasattr(tracking_id, 'file'):
        tracking_id = await tracking_id.read()
        tracking_id = tracking_id.decode() if isinstance(tracking_id, bytes) else str(tracking_id)
    else:
        tracking_id = str(tracking_id)

    session_id = form.get("session_id") or ""
    if hasattr(session_id, 'file'):
        session_id = await session_id.read()
        session_id = session_id.decode() if isinstance(session_id, bytes) else str(session_id)
    else:
        session_id = str(session_id)

    # Ler listas de campos de arquivo (formato Lovable)
    provas_json = form.get("provas")
    gabaritos_json = form.get("gabaritos")

    prova_keys = []
    gabarito_keys = []

    if provas_json:
        if hasattr(provas_json, 'file'):
            raw = await provas_json.read()
            prova_keys = json_mod.loads(raw if isinstance(raw, (str, bytes)) else raw.decode())
        else:
            prova_keys = json_mod.loads(str(provas_json))

    if gabaritos_json:
        if hasattr(gabaritos_json, 'file'):
            raw = await gabaritos_json.read()
            gabarito_keys = json_mod.loads(raw if isinstance(raw, (str, bytes)) else raw.decode())
        else:
            gabarito_keys = json_mod.loads(str(gabaritos_json))

    pipeline = get_pipeline()
    lotes_dir = f"lotes/{tracking_id}" if tracking_id else f"lotes/manual_{criado_por}"
    arquivos_entrada = []

    # Processar provas (por chave dinâmica)
    for key in prova_keys:
        upload_file = form.get(key)
        if not upload_file or not hasattr(upload_file, 'filename'):
            continue

        filename = upload_file.filename or "prova.jpg"
        nome_normalizado = normalize_filename(filename)
        storage_path = f"{lotes_dir}/originais/{nome_normalizado}"
        content = await upload_file.read()

        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        validation = validate_file(tmp_path, filename)
        content_type = upload_file.content_type or "image/jpeg"
        pipeline.supabase.upload_arquivo(tmp_path, storage_path, content_type)
        os.unlink(tmp_path)

        arquivos_entrada.append({
            "nome_original": filename,
            "storage_path": storage_path,
            "tipo_hint": "prova",
            "validation": validation,
        })

    # Processar gabaritos (por chave dinâmica)
    for key in gabarito_keys:
        upload_file = form.get(key)
        if not upload_file or not hasattr(upload_file, 'filename'):
            continue

        filename = upload_file.filename or "gabarito.jpg"
        nome_normalizado = normalize_filename(filename)
        storage_path = f"{lotes_dir}/originais/{nome_normalizado}"
        content = await upload_file.read()

        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        validation = validate_file(tmp_path, filename)
        content_type = upload_file.content_type or "image/jpeg"
        pipeline.supabase.upload_arquivo(tmp_path, storage_path, content_type)
        os.unlink(tmp_path)

        arquivos_entrada.append({
            "nome_original": filename,
            "storage_path": storage_path,
            "tipo_hint": "gabarito",
            "validation": validation,
        })

    if not arquivos_entrada:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado")

    # Criar payload e processar
    import os as _os
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
