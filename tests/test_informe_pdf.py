import datetime as dt

import fitz

from trazabilidad.graficos import destino, recibido_por_categoria
from trazabilidad.informe_pdf import escribir_pdf, numero, ruta_pdf
from trazabilidad.informes import LineaEntrada, calcular_informe


def _informe(recap=(None, None)):
    lineas = [
        LineaEntrada(dt.date(2026, 1, 2), "A1", "1", "LECHE", "Lácteos", 10, "UN"),
        LineaEntrada(dt.date(2026, 1, 2), "A1", "2", "FRUTA", "Fruta y verdura", 5.5, "KG"),
    ]
    return calcular_informe(
        lineas, [], dt.date(2026, 1, 1), dt.date(2026, 1, 31), 61, None, "", {}, {}, recap
    )


def test_pdf_tiene_dos_hojas(tmp_path):
    ruta = escribir_pdf(_informe((1001.64, 3197.64)), ruta_pdf(tmp_path, 2026, 1))
    assert ruta.exists()
    assert len(fitz.open(ruta)) == 2


def test_graficos_devuelven_rebanadas():
    inf = _informe()
    assert recibido_por_categoria(inf)
    assert isinstance(destino(inf), list)


def test_numero_formato_espanol():
    assert numero(1234.5) == "1.234,50"


def test_mes_anterior_al_inicio_no_inventa_consumo(tmp_path):
    lineas = [LineaEntrada(dt.date(2026, 1, 2), "A1", "1", "LECHE", "Lácteos", 10, "UN")]
    inf = calcular_informe(
        lineas, [], dt.date(2026, 1, 1), dt.date(2026, 1, 31), 61, None, "", {}, {},
        (None, None), dt.date(2026, 10, 27), dt.date(2026, 11, 1),
    )
    assert inf.sin_registro
    assert inf.balance[0].entradas == 10 and inf.balance[0].consumo == 0
    assert destino(inf) == []
    ruta = escribir_pdf(inf, ruta_pdf(tmp_path, 2026, 1), dt.date(2026, 11, 1))
    texto = "".join(p.get_text() for p in fitz.open(ruta))
    assert "27/10/2026" in texto and "01/11/2026" in texto
    assert len(fitz.open(ruta)) == 2


def test_primer_mes_de_registro_arranca_de_cero():
    lineas = [
        LineaEntrada(dt.date(2026, 10, 5), "A0", "9", "ARROZ", "Despensa", 50, "UN"),
        LineaEntrada(dt.date(2026, 11, 3), "A1", "9", "ARROZ", "Despensa", 10, "UN"),
    ]
    inf = calcular_informe(
        lineas, [], dt.date(2026, 11, 1), dt.date(2026, 11, 30), 61, None, "", {}, {},
        (None, None), None, dt.date(2026, 11, 1),
    )
    assert not inf.sin_registro
    assert inf.balance[0].inicial == 0  # lo anterior a noviembre no cuenta


def test_comparar_albaranes_y_mover_fila():
    from trazabilidad.informes import comparar_albaranes
    from trazabilidad.revision import mover_fila

    faltan, sobran = comparar_albaranes(
        {"DON123420260105" "00001"}, "DON12342026010500001, DON12342026010600002"
    )
    assert faltan == ["12342026010600002"] and sobran == []
    import pandas as pd

    t = pd.DataFrame({"Código": ["a", "b", "c"]})
    assert list(mover_fila(t, 3, 1)["Código"]) == ["c", "a", "b"]
    assert list(mover_fila(t, 3, 1).index) == [1, 2, 3]


def test_almacen_y_anexo(tmp_path):
    from trazabilidad.informe_pdf import escribir_anexo, ruta_anexo

    cats = ["Despensa", "No comestibles", "Lácteos", "Carnes", "Fruta y verdura", "Pescado"]
    lineas = [
        LineaEntrada(dt.date(2026, 11, 1 + i), f"A{i}", str(i), "X", c, 10 + i, "UN")
        for i, c in enumerate(cats)
    ]
    inf = calcular_informe(
        lineas, [], dt.date(2026, 11, 1), dt.date(2026, 11, 30), 61, None, "x\n" * 12,
        {}, {}, (1001.64, 3197.58), dt.date(2026, 12, 1), dt.date(2026, 11, 1),
    )
    ruta = escribir_pdf(inf, ruta_pdf(tmp_path, 2026, 11), dt.date(2026, 11, 1))
    texto = "".join(p.get_text() for p in fitz.open(ruta))
    assert len(fitz.open(ruta)) == 2 and "Lo que se guarda en el almacén" in texto
    anexo = escribir_anexo(inf, ruta_anexo(tmp_path, 2026, 11))
    assert anexo.exists()


def test_informe_semanal_una_hoja(tmp_path):
    from trazabilidad.informe_pdf import escribir_pdf_semanal, ruta_semanal

    lineas = [LineaEntrada(dt.date(2026, 11, 3), "A1", "1", "LECHE", "Lácteos", 10, "UN")]
    lunes = dt.date(2026, 11, 2)
    inf = calcular_informe(
        lineas, [], lunes, dt.date(2026, 11, 8), 61, None, "", {}, {}, (None, None),
        dt.date(2026, 11, 9), dt.date(2026, 11, 1),
    )
    ruta = escribir_pdf_semanal(inf, ruta_semanal(tmp_path, lunes), dt.date(2026, 11, 1))
    texto = fitz.open(ruta)[0].get_text()
    assert len(fitz.open(ruta)) == 1 and "02/11/2026" in texto and "sin control" in texto
