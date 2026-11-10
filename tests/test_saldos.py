import datetime as dt

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trazabilidad.registro import Linea, abrir_base, guardar_albaran
from trazabilidad.saldos import (
    Entrada,
    Salida,
    SalidaExcedeExistencias,
    asignar_fifo,
    avisos_antiguos,
    cargar_pospuestos,
    cargar_vida_util,
    existencias,
    existencias_a_fecha,
    guardar_vida_util,
    posponer,
    registrar_salida,
    registrar_salidas,
    resumen_existencias,
)

D = dt.date


def entrada(dia, albaran, cantidad, categoria="Pan"):
    return Entrada(D(2025, 9, dia), albaran, categoria, cantidad)


def salida(dia, unidades, categoria="Pan", motivo="consumo"):
    return Salida(D(2025, 9, dia), categoria, unidades, motivo)


# ---------- reparto: el primero que entra es el primero que sale ----------


def test_descuenta_del_albaran_mas_antiguo_primero():
    entradas = [entrada(5, "B", 10), entrada(1, "A", 10)]  # desordenadas a propósito
    r = asignar_fifo(entradas, [salida(6, 12)])
    assert [(a.num_albaran, a.unidades) for a in r.asignaciones[0]] == [("A", 10), ("B", 2)]
    assert r.restante == [8, 0]  # mismo orden que la lista de entradas


def test_no_se_puede_gastar_lo_que_aun_no_ha_llegado():
    r = asignar_fifo([entrada(5, "B", 10)], [salida(3, 4)])
    assert r.sin_cubrir == [4]
    assert r.restante == [10]


def test_cada_categoria_va_por_separado():
    entradas = [entrada(1, "A", 10, "Pan"), entrada(1, "B", 10, "Lacteos")]
    r = asignar_fifo(entradas, [salida(2, 4, "Lacteos")])
    assert r.restante == [10, 6]


def test_fechas_desde_hasta_de_cada_albaran():
    r = asignar_fifo([entrada(1, "A", 10)], [salida(2, 3), salida(4, 3), salida(9, 4)])
    assert r.usos[("A", "Pan")] == (D(2025, 9, 2), D(2025, 9, 9))


def test_la_entrada_del_mismo_dia_cuenta():
    r = asignar_fifo([entrada(3, "A", 5)], [salida(3, 5)])
    assert r.sin_cubrir == [0]


# ---------- propiedades con salidas y entradas aleatorias ----------

fechas = st.dates(min_value=D(2025, 9, 1), max_value=D(2025, 9, 30))
categorias = st.sampled_from(["Pan", "Lacteos", "Carnes"])


@given(
    st.lists(st.tuples(fechas, categorias, st.integers(1, 50)), max_size=15),
    st.lists(st.tuples(fechas, categorias, st.integers(1, 80)), max_size=25),
)
def test_el_saldo_nunca_es_negativo_y_siempre_es_entradas_menos_salidas(datos_e, datos_s):
    entradas = [Entrada(f, f"A{i}", c, q) for i, (f, c, q) in enumerate(datos_e)]
    salidas = [Salida(f, c, u) for f, c, u in datos_s]
    r = asignar_fifo(entradas, salidas)

    assert all(quedan >= 0 for quedan in r.restante)
    for j, s in enumerate(salidas):  # cada salida: lo descontado + lo no cubierto = lo pedido
        assert sum(a.unidades for a in r.asignaciones[j]) + r.sin_cubrir[j] == s.unidades
    for categoria in {e.categoria for e in entradas}:
        recibido = sum(e.cantidad for e in entradas if e.categoria == categoria)
        pares = zip(entradas, r.restante, strict=True)
        quedan = sum(q for e, q in pares if e.categoria == categoria)
        gastado = sum(
            a.unidades
            for j, s in enumerate(salidas)
            if s.categoria == categoria
            for a in r.asignaciones[j]
        )
        assert quedan == recibido - gastado  # el saldo es entradas menos salidas


