"""
Cliente OpenAI — análise de imagens com GPT-4o e extração de texto.
Substitui os nós 'Analyze image' + 'OpenAI Chat Model' do n8n.
"""
import base64
import logging
from typing import Optional

from openai import AsyncOpenAI

from ..core.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()

# ─── Prompts (extraídos dos workflows n8n) ────────────────────────────────────

PROMPT_OCR_LEVE_GABARITO = """Você é um especialista em OCR de documentos de concurso público odontológico.

Analise esta imagem e classifique o documento. Retorne APENAS um JSON válido, sem markdown.

{{
  "tipo_arquivo": "gabarito" | "prova" | "indefinido",
  "titulo_documento": "Nome/título do documento identificado",
  "orgao": "Órgão organizador (ex: Prefeitura Municipal de X)",
  "concurso": "Nome do concurso",
  "cargo": "Cargo do concurso",
  "codigo_prova": "Código identificador (se houver)",
  "ano": 2024,
  "caderno": "Tipo de caderno (se houver)",
  "versao": "Versão (se houver)",
  "confianca_identificacao": 0.85,
  "trecho_relevante": "Trecho do documento que fundamenta a classificação",
  "justificativa": "Por que classificou assim?",
  "blocos_gabarito": [
    {{"codigo_prova": "01", "cargo": "Cirurgião Dentista"}}
  ]
}}

REGRAS:
- tipo_arquivo "gabarito": lista/tabela oficial de respostas (A,B,C,D,E) sem enunciados de questões
- tipo_arquivo "prova": caderno com questões numeradas e alternativas
- tipo_arquivo "indefinido": não foi possível determinar
- Confiança entre 0.0 e 1.0"""

PROMPT_ETAPA2_PROVA = """Você é um especialista em OCR e extração de questões de concurso público odontológico.

CONTEXTO DO PACOTE:
- Nome do arquivo: {nome_original}
- Tipo esperado: {tipo_esperado}
- Posição no pacote: {ordem_arquivo} de {total_arquivos}
- ID do gabarito oficial: {arquivo_gabarito_id}
- IDs das provas: {arquivos_prova_ids}

OBJETIVO:
Analise a imagem e:
1. Classifique o documento (prova/gabarito/indefinido)
2. Extraia TODAS as questões e alternativas (se for prova)
3. Extraia TODAS as respostas (se for gabarito)
4. Extraia metadados (órgão, cargo, concurso, banca, ano)

FORMATO DA RESPOSTA — APENAS JSON, sem markdown:

{{
  "tipo_arquivo": "prova",
  "orgao": "Nome do órgão",
  "cargo": "Nome do cargo",
  "concurso": "Nome do concurso",
  "banca": "Nome da banca",
  "ano": 2024,
  "questoes": [
    {{
      "numero": 1,
      "enunciado": "Texto completo do enunciado...",
      "texto_base": "Texto de apoio/caso clínico (se houver)",
      "comando": "Comando da questão (ex: Assinale a alternativa correta)",
      "alternativas": [
        {{"letra": "A", "texto": "Texto da alternativa A", "ilegivel": false}},
        {{"letra": "B", "texto": "Texto da alternativa B", "ilegivel": false}}
      ],
      "confianca_extracao": 0.9
    }}
  ],
  "gabarito": {{
    "respostas": {{"1": "A", "2": "B"}}
  }},
  "disciplina_sugerida": "Nome da disciplina principal",
  "disciplinas_sugeridas": [
    {{
      "numero_questao": 1,
      "disciplina": "Dentística",
      "assuntos": ["Preparo cavitário", "Resinas compostas"],
      "confianca": 0.85
    }}
  ],
  "confianca_extracao": 0.85
}}

REGRAS IMPORTANTES:
- Se for GABARITO: inclua APENAS o campo "gabarito" com as respostas (sem questões)
- Se for PROVA: inclua APENAS o campo "questoes" com TODAS as questões visíveis
- alternativa.ilegivel = true quando o texto estiver borrado/cortado
- confianca_extracao entre 0.0 e 1.0
- Se houver continuação de prova (ex: "continuação da prova tipo X"), indique no campo apropriado"""

PROMPT_VALIDACAO_REFERENCIAS = """Você é um especialista em classificação de disciplinas e assuntos odontológicos para concursos públicos.

DISCIPLINAS DISPONÍVEIS:
{disciplinas_json}

ASSUNTOS DISPONÍVEIS POR DISCIPLINA:
{assuntos_json}

QUESTÕES EXTRAÍDAS:
{questoes_json}

Para cada questão, sugira a disciplina e os assuntos mais adequados.

RETORNE APENAS JSON:
{{
  "validacao_referencias": {{
    "referencias_por_questao": [
      {{
        "numero": 1,
        "disciplina": {{
          "acao": "usar_existente" | "criar_novo",
          "id": 74,
          "nome": "Periodontia",
          "confianca": 0.9,
          "opcoes": [{{"id": 74, "nome": "Periodontia"}}, {{"id": 53, "nome": "Endodontia"}}],
          "motivo": null
        }},
        "assuntos": [
          {{
            "acao": "usar_existente" | "criar_novo",
            "id": 900,
            "nome": "Doença periodontal",
            "disciplina_id": 74,
            "confianca": 0.85
          }}
        ]
      }}
    ]
  }}
}}"""


