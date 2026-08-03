"""
Cliente da API OdontoQuiz — consulta de referências e importação de questões.
Substitui os HTTP Requests do WF2 e WF3.
"""
import logging
from typing import Optional

import httpx

from ..core.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()


class OdontoQuizAPIError(Exception):
    """Erro na API do OdontoQuiz."""


class OdontoQuizAPIClient:
    """Cliente HTTP para a API REST do OdontoQuiz."""

    def __init__(self):
        self.base_url = _settings.odontoquiz_api_base_url.rstrip("/")
        self.api_key = _settings.odontoquiz_api_key
        self._headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict = None) -> dict | list:
        """GET request com tratamento de erro."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                headers=self._headers,
                params=params or {},
            )
            response.raise_for_status()
            return response.json()

    async def _post(self, path: str, data: dict) -> dict:
        """POST request com tratamento de erro."""
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}{path}",
                headers=self._headers,
                json=data,
            )
            response.raise_for_status()
            return response.json()

    # ─── Referências (leitura) ───────────────────────────────────────────

    async def listar_bancas(self) -> list[dict]:
        """Lista todas as bancas cadastradas."""
        return await self._get("/referencias/bancas")

    async def listar_instituicoes(self) -> list[dict]:
        """Lista todas as instituições cadastradas."""
        return await self._get("/referencias/instituicoes")

    async def listar_cargos(self) -> list[dict]:
        """Lista todos os cargos cadastrados."""
        return await self._get("/referencias/cargos")

    async def listar_disciplinas(self) -> list[dict]:
        """Lista todas as disciplinas cadastradas."""
        result = await self._get("/referencias/disciplinas")
        # Normaliza: a API pode retornar {data: [...]} ou array direto
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return result if isinstance(result, list) else []

    async def listar_assuntos(self, disciplina_id: int = None) -> list[dict]:
        """Lista assuntos (opcionalmente filtrados por disciplina)."""
        params = {}
        if disciplina_id:
            params["disciplina_id"] = disciplina_id
        result = await self._get("/referencias/assuntos", params=params)
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return result if isinstance(result, list) else []

    # ─── Criação de referências (WF3) ────────────────────────────────────

    async def criar_banca(self, nome: str) -> dict:
        """Cria uma nova banca."""
        return await self._post("/referencias/bancas", {"nome": nome})

    async def criar_instituicao(self, nome: str) -> dict:
        """Cria uma nova instituição."""
        return await self._post("/referencias/instituicoes", {"nome": nome})

    async def criar_cargo(self, nome: str) -> dict:
        """Cria um novo cargo."""
        return await self._post("/referencias/cargos", {"nome": nome})

    async def criar_assunto(self, nome: str, disciplina_id: int) -> dict:
        """Cria um novo assunto vinculado a uma disciplina."""
        return await self._post(
            "/referencias/assuntos",
            {"nome": nome, "disciplina_id": disciplina_id},
        )

    # ─── Importação ──────────────────────────────────────────────────────

    async def importar_questoes(self, payload: dict) -> dict:
        """
        Importa questões extraídas para o OdontoQuiz.
        Payload esperado:
        {
            "banca_id": int,
            "instituicao_id": int,
            "cargo_id": int,
            "ano": int,
            "questoes": [
                {
                    "numero": 1,
                    "enunciado": "...",
                    "alternativas": [{"letra": "A", "texto": "..."}, ...],
                    "gabarito": "A",
                    "disciplina_id": 74,
                    "assunto_id": 900
                }
            ]
        }
        """
        return await self._post("/questoes/importar", payload)


# Singleton
_odontoquiz_api: Optional[OdontoQuizAPIClient] = None


def get_odontoquiz_api() -> OdontoQuizAPIClient:
    global _odontoquiz_api
    if _odontoquiz_api is None:
        _odontoquiz_api = OdontoQuizAPIClient()
    return _odontoquiz_api