# ---------- avisos de existencias antiguas ----------


def test_avisa_de_lo_que_lleva_mas_dias_de_los_esperados():
    entradas = [entrada(1, "A", 10, "Carnes Y"), entrada(25, "B", 10, "Carnes Y")]
    r = asignar_fifo(entradas, [salida(5, 4, "Carnes Y")])
    avisos = avisos_antiguos(entradas, r, hoy=D(2025, 9, 28), vida_util={"Carnes Y": 14})
    assert [(a.num_albaran, a.unidades, a.dias) for a in avisos] == [("A", 6, 27)]


def test_no_avisa_si_ya_se_gasto_todo_o_la_categoria_no_tiene_limite():
    entradas = [entrada(1, "A", 10, "Carnes Y"), entrada(1, "B", 10, "Sin limite")]
    r = asignar_fifo(entradas, [salida(5, 10, "Carnes Y")])
    assert avisos_antiguos(entradas, r, D(2025, 12, 1), {"Carnes Y": 14}) == []


# ---------- con la base de datos ----------


@pytest.fixture
def con(tmp_path):
    con = abrir_base(tmp_path / "p.db")
    for fecha, albaran, cantidad in [("2025-09-01", "A1", 10), ("2025-09-05", "A2", 10)]:
        con.execute(
            "INSERT INTO entradas (fecha, num_albaran, codigo, descripcion, categoria, cantidad,"
            " unidad) VALUES (?, ?, '1', 'x', 'Pan', ?, 'UN')",
            (fecha, albaran, cantidad),
        )
    return con


def test_registrar_salida_y_existencias(con):
    registrar_salida(con, D(2025, 9, 6), "Pan", 12)
    assert existencias(con) == {("Pan", "UN"): 8}


def test_salida_mayor_que_las_existencias_se_rechaza_y_no_se_guarda(con):
    with pytest.raises(SalidaExcedeExistencias):
        registrar_salida(con, D(2025, 9, 6), "Pan", 21)
    assert con.execute("SELECT COUNT(*) FROM salidas").fetchone()[0] == 0


def test_salida_anotada_con_fecha_anterior_que_deja_otra_sin_cubrir_se_rechaza(con):
    registrar_salida(con, D(2025, 9, 6), "Pan", 20)
    with pytest.raises(SalidaExcedeExistencias):
        registrar_salida(con, D(2025, 9, 2), "Pan", 8)  # el 2 solo había 10 y ya se usan en el 6


def test_motivo_y_unidades_invalidos(con):
    with pytest.raises(ValueError):
        registrar_salida(con, D(2025, 9, 6), "Pan", 1, motivo="regalo")
    with pytest.raises(ValueError):
        registrar_salida(con, D(2025, 9, 6), "Pan", 0)


def test_tirar_lo_caducado_se_anota_como_salida_con_su_motivo(con):
    registrar_salida(con, D(2025, 9, 20), "Pan", 10, motivo="caducado o desechado")
    fila = con.execute("SELECT motivo FROM salidas").fetchone()
    assert fila["motivo"] == "caducado o desechado"
    assert existencias(con) == {("Pan", "UN"): 10}


# ---------- paso 7b: varias salidas a la vez, existencias a una fecha, avisos pospuestos ----------

def test_varias_salidas_a_la_vez_son_todas_o_ninguna(con):
    buenas = Salida(D(2025, 9, 6), "Pan", 5)
    demasiadas = Salida(D(2025, 9, 6), "Pan", 99)
    with pytest.raises(SalidaExcedeExistencias):
        registrar_salidas(con, [buenas, demasiadas])
    assert con.execute("SELECT COUNT(*) FROM salidas").fetchone()[0] == 0  # ni la buena
    assert len(registrar_salidas(con, [buenas, Salida(D(2025, 9, 6), "Pan", 5, "otro")])) == 2


