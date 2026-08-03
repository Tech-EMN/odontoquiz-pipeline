"""
Celery tasks — processamento assíncrono do pipeline OdontoQuiz.

Substitui `asyncio.create_task(self._processar_lote(...))` do main.py.
Retorna resultado JSON-serializável para o backend (Redis).
"""
import logging
from .celery_app import celery_app
from ..core.pipeline import OdontoQuizPipeline

logger = logging.getLogger("odontoquiz.worker")


@celery_app.task(bind=True, name="odontoquiz.processar_lote")
def processar_lote_task(self, lote_id: str, arquivos: list[dict]):
    """
    Processa um lote completo de forma assíncrona.

    Args:
        lote_id: UUID do lote no Supabase
        arquivos: Lista de dicts com metadados de cada arquivo

    Returns:
        dict com status do processamento
    """
    logger.info(f"[CELERY] Iniciando processamento do lote {lote_id} ({len(arquivos)} arquivos)")

    try:
        pipeline = OdontoQuizPipeline()
        pipeline.supabase.notificar_progresso(lote_id, "celery", "worker_iniciado")

        # --- Fase 1: OCR Leve ---
        pipeline.supabase.atualizar_lote(lote_id, {"status": "processando"})
        resultados_ocr = []

        for i, arquivo in enumerate(arquivos):
            self.update_state(
                state="PROGRESS",
                meta={"lote_id": lote_id, "fase": "ocr_leve", "progresso": f"{i+1}/{len(arquivos)}"},
            )

            pipeline.supabase.atualizar_arquivo(arquivo["id"], {"status": "processando"})

            try:
                import asyncio
                resultado = asyncio.run(pipeline._ocr_leve(arquivo))
                resultados_ocr.append(resultado)
                pipeline.supabase.atualizar_arquivo(
                    arquivo["id"],
                    {
                        "status": "classificado",
                        "tipo_arquivo_inicial": resultado.get("tipo_detectado"),
                        "metadata": resultado,
                    },
                )
            except Exception as e:
                logger.error(f"[CELERY] Erro OCR Leve no arquivo {arquivo['id']}: {e}")
                pipeline.supabase.atualizar_arquivo(
                    arquivo["id"],
                    {"status": "erro", "observacoes": str(e)},
                )

        self.update_state(state="PROGRESS", meta={"lote_id": lote_id, "fase": "pareamento"})

        # --- Fase 2: Pareamento ---
        import asyncio
        pares = asyncio.run(pipeline._parear_arquivos(lote_id, resultados_ocr))
        pipeline.supabase.notificar_progresso(lote_id, "pareamento", "concluido", {"pares": len(pares)})

        # --- Fase 3: ETAPA 2 OCR ---
        for i, par in enumerate(pares):
            self.update_state(
                state="PROGRESS",
                meta={"lote_id": lote_id, "fase": "etapa2", "progresso": f"{i+1}/{len(pares)}"},
            )
            try:
                asyncio.run(pipeline._etapa2_ocr(par))
            except Exception as e:
                logger.error(f"[CELERY] Erro ETAPA 2 no par {par['id']}: {e}")

        # --- Finalização ---
        pipeline.supabase.atualizar_lote(lote_id, {"status": "concluido"})
        pipeline.supabase.notificar_progresso(lote_id, "pipeline", "concluido")

        return {
            "status": "concluido",
            "lote_id": lote_id,
            "total_arquivos": len(arquivos),
            "total_pares": len(pares),
            "total_questoes": 0,  # Seria preenchido com soma real
        }

    except Exception as e:
        logger.exception(f"[CELERY] Erro fatal no lote {lote_id}: {e}")
        pipeline = OdontoQuizPipeline()
        pipeline.supabase.atualizar_lote(lote_id, {"status": "erro", "observacoes": str(e)})
        return {"status": "erro", "lote_id": lote_id, "erro": str(e)}


@celery_app.task(bind=True, name="odontoquiz.health_check")
def health_check_task(self):
    """Task simples para verificar health do worker."""
    return {"status": "ok", "worker": self.request.hostname}
