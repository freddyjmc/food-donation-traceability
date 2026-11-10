"""Prueba con Tesseract sobre una tabla dibujada (sin albaranes reales). Marcada «ocr»."""

from pathlib import Path

import pytest


@pytest.mark.ocr
def test_ocr_lee_todos_los_digitos_de_la_cantidad_en_una_tabla_sintetica():
    """Tabla dibujada con rayas entre filas: las cantidades 1..9 deben salir enteras."""
    from PIL import Image, ImageDraw, ImageFont

    from trazabilidad.ocr import leer_texto
    from trazabilidad.parser import leer_albaran

    fuentes = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not fuentes.exists():
        pytest.skip("No hay una fuente para dibujar la tabla de prueba")
    fuente = ImageFont.truetype(str(fuentes), 34)
    imagen = Image.new("L", (2480, 3507), 255)
    dibujo = ImageDraw.Draw(imagen)
    for texto, x in (("Codigo", 190), ("Descripcion", 725), ("Cantidad", 1539), ("Unidad", 2232)):
        dibujo.text((x, 300), texto, font=fuente, fill=0)
    for n in range(1, 10):
        y = 300 + n * 95
        dibujo.line((150, y - 14, 2330, y - 14), fill=120, width=2)
        dibujo.text((190, y), str(70000 + n), font=fuente, fill=0)
        dibujo.text((725, y), f"PRODUCTO NUMERO {n}", font=fuente, fill=0)
        dibujo.text((1610, y), str(n), font=fuente, fill=0)
        dibujo.text((2232, y), "UN", font=fuente, fill=0)
    albaran = leer_albaran(leer_texto(imagen))
    assert [(linea.codigo, linea.cantidad) for linea in albaran.lineas] == [
        (str(70000 + n), float(n)) for n in range(1, 10)
    ]
