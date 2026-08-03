"""
Fixtures de teste — payloads reais do handoff OdontoQuiz.
Cobre os cenários do pipeline: ingestão JSON, upload multipart, decisão portal.
"""
import pytest
import json

# ─── Payload: ingestao-materiais (WF4 JSON) ───────────────────────────────

@pytest.fixture
def payload_ingestao_minimo():
    """Payload mínimo: 1 prova + 1 gabarito."""
    return {
        "arquivos": [
            {
                "nome_original": "prova_cfo_2024.pdf",
                "storage_path": "lotes/test/originais/prova_cfo_2024.pdf",
                "tipo_hint": "prova",
            },
            {
                "nome_original": "gabarito_cfo_2024.pdf",
                "storage_path": "lotes/test/originais/gabarito_cfo_2024.pdf",
                "tipo_hint": "gabarito",
            },
        ],
        "metadados": {
            "origem": "test",
            "criado_por": "pytest",
        },
    }


@pytest.fixture
def payload_ingestao_completo():
    """Payload completo: múltiplas provas + metadados ricos."""
    return {
        "arquivos": [
            {
                "nome_original": "Prova Objetiva - CFO 2024 - CADERNO 1.pdf",
                "storage_path": "lotes/abc123/originais/cfo_2024_prova_c1.pdf",
                "tipo_hint": "prova",
            },
            {
                "nome_original": "Prova Objetiva - CFO 2024 - CADERNO 2.pdf",
                "storage_path": "lotes/abc123/originais/cfo_2024_prova_c2.pdf",
                "tipo_hint": "prova",
            },
            {
                "nome_original": "Gabarito Oficial CFO 2024.pdf",
                "storage_path": "lotes/abc123/originais/cfo_2024_gabarito.pdf",
                "tipo_hint": "gabarito",
            },
        ],
        "metadados": {
            "origem": "portal_odontoquiz",
            "criado_por": "ariana",
            "tracking_id": "abc123-def456",
            "session_id": "sessao-2026-08-03",
        },
    }


@pytest.fixture
def payload_ingestao_sem_gabarito():
    """Payload sem gabarito — deve lançar erro de validação."""
    return {
        "arquivos": [
            {
                "nome_original": "prova_solta.pdf",
                "storage_path": "lotes/test/prova_solta.pdf",
                "tipo_hint": "prova",
            },
        ],
        "metadados": {"origem": "test"},
    }


@pytest.fixture
def payload_ingestao_duplicado():
    """Payload com arquivo duplicado (mesmo hash)."""
    return {
        "arquivos": [
            {
                "nome_original": "prova_unica.pdf",
                "storage_path": "lotes/test/prova_unica.pdf",
                "tipo_hint": "prova",
            },
            {
                "nome_original": "prova_unica_copia.pdf",
                "storage_path": "lotes/test/prova_unica_copia.pdf",
                "tipo_hint": "prova",
            },
        ],
        "metadados": {"origem": "test", "criado_por": "pytest"},
    }


# ─── Payload: portal/decisao (WF3 JSON) ────────────────────────────────────

@pytest.fixture
def payload_decisao_aprovar():
    """Decisão de aprovação de todas as questões."""
    return {
        "decisoes": [
            {
                "questao_numero": 1,
                "acao": "aprovar",
                "disciplina_id": 42,
                "assunto_id": 101,
                "gabarito_resposta": "B",
            },
            {
                "questao_numero": 2,
                "acao": "aprovar",
                "disciplina_id": 42,
                "assunto_id": 102,
                "gabarito_resposta": "D",
            },
            {
                "questao_numero": 3,
                "acao": "aprovar",
                "disciplina_id": 43,
                "assunto_id": 201,
                "gabarito_resposta": "A",
            },
        ],
        "observacoes": "Todas as questões revisadas e aprovadas.",
    }


@pytest.fixture
def payload_decisao_rejeitar():
    """Decisão de rejeição (questão ilegível)."""
    return {
        "decisoes": [
            {
                "questao_numero": 5,
                "acao": "rejeitar",
                "motivo": "Questão com imagem cortada, enunciado ilegível.",
            },
        ],
        "observacoes": "Reenviar prova com melhor qualidade.",
    }


@pytest.fixture
def payload_decisao_corrigir():
    """Decisão de correção manual de disciplina/assunto."""
    return {
        "decisoes": [
            {
                "questao_numero": 1,
                "acao": "corrigir",
                "disciplina_id": 42,
                "assunto_id": 101,
                "gabarito_resposta": "C",
                "motivo": "Gabarito original estava errado (C, não B).",
            },
        ],
    }


# ─── Payload: ETAPA 2 (resultado OCR) ──────────────────────────────────────

@pytest.fixture
def payload_etapa2_resultado():
    """Resultado simulado da ETAPA 2 (GPT-4o extraiu questões)."""
    return {
        "arquivo_id": "prova-001",
        "questoes": [
            {
                "numero": 1,
                "enunciado": "Qual a principal causa da periodontite?",
                "texto_base": None,
                "comando": "Assinale a alternativa correta.",
                "alternativas": [
                    {"letra": "A", "texto": "Cárie dental"},
                    {"letra": "B", "texto": "Acúmulo de biofilme bacteriano"},
                    {"letra": "C", "texto": "Trauma oclusal"},
                    {"letra": "D", "texto": "Deficiência de vitamina C"},
                    {"letra": "E", "texto": "Bruxismo"},
                ],
                "confianca_extracao": 0.95,
            },
            {
                "numero": 2,
                "enunciado": "Em relação à anestesia em odontopediatria...",
                "alternativas": [
                    {"letra": "A", "texto": "Técnica de Gow-Gates"},
                    {"letra": "B", "texto": "Bloqueio do nervo alveolar inferior"},
                ],
                "confianca_extracao": 0.72,
            },
        ],
        "gabarito": {
            "respostas": {"1": "B", "2": "B"},
        },
        "disciplinas_sugeridas": [
            {"numero_questao": 1, "disciplina": "Periodontia", "assuntos": ["Etiologia"]},
            {"numero_questao": 2, "disciplina": "Odontopediatria", "assuntos": ["Anestesia"]},
        ],
    }


# ─── Fixture: cliente de teste FastAPI ───────────────────────────────────

@pytest.fixture
def client():
    """Cliente de teste para a API FastAPI."""
    from backend.src.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)
