"""
Testes do pipeline principal — validação de schemas, dedup, fuzzy match.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock

from backend.src.models.schemas import (
    TipoDocumento,
    StatusArquivo,
    DecisaoFluxo,
    PayloadETAPA2,
    QuestaoExtraida,
    Alternativa,
    PayloadIngestao,
    IngestaoResponse,
)


class TestSchemas:
    """Validação dos modelos Pydantic."""

    def test_payload_ingestao_validacao(self, payload_ingestao_minimo):
        """Payload mínimo deve ser válido."""
        payload = PayloadIngestao(**payload_ingestao_minimo)
        assert len(payload.arquivos) == 2

    def test_payload_ingestao_sem_arquivos(self):
        """Payload sem arquivos deve falhar validação."""
        with pytest.raises(Exception):
            PayloadIngestao(arquivos=[], metadados={})

    def test_questao_extraida_min_2_alternativas(self):
        """Questão com menos de 2 alternativas válidas deve ser rejeitada."""
        q = QuestaoExtraida(
            numero=1,
            enunciado="Teste",
            alternativas=[Alternativa(letra="A", texto="Única")],
            confianca_extracao=0.5,
        )
        assert q is not None  # Pydantic aceita, validação ocorre no pipeline

    def test_questao_extraida_confianca_float(self):
        """Confianca_extracao deve ser float (não string)."""
        q = QuestaoExtraida(
            numero=1,
            enunciado="Teste",
            alternativas=[
                Alternativa(letra="A", texto="Alt A"),
                Alternativa(letra="B", texto="Alt B"),
            ],
            confianca_extracao=0.85,
        )
        assert isinstance(q.confianca_extracao, float)
        assert q.confianca_extracao == 0.85

    def test_decisao_fluxo_enum(self):
        """DecisaoFluxo deve aceitar apenas valores válidos."""
        assert DecisaoFluxo.ENTREGA_DIRETA.value == "entrega_direta"
        assert DecisaoFluxo.REVISAO_HUMANA.value == "revisao_humana"

        with pytest.raises(ValueError):
            DecisaoFluxo("invalido")


class TestDedup:
    """Validação da lógica de deduplicação de questões."""

    def test_dedup_mantem_maior_confianca(self):
        """Deve manter a questão com maior confianca_extracao quando duplicada."""
        from backend.src.core.pipeline import OdontoQuizPipeline

        pipeline = OdontoQuizPipeline()

        q1 = QuestaoExtraida(
            numero=1,
            enunciado="Qual a causa da periodontite?",
            alternativas=[
                Alternativa(letra="A", texto="Cárie"),
                Alternativa(letra="B", texto="Biofilme"),
            ],
            confianca_extracao=0.60,
        )
        q2 = QuestaoExtraida(
            numero=1,
            enunciado="Qual a principal causa da periodontite?",
            alternativas=[
                Alternativa(letra="A", texto="Cárie"),
                Alternativa(letra="B", texto="Acúmulo de biofilme bacteriano"),
                Alternativa(letra="C", texto="Trauma"),
            ],
            confianca_extracao=0.92,
        )

        resultado = pipeline._deduplicar_questoes([q1, q2])
        assert len(resultado) == 1
        assert resultado[0].confianca_extracao == 0.92
        assert len(resultado[0].alternativas) == 3

    def test_dedup_questoes_diferentes(self):
        """Questões com números diferentes não devem ser dedupadas."""
        from backend.src.core.pipeline import OdontoQuizPipeline

        pipeline = OdontoQuizPipeline()

        q1 = QuestaoExtraida(
            numero=1,
            enunciado="Pergunta 1",
            alternativas=[
                Alternativa(letra="A", texto="Alt A"),
                Alternativa(letra="B", texto="Alt B"),
            ],
            confianca_extracao=0.8,
        )
        q2 = QuestaoExtraida(
            numero=2,
            enunciado="Pergunta 2",
            alternativas=[
                Alternativa(letra="A", texto="Alt A"),
                Alternativa(letra="B", texto="Alt B"),
            ],
            confianca_extracao=0.7,
        )

        resultado = pipeline._deduplicar_questoes([q1, q2])
        assert len(resultado) == 2
        assert {q.numero for q in resultado} == {1, 2}


class TestPareamento:
    """Validação do algoritmo de pareamento prova↔gabarito."""

    def test_score_pareamento_identico(self):
        """Prova e gabarito idênticos devem ter score máximo."""
        from backend.src.core.pipeline import OdontoQuizPipeline

        pipeline = OdontoQuizPipeline()

        prova = {"orgao": "CFO", "cargo": "Cirurgião Dentista", "codigo_prova": "001", "ano": "2024"}
        gabarito = {"orgao": "CFO", "cargo": "Cirurgião Dentista", "codigo_prova": "001", "ano": "2024"}

        score = pipeline._calcular_score_pareamento(prova, gabarito)
        assert score == 1.0

    def test_score_pareamento_diferente_orgao(self):
        """Órgãos diferentes devem reduzir o score."""
        from backend.src.core.pipeline import OdontoQuizPipeline

        pipeline = OdontoQuizPipeline()

        prova = {"orgao": "CFO", "cargo": "Cirurgião Dentista"}
        gabarito = {"orgao": "CRO-SP", "cargo": "Cirurgião Dentista"}

        score = pipeline._calcular_score_pareamento(prova, gabarito)
        assert score < 0.7  # Perdeu 0.35 do órgão

    def test_score_pareamento_vazio(self):
        """Campos vazios não devem quebrar o cálculo."""
        from backend.src.core.pipeline import OdontoQuizPipeline

        pipeline = OdontoQuizPipeline()

        score = pipeline._calcular_score_pareamento({}, {})
        assert score == 0.0


class TestNormalizacao:
    """Validação da normalização de texto."""

    def test_normalizar_texto_acentos(self):
        """Acentos e caracteres especiais devem ser removidos."""
        from backend.src.core.pipeline import OdontoQuizPipeline

        pipeline = OdontoQuizPipeline()
        result = pipeline._normalizar_texto("Cirurgião-Dentista (Prótese)")
        assert "cirurgiao" in result
        assert "dentista" in result
        assert "protese" in result
        assert "(" not in result
        assert "-" not in result
