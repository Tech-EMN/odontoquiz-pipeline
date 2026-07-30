"""
Cliente Supabase — unifica acesso ao banco e storage.
Substitui os HTTP Requests manuais do n8n por chamadas tipadas do SDK.
"""
from supabase import create_client, Client
from typing import Optional, Any
import logging

from ..core.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()


class SupabaseService:
    """Serviço central de acesso ao Supabase (DB + Storage)."""

    def __init__(self):
        if not _settings.supabase_url or not _settings.supabase_service_role_key:
            raise ValueError(
                "SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios. "
                "Configure no .env ou nas variáveis de ambiente."
            )
        self.client: Client = create_client(
            _settings.supabase_url,
            _settings.supabase_service_role_key,
        )
        self.bucket = _settings.supabase_storage_bucket or "odontoquiz"

    # ─── Storage ─────────────────────────────────────────────────────────

    def upload_arquivo(
        self, local_path: str, storage_path: str, content_type: str = "image/jpeg"
    ) -> dict:
        """Faz upload de um arquivo para o bucket do Supabase Storage."""
        with open(local_path, "rb") as f:
            result = self.client.storage.from_(self.bucket).upload(
                path=storage_path,
                file=f,
                file_options={"content-type": content_type},
            )
        # Retorna o path público
        public_url = self.client.storage.from_(self.bucket).get_public_url(storage_path)
        return {"path": storage_path, "url": public_url, "result": result}

    def download_arquivo(self, storage_path: str, local_path: str) -> str:
        """Baixa um arquivo do Supabase Storage para o disco local."""
        with open(local_path, "wb") as f:
            result = self.client.storage.from_(self.bucket).download(storage_path)
            f.write(result)
        return local_path

    def get_public_url(self, storage_path: str) -> str:
        """Retorna a URL pública de um arquivo no storage."""
        return self.client.storage.from_(self.bucket).get_public_url(storage_path)

    # ─── Lotes ───────────────────────────────────────────────────────────

    def criar_lote(self, dados: dict) -> dict:
        """Insere um novo lote na tabela 'lotes'."""
        result = self.client.table("lotes").insert(dados).execute()
        return result.data[0] if result.data else {}

    def atualizar_lote(self, lote_id: str, dados: dict) -> dict:
        """Atualiza um lote existente."""
        result = self.client.table("lotes").update(dados).eq("id", lote_id).execute()
        return result.data[0] if result.data else {}

    def buscar_lote(self, lote_id: str) -> Optional[dict]:
        """Busca um lote pelo ID."""
        result = self.client.table("lotes").select("*").eq("id", lote_id).execute()
        return result.data[0] if result.data else None

    # ─── Arquivos ────────────────────────────────────────────────────────

    def inserir_arquivo(self, dados: dict) -> dict:
        """Insere um novo registro de arquivo na tabela 'arquivos'."""
        result = self.client.table("arquivos").insert(dados).execute()
        return result.data[0] if result.data else {}

    def atualizar_arquivo(self, arquivo_id: str, dados: dict) -> dict:
        """Atualiza um registro de arquivo."""
        result = (
            self.client.table("arquivos").update(dados).eq("id", arquivo_id).execute()
        )
        return result.data[0] if result.data else {}

    def buscar_arquivo(self, arquivo_id: str) -> Optional[dict]:
        """Busca um arquivo pelo ID."""
        result = (
            self.client.table("arquivos").select("*").eq("id", arquivo_id).execute()
        )
        return result.data[0] if result.data else None

    def buscar_arquivo_por_hash(self, hash_arquivo: str) -> Optional[dict]:
        """Verifica se um arquivo já existe pelo hash."""
        result = (
            self.client.table("arquivos")
            .select("*")
            .eq("hash_arquivo", hash_arquivo)
            .execute()
        )
        return result.data[0] if result.data else None

    def listar_arquivos_lote(self, lote_id: str) -> list[dict]:
        """Lista todos os arquivos de um lote."""
        result = (
            self.client.table("arquivos")
            .select("*")
            .eq("lote_id", lote_id)
            .execute()
        )
        return result.data or []

    def buscar_candidatos_pareamento(self, lote_id: str, tipo_oposto: str) -> list[dict]:
        """
        Busca arquivos do tipo oposto no mesmo lote para pareamento.
        Ex: se é prova, busca gabaritos; se é gabarito, busca provas.
        """
        result = (
            self.client.table("arquivos")
            .select("*")
            .eq("lote_id", lote_id)
            .eq("tipo_arquivo_inicial", tipo_oposto)
            .eq("status", "classificado")
            .execute()
        )
        return result.data or []

    # ─── Pares ───────────────────────────────────────────────────────────

    def criar_par(self, dados: dict) -> dict:
        """Insere um novo par prova+gabarito na tabela 'pares_arquivos'."""
        result = self.client.table("pares_arquivos").insert(dados).execute()
        return result.data[0] if result.data else {}

    def atualizar_par(self, par_id: str, dados: dict) -> dict:
        """Atualiza um par existente."""
        result = self.client.table("pares_arquivos").update(dados).eq("id", par_id).execute()
        return result.data[0] if result.data else {}

    def listar_pares_lote(self, lote_id: str) -> list[dict]:
        """Lista todos os pares de um lote."""
        result = (
            self.client.table("pares_arquivos").select("*").eq("lote_id", lote_id).execute()
        )
        return result.data or []

    # ─── Progresso ───────────────────────────────────────────────────────

    def notificar_progresso(self, lote_id: str, etapa: str, status: str, detalhes: dict = None) -> None:
        """
        Notifica progresso via atualização do status do lote.
        A tabela 'progresso' não existe neste schema — usa atualização
        de status no próprio lote + log como fallback.
        """
        try:
            self.atualizar_lote(lote_id, {
                "status": f"{etapa}_{status}",
                "metadata": {"etapa": etapa, "status": status, "detalhes": detalhes or {}},
            })
        except Exception as e:
            logger.warning(f"Falha ao notificar progresso: {e}")


# Singleton
_supabase: Optional[SupabaseService] = None


def get_supabase() -> SupabaseService:
    global _supabase
    if _supabase is None:
        _supabase = SupabaseService()
    return _supabase
