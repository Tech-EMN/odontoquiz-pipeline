"""
Task Celery para processamento de decisões do portal (F6).
"""
import logging
from .celery_app import celery_app
from ..core.pipeline import OdontoQuizPipeline

logger = logging.getLogger("odontoquiz.worker")


@celery_app.task(bind=True, name="odontoquiz.processar_decisao")
def processar_decisao_task(self, decisao_data: dict):
    """
    Processa uma decisão humana do portal de forma assíncrona.

    Args:
        decisao_data: Dict com dados da decisão (DecisaoHumana)

    Returns:
        dict com resultado do processamento
    """
    from ..models.schemas import DecisaoHumana

    decisao = DecisaoHumana(**decisao_data)
    logger.info(f"[CELERY] Processando decisão do arquivo {decisao.arquivo_id}")

    try:
        import asyncio
        pipeline = OdontoQuizPipeline()
        resultado = asyncio.run(pipeline.processar_decisao(decisao))
        return resultado
    except Exception as e:
        logger.error(f"[CELERY] Erro na decisão: {e}")
        return {"arquivo_id": decisao.arquivo_id, "status": "erro", "erro": str(e)}
