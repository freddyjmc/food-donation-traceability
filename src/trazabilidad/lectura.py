"""Abrir un albarán (PDF o foto) y pasar cada página a imagen en gris, lista para el OCR."""

from pathlib import Path

import pymupdf
from PIL import Image

EXTENSIONES_IMAGEN = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def paginas_a_imagenes(ruta: str | Path, dpi: int = 300) -> list[Image.Image]:
    """Devuelve una imagen en escala de grises por cada página del PDF (o la foto, si es imagen)."""
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo: {ruta}")
    if ruta.suffix.lower() in EXTENSIONES_IMAGEN:
        return [Image.open(ruta).convert("L")]
    if ruta.suffix.lower() != ".pdf":
        raise ValueError(f"Formato no admitido: {ruta.suffix}")

    imagenes = []
    with pymupdf.open(ruta) as documento:
        for pagina in documento:
            pix = pagina.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            imagenes.append(Image.frombytes("L", (pix.width, pix.height), pix.samples))
    return imagenes
