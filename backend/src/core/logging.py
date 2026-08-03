"""
Observability — structlog + trace_id por lote (F4).
Substitui logging padrão por JSON estruturado com trace_id.
"""
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Optional

import structlog

# ─── Context variables (thread-safe) ────────────────────────────────────────

trace_id_ctx: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
lote_id_ctx: ContextVar[Optional[str]] = ContextVar("lote_id", default=None)


def get_trace_id() -> str:
    """Retorna o trace_id atual ou gera um novo."""
    tid = trace_id_ctx.get()
    if tid is None:
        tid = str(uuid.uuid4())[:12]
        trace_id_ctx.set(tid)
    return tid


def set_trace_id(trace_id: str) -> None:
    """Define o trace_id do contexto atual."""
    trace_id_ctx.set(trace_id)


def set_lote_id(lote_id: str) -> None:
    """Define o lote_id do contexto atual."""
    lote_id_ctx.set(lote_id)


def clear_context() -> None:
    """Limpa o contexto (útil em workers)."""
    trace_id_ctx.set(None)
    lote_id_ctx.set(None)


# ─── Processors ──────────────────────────────────────────────────────────────

def _add_trace_id(logger, method_name, event_dict):
    """Adiciona trace_id e lote_id a todos os logs."""
    tid = trace_id_ctx.get()
    if tid:
        event_dict["trace_id"] = tid
    lid = lote_id_ctx.get()
    if lid:
        event_dict["lote_id"] = lid
    return event_dict


# ─── Setup ───────────────────────────────────────────────────────────────────

def setup_logging(
    log_level: str = "INFO",
    json_output: bool = True,
) -> None:
    """
    Configura structlog como logger padrão do projeto.

    Args:
        log_level: Nível de log (DEBUG, INFO, WARNING, ERROR)
        json_output: True = JSON para produção, False = console colorido
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            _add_trace_id,
            renderer,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configurar root logger para structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )


def get_logger(name: str = "odontoquiz") -> structlog.stdlib.BoundLogger:
    """Retorna um logger structlog configurado."""
    return structlog.get_logger(name)
