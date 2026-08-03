"""
Utilitários de manipulação de arquivos — conversão PDF→imagem, validação de qualidade.
"""
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── PDF → Imagem ──────────────────────────────────────────────────────────

try:
    import fitz  # PyMuPDF

    def pdf_to_images(pdf_path: str, output_dir: Optional[str] = None, dpi: int = 150) -> list[str]:
        """
        Converte um PDF em imagens JPEG, uma por página.
        Retorna a lista de caminhos das imagens geradas.

        Args:
            pdf_path: Caminho do arquivo PDF
            output_dir: Diretório de saída (default: tempdir)
            dpi: Resolução da imagem (150 = boa qualidade, 200 = alta)

        Returns:
            Lista de paths das imagens geradas
        """
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="pdf2img_")

        doc = fitz.open(pdf_path)
        total_pages = doc.page_count
        image_paths = []

        for page_num in range(total_pages):
            page = doc[page_num]
            # Renderizar página como imagem
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)

            img_path = os.path.join(
                output_dir,
                f"{Path(pdf_path).stem}_p{page_num + 1:03d}.jpeg",
            )
            pix.save(img_path)
            image_paths.append(img_path)
            logger.debug(f"PDF p{page_num + 1}: {pix.width}x{pix.height} → {img_path}")

        doc.close()
        logger.info(f"PDF convertido: {total_pages} páginas → {len(image_paths)} imagens (DPI={dpi})")
        return image_paths

    def is_pdf(file_path: str) -> bool:
        """Verifica se o arquivo é um PDF (por extensão e magic bytes)."""
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            return True
        # Verificar magic bytes
        try:
            with open(file_path, "rb") as f:
                header = f.read(5)
                return header == b"%PDF-"
        except Exception:
            return False

    def get_pdf_page_count(file_path: str) -> int:
        """Retorna o número de páginas de um PDF."""
        doc = fitz.open(file_path)
        count = doc.page_count
        doc.close()
        return count

except ImportError:
    logger.warning("PyMuPDF (fitz) não instalado. Conversão PDF→imagem desabilitada.")

    def pdf_to_images(pdf_path: str, **kwargs) -> list[str]:
        raise ImportError("PyMuPDF não instalado. Instale com: pip install PyMuPDF")

    def is_pdf(file_path: str) -> bool:
        return Path(file_path).suffix.lower() == ".pdf"

    def get_pdf_page_count(file_path: str) -> int:
        raise ImportError("PyMuPDF não instalado.")


# ─── Validação de Imagem ───────────────────────────────────────────────────

MIN_IMAGE_SIZE_BYTES = 50 * 1024      # 50 KB mínimo
WARN_IMAGE_SIZE_BYTES = 100 * 1024    # 100 KB warning
MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB máximo

SUPPORTED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SUPPORTED_DOC_TYPES = {".pdf"}


def validate_file(file_path: str, nome_original: str = "") -> dict:
    """
    Valida um arquivo antes do processamento.
    Retorna: {"ok": bool, "warning": str|None, "error": str|None, "info": dict}
    """
    result = {
        "ok": True,
        "warning": None,
        "error": None,
        "info": {"size_bytes": 0, "ext": "", "is_pdf": False, "pages": 1},
    }

    if not os.path.exists(file_path):
        result["ok"] = False
        result["error"] = f"Arquivo não encontrado: {nome_original}"
        return result

    size = os.path.getsize(file_path)
    ext = Path(file_path).suffix.lower()
    result["info"]["size_bytes"] = size
    result["info"]["ext"] = ext

    # Tamanho máximo
    if size > MAX_IMAGE_SIZE_BYTES:
        result["ok"] = False
        result["error"] = (
            f"Arquivo muito grande ({size / 1024 / 1024:.1f} MB). "
            f"Máximo: {MAX_IMAGE_SIZE_BYTES / 1024 / 1024:.0f} MB"
        )
        return result

    # Tipo suportado
    is_pdf_file = is_pdf(file_path)
    result["info"]["is_pdf"] = is_pdf_file

    if is_pdf_file:
        try:
            pages = get_pdf_page_count(file_path)
            result["info"]["pages"] = pages
        except Exception:
            pages = "?"
    elif ext not in SUPPORTED_IMAGE_TYPES:
        result["ok"] = False
        result["error"] = (
            f"Formato não suportado: {ext}. "
            f"Formatos aceitos: {', '.join(SUPPORTED_IMAGE_TYPES | SUPPORTED_DOC_TYPES)}"
        )
        return result

    # Tamanho mínimo para imagens
    if not is_pdf_file and size < MIN_IMAGE_SIZE_BYTES:
        result["warning"] = (
            f"Imagem muito pequena ({size / 1024:.0f} KB). "
            f"Recomendado mínimo de {MIN_IMAGE_SIZE_BYTES / 1024:.0f} KB para boa extração."
        )
    elif not is_pdf_file and size < WARN_IMAGE_SIZE_BYTES:
        result["warning"] = (
            f"Imagem com tamanho baixo ({size / 1024:.0f} KB). "
            f"Qualidade da extração pode ser reduzida."
        )

    return result


def compute_hash(file_path: str, algorithm: str = "sha256") -> str:
    """
    Calcula o hash de um arquivo (default: SHA256).
    Lê o arquivo em chunks para não estourar memória com arquivos grandes.
    """
    import hashlib
    h = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def normalize_filename(nome_original: str) -> str:
    """
    Normaliza nome de arquivo para storage_path.
    Remove caracteres especiais, espaços, acentos.
    """
    import re
    import unicodedata

    # Remove extensão
    stem = Path(nome_original).stem
    ext = Path(nome_original).suffix.lower()

    # Normaliza unicode (remove acentos)
    stem = unicodedata.normalize("NFKD", stem)
    stem = stem.encode("ascii", "ignore").decode("ascii")

    # Substitui espaços e caracteres especiais por underscore
    stem = re.sub(r"[^a-zA-Z0-9]", "_", stem)
    # Remove underscores múltiplos
    stem = re.sub(r"_+", "_", stem)
    # Remove underscore do início/fim
    stem = stem.strip("_").lower()

    if not stem:
        stem = "arquivo"

    return f"{stem}{ext}" if ext else stem
