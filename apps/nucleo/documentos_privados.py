"""Validação de documentos privados, compartilhada entre os módulos."""

import hashlib
import re
import warnings
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

LIMITE_BYTES = 10 * 1024 * 1024
TIPOS = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".xml": "application/xml"}


def preparar_documento(arquivo):
    """Lê no máximo 10 MiB e confere o conteúdo, além da extensão declarada."""
    if arquivo is None:
        return None
    nome = PurePosixPath(str(arquivo.name).replace("\\", "/")).name
    nome = re.sub(r"[\x00-\x1f\x7f]", "", nome)
    extensao = PurePosixPath(nome).suffix.lower()
    if extensao not in TIPOS:
        raise ValidationError("Anexe um PDF, uma imagem JPG/PNG ou um XML de até 10 MB.")
    if getattr(arquivo, "size", 0) > LIMITE_BYTES:
        raise ValidationError("O documento deve ter no máximo 10 MB.")
    conteudo = arquivo.read(LIMITE_BYTES + 1)
    if not conteudo:
        raise ValidationError("O documento está vazio. Escolha um arquivo válido.")
    if len(conteudo) > LIMITE_BYTES:
        raise ValidationError("O documento deve ter no máximo 10 MB.")
    try:
        if extensao == ".pdf":
            if not re.match(rb"%PDF-[12]\.\d", conteudo) or b"%%EOF" not in conteudo[-1024:]:
                raise ValueError()
            leitor = PdfReader(BytesIO(conteudo), strict=True)
            if leitor.is_encrypted or not 1 <= len(leitor.pages) <= 500:
                raise ValueError()
        elif extensao == ".xml":
            texto = conteudo.decode("utf-8-sig")
            # Sem DTD não há entidade para expandir nem para buscar fora: é a defesa
            # do defusedxml, feita aqui antes do parse.
            if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", texto, re.IGNORECASE):
                raise ValueError()
            ElementTree.fromstring(texto)  # nosec B314
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(conteudo)) as imagem:
                    formato = "PNG" if extensao == ".png" else "JPEG"
                    if imagem.format != formato or imagem.width * imagem.height > 40_000_000:
                        raise ValueError()
                    imagem.verify()
    except (ValueError, UnicodeError, OSError, ElementTree.ParseError, PdfReadError, RecursionError,
            UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as erro:
        raise ValidationError("O arquivo não corresponde a um documento válido no formato escolhido.") from erro
    if len(nome) > 180:
        nome = nome[:180 - len(extensao)] + extensao
    return {"nome": nome, "tipo": TIPOS[extensao], "tamanho": len(conteudo),
            "conteudo": conteudo, "sha256": hashlib.sha256(conteudo).hexdigest()}
