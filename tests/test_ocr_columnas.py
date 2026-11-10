"""Pruebas de la reconstrucción de líneas por columnas (sin Tesseract: posiciones inventadas)."""

import pytest

from trazabilidad.ocr import reconstruir_lineas

ANCHO = 2000


def _datos(filas, cabecera=True):
    """filas: lista de listas de (texto, izquierda). Cada fila es una línea del OCR."""
    datos = {k: [] for k in ("text", "left", "width", "top", "height",
                             "block_num", "par_num", "line_num")}
    todas = ([[("Codigo", 100), ("Descripcion", 400), ("Cantidad", 1300), ("Unidad", 1800)]]
             if cabecera else []) + filas
    for n, fila in enumerate(todas):
        for texto, izq in fila:
            datos["text"].append(texto)
            datos["left"].append(izq)
            datos["width"].append(max(20, 25 * len(texto)))
            datos["top"].append(100 + n * 60)
            datos["height"].append(30)
            datos["block_num"].append(1)
            datos["par_num"].append(1)
            datos["line_num"].append(n)
    return datos


def _leer(filas, cantidad="1", cabecera=True):
    llamadas = []

    def celda(i, a, d, b):
        llamadas.append((i, a, d, b))
        return cantidad

    lineas = reconstruir_lineas(_datos(filas, cabecera), ANCHO, celda)
    return lineas[1 if cabecera else 0:], llamadas


@pytest.mark.parametrize("basura", ["a", "L", "q", "{", "|", "-", "é", "~~", "x1"])
def test_cantidad_ilegible_se_relee_y_no_se_pega_a_la_descripcion(basura):
    fila = [("84785", 100), ("BERLINA", 400), ("CACAO", 700), ("4", 900), ("UDS", 960),
            (basura, 1400), ("UN", 1850)]
    lineas, llamadas = _leer([fila], cantidad="3")
    assert lineas == ["84785 BERLINA CACAO 4 UDS 3 UN"]
    assert len(llamadas) == 1 and llamadas[0][0] < 1400 < llamadas[0][2]


def test_si_la_relectura_falla_la_linea_queda_sin_cantidad_y_sin_basura():
    fila = [("14725", 100), ("HOJALDRE", 400), ("PIZZA", 700), ("L", 1400), ("UN", 1850)]
    lineas, _ = _leer([fila], cantidad=None)
    assert lineas == ["14725 HOJALDRE PIZZA UN"]


def test_cantidad_ausente_tambien_se_relee():
    fila = [("67563", 100), ("PAN", 400), ("QUESO", 600), ("18%", 800), ("UN", 1850)]
    lineas, _ = _leer([fila], cantidad="4")
    assert lineas == ["67563 PAN QUESO 18% 4 UN"]


def test_cantidad_bien_leida_no_se_toca_ni_se_relee():
    fila = [("2807", 100), ("TACOS", 400), ("ANOJO", 700), ("1", 1400), ("UN", 1850)]
    lineas, llamadas = _leer([fila], cantidad="9")
    assert lineas == ["2807 TACOS ANOJO 1 UN"] and not llamadas


def test_cantidad_con_decimales_no_se_toca():
    fila = [("5001", 100), ("CIRUELA", 400), ("0,834", 1380), ("KG", 1850)]
    lineas, llamadas = _leer([fila], cantidad="9")
    assert lineas == ["5001 CIRUELA 0,834 KG"] and not llamadas


def test_una_palabra_corta_de_la_descripcion_no_se_pierde():
    fila = [("9220", 100), ("PAN", 400), ("DE", 600), ("LA", 700), ("ABUELA", 800),
            ("x", 1400), ("UN", 1850)]
    lineas, _ = _leer([fila], cantidad="2")
    assert lineas == ["9220 PAN DE LA ABUELA 2 UN"]


def test_lineas_que_no_son_filas_de_producto_pasan_igual():
    otras = [[("Fecha:", 100), ("05-05-2026", 300), ("DON12342026050500001", 900)],
             [("RECIBI:", 900)]]
    lineas, llamadas = _leer(otras)
    assert lineas == ["Fecha: 05-05-2026 DON12342026050500001", "RECIBI:"] and not llamadas


def test_sin_cabecera_solo_se_limpian_simbolos_y_letras_sueltas():
    fila = [("84785", 100), ("BERLINA", 400), ("CACAO", 700), ("a", 1400), ("UN", 1850)]
    lineas, _ = _leer([fila], cantidad="2", cabecera=False)
    assert lineas == ["84785 BERLINA CACAO 2 UN"]
    ok = [("84785", 100), ("BERLINA", 400), ("5", 1400), ("UN", 1850)]
    assert _leer([ok], cantidad="9", cabecera=False)[0] == ["84785 BERLINA 5 UN"]


@pytest.mark.parametrize("cantidad", ["6,75", "0,5", "12,5", "0,834", "1.000"])
def test_decimales_bien_leidos_no_se_tocan(cantidad):
    fila = [("8177", 100), ("MANZ.", 400), ("ROJA", 700), ("DULCE", 900),
            (cantidad, 1380), ("KG", 1850)]
    lineas, llamadas = _leer([fila], cantidad="999")
    assert lineas == [f"8177 MANZ. ROJA DULCE {cantidad} KG"] and not llamadas


@pytest.mark.parametrize("simbolo", [":", "|", ".", "-", "~"])
def test_cantidad_bien_leida_con_un_simbolo_suelto_al_lado(simbolo):
    fila = [("4570", 100), ("SOLOMILLO", 400), ("CERDO", 700), ("2", 1400), (simbolo, 1450),
            ("UN", 1850)]
    lineas, llamadas = _leer([fila], cantidad="9")
    assert lineas == ["4570 SOLOMILLO CERDO 2 UN"] and not llamadas
