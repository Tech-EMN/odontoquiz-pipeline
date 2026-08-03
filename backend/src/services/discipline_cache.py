"""
Cache local de disciplinas e assuntos odontológicos.
Usado como fallback quando a API OdontoQuiz está indisponível.

Fonte: API OdontoQuiz (GET /referencias/disciplinas, /referencias/assuntos)
Última atualização: 2026-07-30
"""
import logging

logger = logging.getLogger(__name__)

# ─── Disciplinas (ID real da API OdontoQuiz) ────────────────────────────────
# ⚠️ Atualizar periodicamente via GET /referencias/disciplinas
DISCIPLINAS_FALLBACK = [
    {"id": 97, "nome": "Cirurgia Oral"},
    {"id": 50, "nome": "Dentística"},
    {"id": 53, "nome": "Endodontia"},
    {"id": 73, "nome": "Estomatologia"},
    {"id": 71, "nome": "Odontopediatria"},
    {"id": 72, "nome": "Ortodontia"},
    {"id": 74, "nome": "Periodontia"},
    {"id": 76, "nome": "Prótese Dentária"},
    {"id": 77, "nome": "Radiologia"},
    {"id": 80, "nome": "Saúde Coletiva"},
    {"id": 75, "nome": "Cirurgia Bucomaxilofacial"},
    {"id": 78, "nome": "Patologia Bucal"},
    {"id": 79, "nome": "Farmacologia"},
    {"id": 81, "nome": "Anestesiologia"},
    {"id": 82, "nome": "Implantodontia"},
]

# ─── Assuntos comuns por disciplina ─────────────────────────────────────────
ASSUNTOS_FALLBACK = [
    # Cirurgia Oral (97)
    {"id": 2680, "nome": "Exodontia", "disciplina_id": 97},
    {"id": 2681, "nome": "Complicações cirúrgicas", "disciplina_id": 97},
    {"id": 2682, "nome": "Cirurgia dos dentes inclusos", "disciplina_id": 97},
    # Dentística (50)
    {"id": 900, "nome": "Preparo cavitário", "disciplina_id": 50},
    {"id": 901, "nome": "Resinas compostas", "disciplina_id": 50},
    {"id": 902, "nome": "Amálgama", "disciplina_id": 50},
    {"id": 903, "nome": "Sistemas adesivos", "disciplina_id": 50},
    {"id": 904, "nome": "Clareamento dental", "disciplina_id": 50},
    # Endodontia (53)
    {"id": 1400, "nome": "Tratamento endodôntico", "disciplina_id": 53},
    {"id": 1401, "nome": "Instrumentação", "disciplina_id": 53},
    {"id": 1402, "nome": "Medicação intracanal", "disciplina_id": 53},
    # Periodontia (74)
    {"id": 1800, "nome": "Doença periodontal", "disciplina_id": 74},
    {"id": 1801, "nome": "Raspagem e alisamento radicular", "disciplina_id": 74},
    {"id": 1802, "nome": "Cirurgia periodontal", "disciplina_id": 74},
    # Cirurgia Bucomaxilofacial (75)
    {"id": 2600, "nome": "Trauma facial", "disciplina_id": 75},
    {"id": 2601, "nome": "Fraturas faciais", "disciplina_id": 75},
    {"id": 2602, "nome": "Classificação de Le Fort", "disciplina_id": 75},
    # Saúde Coletiva (80)
    {"id": 2200, "nome": "SUS", "disciplina_id": 80},
    {"id": 2201, "nome": "Epidemiologia", "disciplina_id": 80},
    {"id": 2202, "nome": "Biossegurança", "disciplina_id": 80},
    # Radiologia (77)
    {"id": 2400, "nome": "Técnicas radiográficas", "disciplina_id": 77},
    {"id": 2401, "nome": "Interpretação radiográfica", "disciplina_id": 77},
    # Prótese Dentária (76)
    {"id": 2800, "nome": "Prótese fixa", "disciplina_id": 76},
    {"id": 2801, "nome": "Prótese removível", "disciplina_id": 76},
    # Ortodontia (72)
    {"id": 3000, "nome": "Má oclusão", "disciplina_id": 72},
    {"id": 3001, "nome": "Aparelhos ortodônticos", "disciplina_id": 72},
    # Estomatologia (73)
    {"id": 3200, "nome": "Lesões bucais", "disciplina_id": 73},
    {"id": 3201, "nome": "Diagnóstico bucal", "disciplina_id": 73},
    # Odontopediatria (71)
    {"id": 3400, "nome": "Dentição decídua", "disciplina_id": 71},
    {"id": 3401, "nome": "Traumatismo dentário", "disciplina_id": 71},
    # Patologia Bucal (78)
    {"id": 3600, "nome": "Cistos odontogênicos", "disciplina_id": 78},
    {"id": 3601, "nome": "Tumores odontogênicos", "disciplina_id": 78},
    # Farmacologia (79)
    {"id": 3800, "nome": "Antibióticos", "disciplina_id": 79},
    {"id": 3801, "nome": "Analgésicos", "disciplina_id": 79},
    {"id": 3802, "nome": "Anestésicos locais", "disciplina_id": 79},
    # Implantodontia (82)
    {"id": 4000, "nome": "Osseointegração", "disciplina_id": 82},
    # Anestesiologia (81)
    {"id": 4200, "nome": "Técnicas anestésicas", "disciplina_id": 81},
]


def get_disciplinas_fallback() -> list[dict]:
    """Retorna lista de disciplinas do cache local."""
    return DISCIPLINAS_FALLBACK


def get_assuntos_fallback(disciplina_id: int = None) -> list[dict]:
    """Retorna assuntos do cache local, opcionalmente filtrados por disciplina."""
    if disciplina_id:
        return [a for a in ASSUNTOS_FALLBACK if a["disciplina_id"] == disciplina_id]
    return ASSUNTOS_FALLBACK


def cache_is_stale() -> bool:
    """
    Verifica se o cache local precisa ser atualizado.
    Deve ser executado periodicamente (ex: uma vez por semana).
    """
    return True  # Sempre reporta como stale até implementar timestamp
