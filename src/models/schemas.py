"""
Modelos Pydantic para o pipeline OdontoQuiz
"""
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import Enum


# ─── Enums ───────────────────────────────────────────────────────────────────

class TipoDocumento(str, Enum):
    PROVA = "prova"
    GABARITO = "gabarito"
    INDEFINIDO = "indefinido"

class StatusArquivo(str, Enum):
    PENDENTE = "pendente"
    PROCESSANDO = "processando"
    CLASSIFICADO = "classificado"
    PARES_FORMADOS = "pares_formados"
    EXTRAIDO = "extraido"
    REVISAO = "revisao"
    IMPORTADO = "importado"
    RECUSADO = "recusado"
    ERRO = "erro"

class DecisaoFluxo(str, Enum):
    ENTREGA_DIRETA = "entrega_direta"
    ENTREGA_PAYLOAD = "entrega_payload"
    REVISAO_HUMANA = "revisao_humana"
    ERRO = "erro"

class AcaoReferencia(str, Enum):
    USAR_EXISTENTE = "usar_existente"
    CRIAR_NOVO = "criar_novo"
    REVISAO = "revisao"

class StatusPar(str, Enum):
    PENDENTE = "pendente"
    PAREADO = "pareado"
    REVISAO_MANUAL = "revisao_manual"
    PROCESSADO = "processado"


# ─── Entrada Webhook ─────────────────────────────────────────────────────────

class ArquivoEntrada(BaseModel):
    nome_original: str
    storage_path: str
    storage_bucket: Optional[str] = None
    tipo_hint: Optional[TipoDocumento] = None

class PayloadIngestao(BaseModel):
    lote_id: Optional[str] = None
    arquivos: list[ArquivoEntrada]
    metadados: Optional[dict[str, Any]] = None


# ─── OCR Leve (WF1) ──────────────────────────────────────────────────────────

class MetadadosDocumento(BaseModel):
    titulo_documento: Optional[str] = None
    orgao: Optional[str] = None
    concurso: Optional[str] = None
    cargo: Optional[str] = None
    codigo_prova: Optional[str] = None
    ano: Optional[int] = None
    caderno: Optional[str] = None
    versao: Optional[str] = None
    tipo_detectado: TipoDocumento = TipoDocumento.INDEFINIDO
    confianca_identificacao: float = 0.0
    blocos_gabarito: list[dict[str, str]] = Field(default_factory=list)
    texto_base: Optional[str] = None
    trecho_relevante: Optional[str] = None
    justificativa: Optional[str] = None
    fonte_metadados: Optional[str] = None
    erro_ocr_imagem: bool = False
    mensagem: Optional[str] = None


# ─── ETAPA 2 OCR (WF2) ──────────────────────────────────────────────────────

class Alternativa(BaseModel):
    letra: Optional[str] = None
    texto: Optional[str] = None
    ilegivel: bool = False

class QuestaoExtraida(BaseModel):
    numero: Optional[int] = None
    enunciado: Optional[str] = None
    texto_base: Optional[str] = None
    comando: Optional[str] = None
    alternativas: list[Alternativa] = Field(default_factory=list)
    confianca_extracao: float = 0.0

class GabaritoExtraido(BaseModel):
    respostas: dict[str, str] = Field(default_factory=dict)  # {"1": "A", "2": "B", ...}

class ReferenciaDisciplina(BaseModel):
    acao: AcaoReferencia = AcaoReferencia.USAR_EXISTENTE
    id: Optional[int] = None
    nome: str = ""
    confianca: float = 0.0
    opcoes: list[dict] = Field(default_factory=list)
    motivo: Optional[str] = None

class ReferenciaAssunto(BaseModel):
    acao: AcaoReferencia = AcaoReferencia.USAR_EXISTENTE
    id: Optional[int] = None
    nome: str = ""
    disciplina_id: Optional[int] = None
    confianca: float = 0.0
    motivo: Optional[str] = None

class ValidacaoReferencias(BaseModel):
    referencias_por_questao: list[dict] = Field(default_factory=list)
    status: str = "pendente"

class PayloadETAPA2(BaseModel):
    """Output completo da ETAPA 2 OCR"""
    arquivo_id: str = ""
    questoes: list[QuestaoExtraida] = Field(default_factory=list)
    gabarito: Optional[GabaritoExtraido] = None
    disciplinas_por_questao: dict[str, list[int]] = Field(default_factory=dict)  # {"1": [104]}
    assuntos_por_questao: dict[str, list[int]] = Field(default_factory=dict)     # {"1": [2686]}
    validacao: ValidacaoReferencias = Field(default_factory=ValidacaoReferencias)
    decisao_fluxo: DecisaoFluxo = DecisaoFluxo.REVISAO_HUMANA
    motivos_revisao: list[str] = Field(default_factory=list)
    precisa_revisao_humana: bool = False
    erro_validacao_referencias: bool = False
    metadados: Optional[MetadadosDocumento] = None


# ─── Portal / Decisão (WF3) ──────────────────────────────────────────────────

class DecisaoHumana(BaseModel):
    arquivo_id: str
    banca_id: Optional[int] = None
    instituicao_id: Optional[int] = None
    cargo_id: Optional[int] = None
    ano: Optional[int] = None
    questoes: list[dict[str, Any]] = Field(default_factory=list)
    recusar: bool = False
    motivo_recusa: Optional[str] = None

class PayloadDecisao(BaseModel):
    decisoes: list[DecisaoHumana] = Field(default_factory=list)


# ─── API Responses ───────────────────────────────────────────────────────────

class IngestaoResponse(BaseModel):
    status: str
    lote_id: str
    arquivos_recebidos: int
    mensagem: str

class StatusResponse(BaseModel):
    lote_id: str
    status: StatusArquivo
    arquivos: list[dict[str, Any]] = Field(default_factory=list)
    pares: list[dict[str, Any]] = Field(default_factory=list)