class OpenAIService:
    """Serviço de análise de imagens e extração com OpenAI GPT-4o."""

    def __init__(self):
        if not _settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY é obrigatória. Configure no .env ou nas variáveis de ambiente."
            )
        self.client = AsyncOpenAI(api_key=_settings.openai_api_key)
        self.model = _settings.openai_model

    def _encode_image(self, image_path: str) -> str:
        """Codifica uma imagem local em base64 para envio à API."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    async def analyze_image(
        self,
        image_path: str,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 4000,
    ) -> dict:
        """
        Analisa uma imagem com GPT-4o e retorna o JSON parseado.
        Levanta ValueError se a API retornar erro.
        """
        image_b64 = self._encode_image(image_path)

        try:
            response = await self.client.chat.completions.create(
                model=model or self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                ],
                max_tokens=max_tokens,
                temperature=0.2,
            )

            raw_text = response.choices[0].message.content or ""

            # Parse do JSON usando parseJsonSeguro (com contador de profundidade)
            return self._parse_json_seguro(raw_text)

        except Exception as e:
            logger.error(f"Erro na análise de imagem: {e}")
            raise ValueError(f"Falha na análise de imagem: {str(e)}")

    async def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 4000,
    ) -> dict:
        """Chat completion textual com GPT-4o."""
        try:
            response = await self.client.chat.completions.create(
                model=model or self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.3,
            )

            raw_text = response.choices[0].message.content or ""
            return self._parse_json_seguro(raw_text)

        except Exception as e:
            logger.error(f"Erro no chat completion: {e}")
            raise ValueError(f"Falha no chat completion: {str(e)}")

    def _parse_json_seguro(self, texto: str) -> dict:
        """
        parseJsonSeguro() com contador de profundidade.
        Substitui o regex greedy por loop com contador de chaves.
        """
        bruto = str(texto or "").strip()
        if not bruto:
            return {}

        # Tenta parse direto
        try:
            import json
            return json.loads(bruto)
        except json.JSONDecodeError:
            pass

        # Remove markdown code fences
        sem_markdown = bruto
        import re
        sem_markdown = re.sub(r'^```json\s*', '', sem_markdown, flags=re.IGNORECASE)
        sem_markdown = re.sub(r'^```\s*', '', sem_markdown, flags=re.IGNORECASE)
        sem_markdown = re.sub(r'```$', '', sem_markdown)
        sem_markdown = sem_markdown.strip()

        # Tenta parse após limpeza
        try:
            return json.loads(sem_markdown)
        except json.JSONDecodeError:
            pass

        # Contador de profundidade (CORREÇÃO #6)
        depth = 0
        start = -1

        for i, ch in enumerate(sem_markdown):
            if ch == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        parsed = json.loads(sem_markdown[start:i + 1])
                        if parsed and isinstance(parsed, dict) and len(parsed) >= 2:
                            return parsed
                    except json.JSONDecodeError:
                        pass
                    start = -1

        # Último recurso: array
        array_match = re.search(r'\[[\s\S]*\]', sem_markdown)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"parseJsonSeguro: não foi possível extrair JSON de: {texto[:200]}...")
        return {}

    # ─── OCR Leve (WF1) ──────────────────────────────────────────────────

    async def classificar_documento(
        self, image_path: str, tipo_hint: str = "indefinido"
    ) -> dict:
        """
        Classifica um documento como prova/gabarito/indefinido.
        Equivalente ao WF1: OCR Leve - Identificação de Documento.
        """
        prompt = PROMPT_OCR_LEVE_GABARITO

        if tipo_hint == "gabarito":
            prompt += "\n\nATENÇÃO: Este arquivo foi enviado como GABARITO. Priorize a detecção de respostas."
        elif tipo_hint == "prova":
            prompt += "\n\nATENÇÃO: Este arquivo foi enviado como PROVA. Priorize a detecção de questões e alternativas."

        return await self.analyze_image(image_path, prompt)

    # ─── ETAPA 2 OCR (WF2) ───────────────────────────────────────────────

    async def extrair_questoes_gabarito(
        self,
        image_path: str,
        contexto: dict,
    ) -> dict:
        """
        Extrai questões, gabarito e metadados de uma imagem.
        Equivalente ao WF2: ETAPA 2 OCR.
        """
        prompt = PROMPT_ETAPA2_PROVA.format(
            nome_original=contexto.get("nome_original", "arquivo_sem_nome"),
            tipo_esperado=contexto.get("tipo_esperado", "indefinido"),
            ordem_arquivo=contexto.get("ordem_arquivo", "?"),
            total_arquivos=contexto.get("total_arquivos", "?"),
            arquivo_gabarito_id=contexto.get("arquivo_gabarito_id", ""),
            arquivos_prova_ids=contexto.get("arquivos_prova_ids", []),
        )

        return await self.analyze_image(image_path, prompt, max_tokens=4000)

    async def validar_referencias(
        self,
        questoes: list[dict],
        disciplinas: list[dict],
        assuntos: list[dict],
    ) -> dict:
        """
        Valida disciplinas e assuntos sugeridos contra a base de referências.
        """
        prompt = PROMPT_VALIDACAO_REFERENCIAS.format(
            disciplinas_json=str(disciplinas),
            assuntos_json=str(assuntos),
            questoes_json=str(questoes),
        )

        return await self.chat_completion(
            system_prompt="Você é um especialista em classificação odontológica.",
            user_prompt=prompt,
        )


# Singleton
_openai: Optional[OpenAIService] = None


def get_openai() -> OpenAIService:
    global _openai
    if _openai is None:
        _openai = OpenAIService()
    return _openai
