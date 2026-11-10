import datetime as dt

import pytest
from openpyxl import load_workbook

from trazabilidad.controles import Control
from trazabilidad.informe_excel import escribir_excel, ruta_informe
from trazabilidad.informes import (
    LineaEntrada,
    calcular_informe,
    cargar_lineas,
    cargar_personas,
    guardar_personas,
    limites_del_mes,
)
from trazabilidad.registro import Linea, abrir_base, guardar_albaran
from trazabilidad.saldos import Salida

D = dt.date
PAN = "Panadería y bollería"
FRUTA = "Frutas y Verduras"
DESPENSA = "Despensa"
OCT = (D(2026, 10, 1), D(2026, 10, 31))


def linea(dia, cantidad, categoria=PAN, unidad="UN", mes=10, codigo="1", num=None):
    f = D(2026, mes, dia)
    return LineaEntrada(f, num or f"DON12342026{mes:02d}{dia:02d}00001", codigo, "PRODUCTO",
                        categoria, cantidad, unidad)


def tirar(dia, unidades, categoria=PAN, unidad="UN", mes=10):
    return Salida(D(2026, mes, dia), categoria, unidades, "caducado o desechado", None, unidad)


def fila(informe, categoria, unidad="UN"):
    return next(f for f in informe.balance if (f.categoria, f.unidad) == (categoria, unidad))


def test_lo_perecedero_se_da_por_consumido_menos_lo_desechado():
    informe = calcular_informe([linea(2, 20), linea(5, 10)], [tirar(6, 2)], *OCT)
    pan = fila(informe, PAN)
    assert (pan.inicial, pan.entradas, pan.desechado, pan.final) == (0, 30, 2, 0)
    assert pan.consumo == 28
    assert informe.cuadra


def test_despensa_usa_el_recuento_del_mes_anterior_y_el_de_este_mes():
    lineas = [linea(3, 10, DESPENSA)]
    recuentos = {("2026-09", DESPENSA, "UN"): 4, ("2026-10", DESPENSA, "UN"): 6}
    informe = calcular_informe(lineas, [], *OCT, recuentos=recuentos)
    d = fila(informe, DESPENSA)
    assert (d.inicial, d.entradas, d.final, d.consumo) == (4, 10, 6, 8)
    assert not d.estimado


def test_despensa_sin_recuento_se_estima_y_se_avisa():
    informe = calcular_informe([linea(3, 10, DESPENSA)], [], *OCT)
    d = fila(informe, DESPENSA)
    assert d.estimado and d.final == 10 and d.consumo == 0
    assert any("Falta el recuento" in t for t in informe.incidencias)


def test_recuento_mayor_de_lo_posible_no_cuadra():
    informe = calcular_informe(
        [linea(3, 10, DESPENSA)], [], *OCT, recuentos={("2026-10", DESPENSA, "UN"): 50}
    )
    assert not informe.cuadra
    assert any("No cuadra" in t for t in informe.incidencias)


def test_unidades_y_kilos_van_separados():
    informe = calcular_informe(
        [linea(2, 13, FRUTA), linea(2, 0.834, FRUTA, "KG")], [tirar(3, 1, FRUTA)], *OCT
    )
    assert fila(informe, FRUTA, "UN").consumo == 12
    assert fila(informe, FRUTA, "KG").consumo == pytest.approx(0.834)


def test_consumo_por_persona_y_comparacion_con_meses_anteriores():
    lineas = [linea(1, 62), linea(1, 31, mes=9), linea(1, 30, mes=8), linea(1, 29, mes=7)]
    informe = calcular_informe(lineas, [], *OCT, personas=62)
    c = informe.consumo[0]
    assert c.total == 62 and c.media_diaria == 2
    assert c.por_persona_dia == pytest.approx(2 / 62, abs=1e-3)
    assert c.mes_anterior == 31
    assert c.media_3_meses == pytest.approx((31 + 30 + 29) / 3, abs=1e-3)


def test_controles_diarios_y_dias_sin_control():
    lineas = [linea(1, 5), linea(2, 5), linea(3, 5)]
    controles = {D(2026, 10, 1): Control(D(2026, 10, 1), False, "Ana", ""),
                 D(2026, 10, 2): Control(D(2026, 10, 2), True, "Ana", "fruta con moho")}
    informe = calcular_informe(lineas, [tirar(2, 1)], *OCT, controles=controles)
    assert informe.controles_hechos == 2 and informe.dias_con_desecho == 1
    assert informe.dias_sin_control == [D(2026, 10, 3)]
    assert any("sin control de aptitud: 1" in t for t in informe.incidencias)


def test_fecha_aproximada_de_consumo_por_albaran():
    lineas = [
        linea(1, 5, "Pescados y Mariscos", num="A1"), linea(1, 5, FRUTA, num="A1"),
        linea(2, 5, DESPENSA, num="A2"),
    ]
    detalle = calcular_informe(lineas, [], *OCT).detalle_albaranes
    uno, dos = detalle
    assert uno["consumir_antes"] == D(2026, 10, 6)  # el plazo más corto: pescado, 5 días
    assert dos["consumir_antes"] is None and dos["almacenable"]


def test_top_productos_y_semanas():
    informe = calcular_informe(
        [linea(1, 3, codigo="7"), linea(9, 9, codigo="8")], [tirar(10, 1)], *OCT
    )
    assert [p["codigo"] for p in informe.top_productos] == ["8", "7"]
    assert len(informe.semanas) == 5
    assert informe.semanas[1]["entradas"] == 9 and informe.semanas[1]["consumo"] == 8


def test_limites_del_mes():
    assert limites_del_mes(2028, 2) == (D(2028, 2, 1), D(2028, 2, 29))


def test_excel_se_escribe_y_tiene_las_hojas(tmp_path):
    informe = calcular_informe(
        [linea(2, 20), linea(5, 4, FRUTA, "KG")], [tirar(3, 2)], *OCT, comentarios="Nota de prueba",
        controles={D(2026, 10, 2): Control(D(2026, 10, 2), False, "Ana", "")},
    )
    ruta = escribir_excel(informe, ruta_informe(tmp_path, 2026, 10))
    assert ruta == tmp_path / "2026" / "2026-10.xlsx"
    libro = load_workbook(ruta)
    assert libro.sheetnames == [
        "Resumen", "Consumo", "Albaranes", "Entradas", "Salidas", "Control diario", "Incidencias",
    ]
    resumen = libro["Resumen"]
    assert "Octubre de 2026" in resumen["A3"].value
    assert len(resumen._charts) == 2
    textos = [c.value for f in resumen.iter_rows() for c in f if isinstance(c.value, str)]
    assert "Nota de prueba" in textos
    assert any(t.startswith("Declaración de la dirección") for t in textos)
    assert any("Control diario de aptitud: anotado en 1 de 31" in t for t in textos)
    assert libro["Entradas"].max_row == 3
    assert libro["Control diario"].max_row == 2


def test_personas_y_lineas_desde_la_base(tmp_path):
    con = abrir_base(tmp_path / "r.db")
    assert cargar_personas(con) == 50
    guardar_personas(con, 58)
    assert cargar_personas(con) == 58
    with pytest.raises(ValueError):
        guardar_personas(con, 0)
    guardar_albaran(
        con, D(2026, 10, 9), "DON12342026100900001",
        [Linea(codigo="1", descripcion="X", cantidad=2, unidad="un")],
        categorias_elegidas={"1": PAN},
    )
    assert cargar_lineas(con)[0].unidad == "UN"
