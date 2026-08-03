"""
Pipeline principal — orquestra todas as etapas do processamento OdontoQuiz.
Substitui os 4 workflows n8n (WF1, WF2, WF3, WF4) em um único pipeline coeso.
"""
import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from ..models.schemas import (
    TipoDocumento,
    StatusArquivo,
    StatusPar,
    DecisaoFluxo,
    PayloadETAPA2,
    MetadadosDocumento,
    GabaritoExtraido,
    QuestaoExtraida,
    Alternativa,
)
from ..services.supabase import get_supabase
from ..services.openai_client import get_openai
from ..services.odontoquiz_api import get_odontoquiz_api
from ..utils.file_utils import (
    pdf_to_images,
    is_pdf,
    validate_file,
    normalize_filename,
    compute_hash,
)

logger = logging.getLogger(__name__)


class OdontoQuizPipeline:
    """
    Pipeline completo de processamento de materiais de concurso odontológico.

    Fluxo:
    1. INGESTÃO (WF4): recebe arquivos, faz upload, classifica, pareia prova+gabarito
    2. OCR LEVE (WF1): classifica cada documento como prova/gabarito/indefinido
    3. ETAPA 2 OCR (WF2): extrai questões, gabarito, disciplina e assuntos
    4. PORTAL (WF3): prepara payload para importação (decisão humana se necessário)
    """

    def __init__(self):
        self.supabase = get_supabase()
        self.openai = get_openai()
        self.api = get_odontoquiz_api()

    # ═══════════════════════════════════════════════════════════════════════════
    # ETAPA 1: INGESTÃO (WF4)
    # ═══════════════════════════════════════════════════════════════════════════

    async def processar_ingestao(self, payload: dict) -> dict:
        """
        Processa um lote de arquivos recebido via webhook.
        - Valida token
        - Cria lote no Supabase
        - Para cada arquivo: calcula hash, faz upload, insere registro
        - Inicia processamento assíncrono
        """
        lote_id = str(uuid4())
        arquivos_entrada = payload.get("arquivos", [])
        metadados = payload.get("metadados", {})

        logger.info(f"[INGESTÃO] Novo lote {lote_id} com {len(arquivos_entrada)} arquivos")

        # 1. Criar lote
        lote = self.supabase.criar_lote({
            "id": lote_id,
            "origem": "webhook",
            "status": "pendente",
            "metadata": json.dumps(metadados),
            "total_arquivos": len(arquivos_entrada),
        })

        # 2. Processar cada arquivo (com hash e dedup — FIX A2 + A3)
        arquivos_processados = []
        for i, arquivo in enumerate(arquivos_entrada):
            arquivo_id = str(uuid4())
            nome_original = arquivo.get("nome_original", f"arquivo_{i}")
            storage_path_in = arquivo.get("storage_path", f"lotes/{lote_id}/originais/{nome_original}")
            tipo_arquivo_inicial = arquivo.get("tipo_hint") or "indefinido"

            # FIX A2+A3: Calcular hash do arquivo e verificar duplicata
            hash_arquivo = None
            duplicado_de = None
            status_inicial = StatusArquivo.PENDENTE.value

            try:
                tmp_hash = os.path.join(tempfile.gettempdir(), f"hash_{arquivo_id}")
                self.supabase.download_arquivo(storage_path_in, tmp_hash)
                hash_arquivo = compute_hash(tmp_hash)
                os.unlink(tmp_hash)

                # Verificar duplicata (FIX A3)
                existente = self.supabase.buscar_arquivo_por_hash(hash_arquivo)
                if existente:
                    duplicado_de = existente["id"]
                    status_inicial = StatusArquivo.RECUSADO.value
                    logger.info(f"[INGESTÃO] Arquivo duplicado: {nome_original} (hash={hash_arquivo[:16]}...) → original={duplicado_de}")
            except Exception as e:
                logger.warning(f"[INGESTÃO] Falha ao calcular hash para {nome_original}: {e}")

            dados_arquivo = {
                "id": arquivo_id,
                "lote_id": lote_id,
                "origem": "webhook",
                "nome_original": nome_original,
                "storage_path": storage_path_in,
                "tipo_arquivo_inicial": tipo_arquivo_inicial,
                "binary_key": f"arquivo_{i}",
                "status": status_inicial,
                "hash_arquivo": hash_arquivo,
                "duplicado_de": duplicado_de,
                "metadata": {"ordem": i, "tipo_hint": arquivo.get("tipo_hint")},
            }
            self.supabase.inserir_arquivo(dados_arquivo)
            arquivos_processados.append(dados_arquivo)

        # 3. Atualizar status do lote
        self.supabase.atualizar_lote(lote_id, {"status": "arquivos_registrados"})

        # 4. Disparar processamento assíncrono
        asyncio.create_task(self._processar_lote(lote_id, arquivos_processados))

        return {
            "status": "recebido",
            "lote_id": lote_id,
            "arquivos_recebidos": len(arquivos_entrada),
            "mensagem": f"Lote {lote_id} recebido. Processamento iniciado.",
        }

    async def _processar_lote(self, lote_id: str, arquivos: list[dict]):
        """
        Processamento assíncrono do lote completo:
        Para cada arquivo → OCR Leve → Classificação → Pareamento → ETAPA 2
        """
        try:
            self.supabase.atualizar_lote(lote_id, {"status": "processando"})
            self.supabase.notificar_progresso(lote_id, "ingestao", "iniciado")

            # --- Fase 1: OCR Leve em todos os arquivos ---
            resultados_ocr = []
            for arquivo in arquivos:
                self.supabase.atualizar_arquivo(arquivo["id"], {"status": StatusArquivo.PROCESSANDO.value})
                try:
                    resultado = await self._ocr_leve(arquivo)
                    resultados_ocr.append(resultado)
                    self.supabase.atualizar_arquivo(
                        arquivo["id"],
                        {
                            "status": StatusArquivo.CLASSIFICADO.value,
                            "tipo_arquivo_inicial": resultado.get("tipo_detectado"),
                            "metadata": resultado,
                        },
                    )
                except Exception as e:
                    logger.error(f"Erro OCR Leve no arquivo {arquivo['id']}: {e}")
                    self.supabase.atualizar_arquivo(
                        arquivo["id"],
                        {"status": StatusArquivo.ERRO.value, "observacoes": str(e)},
                    )

            # --- Fase 2: Pareamento prova + gabarito ---
            pares = await self._parear_arquivos(lote_id, resultados_ocr)
            self.supabase.notificar_progresso(lote_id, "pareamento", "concluido", {"pares": len(pares)})

            # --- Fase 3: ETAPA 2 OCR em cada par ---
            for par in pares:
                await self._etapa2_ocr(par)

            self.supabase.atualizar_lote(lote_id, {"status": "concluido"})
            self.supabase.notificar_progresso(lote_id, "pipeline", "concluido")

        except Exception as e:
            logger.exception(f"Erro fatal no processamento do lote {lote_id}: {e}")
            self.supabase.atualizar_lote(lote_id, {"status": "erro", "observacoes": str(e)})
            self.supabase.notificar_progresso(lote_id, "pipeline", "erro", {"erro": str(e)})

    # ═══════════════════════════════════════════════════════════════════════════
    # ETAPA 2: OCR LEVE (WF1)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _ocr_leve(self, arquivo: dict) -> dict:
        """
        Classifica um documento como prova/gabarito/indefinido.
        Equivalente ao WF1: Odontoquiz OCR Leve - Identificação de Documento.
        Suporta PDF (converte primeira página para imagem automaticamente).
        """
        logger.info(f"[OCR LEVE] Classificando arquivo {arquivo['id']}: {arquivo['nome_original']}")

        # Download do arquivo do Supabase Storage
        ext = ".pdf" if ".pdf" in (arquivo.get("storage_path", "") or "").lower() else \
              "." + (arquivo.get("storage_path", "") or "").split(".")[-1] if "." in (arquivo.get("storage_path", "") or "") else ".jpg"
        tmp_path = os.path.join(tempfile.gettempdir(), f"ocr_leve_{arquivo['id']}{ext}")
        tmp_images = []  # Para limpeza de PDFs convertidos

        try:
            self.supabase.download_arquivo(arquivo["storage_path"], tmp_path)
        except Exception as e:
            logger.error(f"[OCR LEVE] Falha ao baixar arquivo: {e}")
            return {
                "arquivo_id": arquivo["id"],
                "erro_ocr_imagem": True,
                "mensagem": f"Falha ao baixar arquivo do storage: {e}",
            }

        try:
            # CORREÇÃO BUG #2: Converter PDF para imagem se necessário
            image_path = tmp_path
            is_pdf_file = is_pdf(tmp_path)
            pdf_pages = 1

            if is_pdf_file:
                logger.info(f"[OCR LEVE] PDF detectado, convertendo para imagem...")
                try:
                    images = pdf_to_images(tmp_path, dpi=150)
                    if images:
                        image_path = images[0]  # OCR Leve só precisa da primeira página
                        tmp_images = images
                        pdf_pages = len(images)
                        logger.info(f"[OCR LEVE] PDF convertido: {pdf_pages} páginas, usando p1 para classificação")
                    else:
                        raise ValueError("PDF não gerou imagens")
                except Exception as e:
                    logger.error(f"[OCR LEVE] Falha ao converter PDF: {e}")
                    return {
                        "arquivo_id": arquivo["id"],
                        "nome_original": arquivo["nome_original"],
                        "erro_ocr_imagem": True,
                        "mensagem": f"Falha ao converter PDF para imagem: {e}",
                    }

            # Validação de qualidade (BUG #7)
            validation = validate_file(image_path, arquivo.get("nome_original", ""))
            if validation.get("warning"):
                logger.warning(f"[OCR LEVE] ⚠️ {validation['warning']}")

            tipo_hint = arquivo.get("tipo_arquivo_inicial") or arquivo.get("tipo_hint") or "indefinido"
            resultado_ia = await self.openai.classificar_documento(image_path, tipo_hint)

            # CORREÇÃO #5: Validar erro do Analyze Image
            if resultado_ia.get("error"):
                logger.warning(f"[OCR LEVE] Erro do Analyze Image: {resultado_ia['error']}")
                return {
                    "arquivo_id": arquivo["id"],
                    "nome_original": arquivo["nome_original"],
                    "erro_ocr_imagem": True,
                    "mensagem": f"Falha no Analyze Image: {resultado_ia['error']}",
                }

            # Extrair metadados do resultado
            tipo_detectado = resultado_ia.get("tipo_arquivo", "indefinido")
            metadados = {
                "arquivo_id": arquivo["id"],
                "nome_original": arquivo["nome_original"],
                "titulo_documento": resultado_ia.get("titulo_documento"),
                "orgao": resultado_ia.get("orgao"),
                "concurso": resultado_ia.get("concurso"),
                "cargo": resultado_ia.get("cargo"),
                "codigo_prova": resultado_ia.get("codigo_prova"),
                "ano": resultado_ia.get("ano"),
                "caderno": resultado_ia.get("caderno"),
                "versao": resultado_ia.get("versao"),
                "tipo_detectado": tipo_detectado,
                "confianca_identificacao": min(float(resultado_ia.get("confianca_identificacao", 0) or 0), 0.99),
                "blocos_gabarito": resultado_ia.get("blocos_gabarito", []),
                "texto_base": resultado_ia.get("trecho_relevante", "")[:1200],
                "trecho_relevante": resultado_ia.get("trecho_relevante", ""),
                "justificativa": resultado_ia.get("justificativa"),
                "fonte_metadados": "image_analyze",
                "erro_ocr_imagem": False,
                "resposta_ia_parseada": resultado_ia,
                "is_pdf": is_pdf_file,
                "pdf_pages": pdf_pages,
                "image_quality_warning": validation.get("warning"),
            }

            logger.info(f"[OCR LEVE] {arquivo['id']}: {tipo_detectado} (confiança: {metadados['confianca_identificacao']}, pdf={is_pdf_file})")
            return metadados

        except Exception as e:
            logger.error(f"[OCR LEVE] Erro na classificação de {arquivo['id']}: {e}")
            return {
                "arquivo_id": arquivo["id"],
                "nome_original": arquivo["nome_original"],
                "erro_ocr_imagem": True,
                "mensagem": str(e),
            }
        finally:
            # Limpeza
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            for img in tmp_images:
                if os.path.exists(img):
                    os.unlink(img)

    # ═══════════════════════════════════════════════════════════════════════════
    # ETAPA 3: PAREAMENTO (WF4)
    # ═══════════════════════════════════════════════════════════════════════════

    def _normalizar_texto(self, s: str) -> str:
        """Normaliza texto para comparação (substitui a função 'norm' do n8n)."""
        import unicodedata
        import re
        s = unicodedata.normalize('NFD', str(s or ''))
        s = s.encode('ascii', 'ignore').decode('ascii')
        s = s.lower()
        s = re.sub(r'[^a-z0-9\s]', ' ', s)
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    def _calcular_score_pareamento(self, prova: dict, gabarito: dict) -> float:
        """
        Calcula score de similaridade entre prova e gabarito.
        Baseado em: órgão, cargo, código da prova, ano.
        Score máximo: 1.0
        """
        score = 0.0
        campos_prova = {
            "orgao": self._normalizar_texto(prova.get("orgao", "")),
            "cargo": self._normalizar_texto(prova.get("cargo", "")),
            "codigo_prova": self._normalizar_texto(prova.get("codigo_prova", "")),
            "ano": str(prova.get("ano", "")),
        }
        campos_gabarito = {
            "orgao": self._normalizar_texto(gabarito.get("orgao", "")),
            "cargo": self._normalizar_texto(gabarito.get("cargo", "")),
            "codigo_prova": self._normalizar_texto(gabarito.get("codigo_prova", "")),
            "ano": str(gabarito.get("ano", "")),
        }

        # Pesos: orgao=0.35, cargo=0.35, codigo=0.20, ano=0.10
        if campos_prova["orgao"] and campos_gabarito["orgao"]:
            score += 0.35 if campos_prova["orgao"] == campos_gabarito["orgao"] else 0.0

        if campos_prova["cargo"] and campos_gabarito["cargo"]:
            # Token similarity para cargo (pode ter variações: "Cirurgião Dentista" vs "Cirurgião-Dentista")
            ta = set(campos_prova["cargo"].split())
            tb = set(campos_gabarito["cargo"].split())
            if ta and tb:
                intersec = len(ta & tb)
                score += 0.35 * (intersec / max(len(ta), len(tb)))

        if campos_prova["codigo_prova"] and campos_gabarito["codigo_prova"]:
            score += 0.20 if campos_prova["codigo_prova"] == campos_gabarito["codigo_prova"] else 0.0

        if campos_prova["ano"] and campos_gabarito["ano"]:
            score += 0.10 if campos_prova["ano"] == campos_gabarito["ano"] else 0.0

        return min(score, 1.0)

    async def _parear_arquivos(self, lote_id: str, resultados_ocr: list[dict]) -> list[dict]:
        """
        Pareia arquivos de prova com gabaritos do mesmo lote.
        Usa score de similaridade para encontrar o melhor par.
        """
        logger.info(f"[PAREAMENTO] Lote {lote_id}: pareando {len(resultados_ocr)} arquivos")

        provas = [r for r in resultados_ocr if r.get("tipo_detectado") == "prova" and not r.get("erro_ocr_imagem")]
        gabaritos = [r for r in resultados_ocr if r.get("tipo_detectado") == "gabarito" and not r.get("erro_ocr_imagem")]

        logger.info(f"[PAREAMENTO] {len(provas)} provas, {len(gabaritos)} gabaritos")

        pares = []

        # Estratégia: para cada gabarito, encontrar a melhor prova
        for gabarito in gabaritos:
            melhor_prova = None
            melhor_score = 0.0
            scores = []

            for prova in provas:
                score = self._calcular_score_pareamento(prova, gabarito)
                scores.append({"prova_id": prova["arquivo_id"], "score": score})
                if score > melhor_score:
                    melhor_score = score
                    melhor_prova = prova

            if melhor_prova and melhor_score > 0.3:  # threshold mínimo
                par_id = str(uuid4())
                chave = f"{melhor_prova.get('orgao','')}|{melhor_prova.get('concurso','')}|{melhor_prova.get('cargo','')}|{melhor_prova.get('codigo_prova','')}"
                par = {
                    "id": par_id,
                    "lote_id": lote_id,
                    "arquivo_prova_id": melhor_prova["arquivo_id"],
                    "arquivo_gabarito_id": gabarito["arquivo_id"],
                    "confianca_pareamento": round(melhor_score, 2),
                    "status": StatusPar.PAREADO.value if melhor_score > 0.6 else StatusPar.REVISAO_MANUAL.value,
                    "chave_pareamento": self._normalizar_texto(chave),
                }
                self.supabase.criar_par(par)
                pares.append(par)
                logger.info(f"[PAREAMENTO] Par {par_id}: prova={melhor_prova['arquivo_id']} + gabarito={gabarito['arquivo_id']} (score={melhor_score:.2f})")
            else:
                logger.warning(f"[PAREAMENTO] Nenhuma prova encontrada para gabarito {gabarito['arquivo_id']} (max_score={melhor_score:.2f})")

        # Atualizar chave_pareamento nos arquivos pareados
        for par in pares:
            self.supabase.atualizar_arquivo(par["arquivo_prova_id"], {"chave_pareamento": par["chave_pareamento"]})
            self.supabase.atualizar_arquivo(par["arquivo_gabarito_id"], {"chave_pareamento": par["chave_pareamento"]})

        return pares

    # ═══════════════════════════════════════════════════════════════════════════
    # ETAPA 4: ETAPA 2 OCR (WF2)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _etapa2_ocr(self, par: dict) -> PayloadETAPA2:
        """
        Extrai questões, gabarito, disciplinas e assuntos de um par prova+gabarito.
        Equivalente ao WF2: ETAPA 2 OCR.
        Suporta PDF (converte todas as páginas e combina resultados).
        """
        logger.info(f"[ETAPA 2] Processando par {par['id']}")

        prova = self.supabase.buscar_arquivo(par["arquivo_prova_id"])
        gabarito = self.supabase.buscar_arquivo(par["arquivo_gabarito_id"])

        if not prova or not gabarito:
            raise ValueError(f"Arquivos do par {par['id']} não encontrados")

        # 1. Baixar arquivos
        tmp_prova = os.path.join(tempfile.gettempdir(), f"etapa2_prova_{prova['id']}.jpg")
        tmp_gabarito = os.path.join(tempfile.gettempdir(), f"etapa2_gabarito_{gabarito['id']}.jpg")
        tmp_imgs_prova = []
        tmp_imgs_gabarito = []

        try:
            self.supabase.download_arquivo(prova["storage_path"], tmp_prova)
            self.supabase.download_arquivo(gabarito["storage_path"], tmp_gabarito)

            # CORREÇÃO BUG #2: Converter PDFs para imagens
            prova_images = [tmp_prova]
            gabarito_images = [tmp_gabarito]

            if is_pdf(tmp_prova):
                logger.info(f"[ETAPA 2] Prova é PDF, convertendo...")
                prova_images = pdf_to_images(tmp_prova, dpi=150)
                tmp_imgs_prova = prova_images
                logger.info(f"[ETAPA 2] Prova PDF: {len(prova_images)} páginas")

            if is_pdf(tmp_gabarito):
                logger.info(f"[ETAPA 2] Gabarito é PDF, convertendo...")
                gabarito_images = pdf_to_images(tmp_gabarito, dpi=150)
                tmp_imgs_gabarito = gabarito_images
                logger.info(f"[ETAPA 2] Gabarito PDF: {len(gabarito_images)} páginas")

            # 2. Extrair questões da prova (todas as páginas)
            todas_questoes = []
            todas_disciplinas_sugeridas = []
            resultado_prova = {}

            for i, img_path in enumerate(prova_images):
                contexto_prova = {
                    "nome_original": prova["nome_original"],
                    "tipo_esperado": "prova",
                    "ordem_arquivo": (prova.get("metadata") or {}).get("ordem", i + 1) if isinstance(prova.get("metadata"), dict) else i + 1,
                    "total_arquivos": len(prova_images),
                    "arquivo_gabarito_id": gabarito["id"],
                    "arquivos_prova_ids": [prova["id"]],
                }

                resultado_pagina = await self.openai.extrair_questoes_gabarito(img_path, contexto_prova)
                if resultado_pagina.get("error"):
                    logger.warning(f"[ETAPA 2] Erro na página {i+1}: {resultado_pagina['error']}")
                    continue

                qs = resultado_pagina.get("questoes", [])
                todas_questoes.extend(qs)
                todas_disciplinas_sugeridas.extend(resultado_pagina.get("disciplinas_sugeridas", []))
                if i == 0:
                    resultado_prova = resultado_pagina

            resultado_prova["questoes"] = todas_questoes
            resultado_prova["disciplinas_sugeridas"] = todas_disciplinas_sugeridas
            logger.info(f"[ETAPA 2] Prova: {len(todas_questoes)} questões de {len(prova_images)} páginas")

            # 3. Extrair gabarito (todas as páginas)
            todas_respostas = {}
            resultado_gabarito = {}

            for i, img_path in enumerate(gabarito_images):
                contexto_gabarito = {
                    "nome_original": gabarito["nome_original"],
                    "tipo_esperado": "gabarito",
                    "ordem_arquivo": i + 1,
                    "total_arquivos": len(gabarito_images),
                    "arquivo_gabarito_id": gabarito["id"],
                    "arquivos_prova_ids": [prova["id"]],
                }

                resultado_pagina = await self.openai.extrair_questoes_gabarito(img_path, contexto_gabarito)
                if resultado_pagina.get("error"):
                    logger.warning(f"[ETAPA 2] Erro no gabarito p{i+1}: {resultado_pagina['error']}")
                    continue

                gab = resultado_pagina.get("gabarito", {})
                respostas = gab.get("respostas", {}) if gab else {}
                todas_respostas.update(respostas)
                if i == 0:
                    resultado_gabarito = resultado_pagina

            resultado_gabarito["gabarito"] = {"respostas": todas_respostas}
            logger.info(f"[ETAPA 2] Gabarito: {len(todas_respostas)} respostas de {len(gabarito_images)} páginas")

            # 4. Buscar referências do OdontoQuiz para validação
            disciplinas = await self._buscar_disciplinas_com_fallback()
            try:
                assuntos = await self.api.listar_assuntos()
            except Exception as e:
                logger.warning(f"[ETAPA 2] API assuntos offline, usando cache: {e}")
                from ..services.discipline_cache import get_assuntos_fallback
                assuntos = get_assuntos_fallback()

            # 5. Validar referências (CORREÇÃO #3: mapear disciplinas/assuntos para IDs)
            questoes_raw = resultado_prova.get("questoes", [])
            gabarito_raw = resultado_gabarito.get("gabarito", {}).get("respostas", {})

            payload = await self._montar_payload_etapa2(
                par=par,
                prova=prova,
                gabarito=gabarito,
                questoes=questoes_raw,
                gabarito_respostas=gabarito_raw,
                disciplinas=disciplinas,
                assuntos=assuntos,
                resultado_prova=resultado_prova,
                resultado_gabarito=resultado_gabarito,
            )

            # 6. Salvar resultado no metadata do arquivo
            self.supabase.atualizar_arquivo(prova["id"], {
                "status": StatusArquivo.EXTRAIDO.value,
                "metadata": {"payload_etapa2": payload.model_dump()},
            })
            self.supabase.atualizar_par(par["id"], {"status": StatusPar.PROCESSADO.value})

            # 7. Se entrega direta (confiança alta), importar automaticamente
            if payload.decisao_fluxo == DecisaoFluxo.ENTREGA_DIRETA:
                await self._importar_questoes(payload)

            logger.info(f"[ETAPA 2] Par {par['id']}: {len(payload.questoes)} questões, fluxo={payload.decisao_fluxo.value}")

            return payload

        finally:
            all_temps = [tmp_prova, tmp_gabarito] + tmp_imgs_prova + tmp_imgs_gabarito
            for p in all_temps:
                if os.path.exists(p):
                    os.unlink(p)

    async def _buscar_disciplinas_com_fallback(self) -> list[dict]:
        """
        Busca disciplinas da API com fallback para cache local (CORREÇÃO BUG #1).
        Se a API OdontoQuiz estiver offline, usa cache estático.
        """
        from ..services.discipline_cache import get_disciplinas_fallback

        try:
            disciplinas = await self.api.listar_disciplinas()
            if disciplinas and len(disciplinas) > 0:
                logger.info(f"[REFERÊNCIAS] {len(disciplinas)} disciplinas da API")
                return disciplinas
        except Exception as e:
            logger.warning(f"[REFERÊNCIAS] API OdontoQuiz indisponível: {e}")

        # Fallback para cache local
        logger.warning("[REFERÊNCIAS] Usando cache local de disciplinas")
        return get_disciplinas_fallback()

    async def _montar_payload_etapa2(
        self,
        par: dict,
        prova: dict,
        gabarito: dict,
        questoes: list[dict],
        gabarito_respostas: dict,
        disciplinas: list[dict],
        assuntos: list[dict],
        resultado_prova: dict,
        resultado_gabarito: dict,
    ) -> PayloadETAPA2:
        """
        Monta o payload final da ETAPA 2 com:
        - Questões normalizadas e deduplicadas
        - Disciplinas/assuntos mapeados para IDs (CORREÇÃO #3)
        - Validação de schema (CORREÇÃO #9)
        """

        # ─── Normalizar questões ─────────────────────────────────────────
        questoes_normalizadas = []
        for q in questoes or []:
            numero = q.get("numero")
            enunciado = q.get("enunciado", "")
            if not enunciado or not str(enunciado).strip():
                continue

            alternativas = []
            for alt in (q.get("alternativas") or []):
                alternativas.append(Alternativa(
                    letra=alt.get("letra"),
                    texto=alt.get("texto"),
                    ilegivel=bool(alt.get("ilegivel")),
                ))

            # CORREÇÃO #9: Validar schema
            if len(alternativas) < 2:
                logger.warning(f"Questão {numero}: menos de 2 alternativas, pulando")
                continue

            questoes_normalizadas.append(QuestaoExtraida(
                numero=numero,
                enunciado=enunciado,
                texto_base=q.get("texto_base"),
                comando=q.get("comando"),
                alternativas=alternativas,
                confianca_extracao=float(q.get("confianca_extracao") or 0),
            ))

        # ─── Deduplicar questões (CORREÇÃO #8) ──────────────────────────
        questoes_dedup = self._deduplicar_questoes(questoes_normalizadas)

        # ─── CORREÇÃO #3: Mapear disciplinas e assuntos para IDs ─────────
        disciplinas_por_questao = {}
        assuntos_por_questao = {}

        disciplinas_sugeridas = resultado_prova.get("disciplinas_sugeridas", [])

        # Mapa nome → ID para fuzzy matching
        nome_para_id = {d["nome"].lower().strip(): d["id"] for d in disciplinas if d.get("nome")}
        assunto_nome_para_id = {a["nome"].lower().strip(): a["id"] for a in assuntos if a.get("nome")}

        for sugestao in disciplinas_sugeridas:
            num = str(sugestao.get("numero_questao", ""))
            if not num:
                continue

            # Buscar disciplina por fuzzy match
            disciplina_nome = (sugestao.get("disciplina") or "").lower().strip()
            disciplina_id = None
            for nome, did in nome_para_id.items():
                if disciplina_nome in nome or nome in disciplina_nome:
                    disciplina_id = did
                    break

            if disciplina_id:
                disciplinas_por_questao[num] = [disciplina_id]

                # Mapear assuntos
                assuntos_ids = []
                for assunto_nome in (sugestao.get("assuntos") or []):
                    anome = assunto_nome.lower().strip()
                    for nome, aid in assunto_nome_para_id.items():
                        if anome in nome or nome in anome:
                            assuntos_ids.append(aid)
                            break
                if assuntos_ids:
                    assuntos_por_questao[num] = assuntos_ids

        # ─── Gabarito ─────────────────────────────────────────────────────
        gabarito_obj = None
        if gabarito_respostas:
            gabarito_obj = GabaritoExtraido(respostas=gabarito_respostas)

        # ─── Decisão de fluxo ────────────────────────────────────────────
        confianca_media = (
            sum(q.confianca_extracao for q in questoes_dedup) / len(questoes_dedup)
            if questoes_dedup else 0.0
        )

        if not questoes_dedup:
            decisao = DecisaoFluxo.ERRO
            motivos = ["nenhuma_questao_extraida"]
        elif confianca_media > 0.8 and len(disciplinas_por_questao) > 0:
            decisao = DecisaoFluxo.ENTREGA_DIRETA
            motivos = []
        elif confianca_media > 0.5:
            decisao = DecisaoFluxo.ENTREGA_PAYLOAD
            motivos = []
        else:
            decisao = DecisaoFluxo.REVISAO_HUMANA
            motivos = ["baixa_confianca"]

        # Se não mapeou nenhuma disciplina, precisa de revisão
        if not disciplinas_por_questao:
            decisao = DecisaoFluxo.REVISAO_HUMANA
            if "disciplinas_nao_mapeadas" not in motivos:
                motivos.append("disciplinas_nao_mapeadas")

        return PayloadETAPA2(
            arquivo_id=prova["id"],
            questoes=questoes_dedup,
            gabarito=gabarito_obj,
            disciplinas_por_questao=disciplinas_por_questao,
            assuntos_por_questao=assuntos_por_questao,
            decisao_fluxo=decisao,
            motivos_revisao=motivos,
            precisa_revisao_humana=decisao == DecisaoFluxo.REVISAO_HUMANA,
            erro_validacao_referencias=decisao == DecisaoFluxo.ERRO,
        )

    def _deduplicar_questoes(self, questoes: list[QuestaoExtraida]) -> list[QuestaoExtraida]:
        """
        Deduplica questões mantendo a de maior confiança (CORREÇÃO #8).
        Score = confianca_extracao * 200 + alternativas_validas * 50 + min(texto_len, 500) * 0.1
        """
        mapa = {}

        for q in questoes:
            if q.numero is None:
                continue

            num = q.numero
            alt_validas = sum(1 for a in q.alternativas if not a.ilegivel and a.texto)
            score = (
                (q.confianca_extracao or 0) * 200
                + alt_validas * 50
                + min(len(q.enunciado or ""), 500) * 0.1
            )

            if num not in mapa or score > mapa[num][0]:
                mapa[num] = (score, q)

        # Ordena por número
        resultado = [q for _, q in sorted(mapa.values(), key=lambda x: (x[1].numero or 0))]
        return resultado

    # ═══════════════════════════════════════════════════════════════════════════
    # ETAPA 5: IMPORTAÇÃO (WF3)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _importar_questoes(self, payload: PayloadETAPA2) -> dict:
        """
        Importa questões para o OdontoQuiz (CORREÇÃO #4: sem IDs hardcoded).
        Equivalente ao WF3: Portal - Webhook de Decisão.
        """
        logger.info(f"[IMPORTAÇÃO] Importando {len(payload.questoes)} questões do arquivo {payload.arquivo_id}")

        prova = self.supabase.buscar_arquivo(payload.arquivo_id)
        metadados = (prova or {}).get("metadata", {}) or {}

        # CORREÇÃO #4: IDs de referência devem vir do payload, nunca hardcoded
        banca_id = metadados.get("banca_id")
        instituicao_id = metadados.get("instituicao_id")
        cargo_id = metadados.get("cargo_id")

        if not all([banca_id, instituicao_id, cargo_id]):
            raise ValueError(
                "Referências incompletas para importação. "
                f"banca_id={banca_id}, instituicao_id={instituicao_id}, cargo_id={cargo_id}"
            )

        questoes_import = []
        for q in payload.questoes:
            num = str(q.numero)
            gabarito_resposta = None
            if payload.gabarito and num in payload.gabarito.respostas:
                gabarito_resposta = payload.gabarito.respostas[num]

            questoes_import.append({
                "numero": q.numero,
                "enunciado": q.enunciado,
                "texto_base": q.texto_base,
                "comando": q.comando,
                "alternativas": [
                    {"letra": a.letra, "texto": a.texto}
                    for a in q.alternativas
                ],
                "gabarito": gabarito_resposta,
                "disciplina_id": payload.disciplinas_por_questao.get(num, [None])[0],
                "assunto_id": payload.assuntos_por_questao.get(num, [None])[0],
            })

        payload_import = {
            "banca_id": banca_id,
            "instituicao_id": instituicao_id,
            "cargo_id": cargo_id,
            "ano": metadados.get("ano"),
            "questoes": questoes_import,
        }

        resultado = await self.api.importar_questoes(payload_import)
        logger.info(f"[IMPORTAÇÃO] {len(questoes_import)} questões importadas com sucesso")

        # Atualizar status
        self.supabase.atualizar_arquivo(payload.arquivo_id, {"status": StatusArquivo.IMPORTADO.value})

        return resultado


# Singleton
_pipeline: Optional[OdontoQuizPipeline] = None


def get_pipeline() -> OdontoQuizPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = OdontoQuizPipeline()
    return _pipeline