def test_existencias_a_una_fecha_ignora_lo_posterior():
    entradas = [entrada(1, "A", 10), entrada(5, "B", 10)]
    salidas = [salida(3, 4), salida(8, 6)]
    assert existencias_a_fecha(entradas, salidas, D(2025, 9, 2)) == {("Pan", "UN"): 10}
    assert existencias_a_fecha(entradas, salidas, D(2025, 9, 4)) == {("Pan", "UN"): 6}
    assert existencias_a_fecha(entradas, salidas, D(2025, 9, 30)) == {("Pan", "UN"): 10}


def test_resumen_muestra_el_albaran_mas_antiguo_con_unidades():
    entradas = [entrada(1, "A", 10), entrada(5, "B", 10), entrada(2, "C", 3, "Lacteos")]
    r = asignar_fifo(entradas, [salida(6, 10)])  # se gasta todo A
    resumen = resumen_existencias(entradas, r, D(2025, 9, 10))
    assert [(f["categoria"], f["unidades"], f["albaran"], f["dias"]) for f in resumen] == [
        ("Lacteos", 3, "C", 8),
        ("Pan", 10, "B", 5),
    ]


def test_un_aviso_pospuesto_no_sale_hasta_que_pasa_la_fecha():
    entradas = [entrada(1, "A", 10, "Carnes Y")]
    r = asignar_fifo(entradas, [])
    limite = {"Carnes Y": 14}
    pospuesto = {("A", "Carnes Y"): D(2025, 9, 25)}
    assert avisos_antiguos(entradas, r, D(2025, 9, 20), limite, pospuesto) == []
    assert len(avisos_antiguos(entradas, r, D(2025, 9, 26), limite, pospuesto)) == 1


def test_posponer_se_guarda_en_la_base(con):
    posponer(con, "A1", "Pan", D(2025, 10, 1))
    assert cargar_pospuestos(con) == {("A1", "Pan"): D(2025, 10, 1)}


def test_vida_util_cambiada_se_guarda_sobre_la_de_por_defecto(con):
    assert cargar_vida_util(con)["Pescados y Mariscos"] == 5
    guardar_vida_util(con, {"Pescados y Mariscos": 4})
    assert cargar_vida_util(con)["Pescados y Mariscos"] == 4
    assert cargar_vida_util(con)["Carnes y Embutidos"] == 14


def test_unidades_y_kilos_no_se_mezclan(con):
    guardar_albaran(
        con, D(2025, 9, 1), "DON12342025090100099",
        [Linea(codigo="3649", descripcion="CIRUELA", cantidad=0.834, unidad="KG"),
         Linea(codigo="69435", descripcion="ROMANA", cantidad=13, unidad="UN")],
        categorias_elegidas={"3649": "Frutas y Verduras", "69435": "Frutas y Verduras"},
    )
    ahora = existencias(con)
    assert ahora[("Frutas y Verduras", "KG")] == pytest.approx(0.834)
    assert ahora[("Frutas y Verduras", "UN")] == 13
    registrar_salida(con, D(2025, 9, 2), "Frutas y Verduras", 5, unidad="UN")
    with pytest.raises(SalidaExcedeExistencias):
        registrar_salida(con, D(2025, 9, 2), "Frutas y Verduras", 1, unidad="KG")
    assert existencias(con)[("Frutas y Verduras", "UN")] == 8


def test_base_antigua_sin_columna_unidad_se_actualiza(tmp_path):
    import sqlite3

    ruta = tmp_path / "vieja.db"
    antigua = sqlite3.connect(ruta)
    antigua.execute(
        "CREATE TABLE salidas (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL,"
        " categoria TEXT NOT NULL, unidades REAL NOT NULL, motivo TEXT NOT NULL)"
    )
    antigua.execute("INSERT INTO salidas (fecha, categoria, unidades, motivo)"
                    " VALUES ('2025-09-01', 'Pan', 2, 'consumo')")
    antigua.commit()
    antigua.close()
    con = abrir_base(ruta)
    assert con.execute("SELECT unidad FROM salidas").fetchone()[0] == "UN"
