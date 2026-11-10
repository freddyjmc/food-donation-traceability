import datetime as dt

import pytest

from trazabilidad.categorizar import sugerir_categoria
from trazabilidad.parser import Albaran
from trazabilidad.registro import Linea, abrir_base, guardar_albaran
from trazabilidad.revision import preparar_revision


@pytest.fixture
def con():
    return abrir_base(":memory:")


@pytest.mark.parametrize(
    ("descripcion", "categoria"),
    [
        ("YOGUR LIQUIDO FRESA", "Lacteos y Huevos"),
        ("NATILLA C/GALLETA X4", "Lacteos y Huevos"),
        ("CROISSANT CACAO", "Panadería y bollería"),
        ("BERLINA AZUCAR", "Panadería y bollería"),
        ("RABO CERDO", "Carnes y Embutidos"),
        ("ATUN CLARO GIRAS PK6", "Despensa"),
        ("SAL FINA", "Despensa"),
        ("SALMOREJO FRESCO", "Comida preparada y congelados"),
        ("ENSALADA JAMON", "Comida preparada y congelados"),
        ("ENSALADA CALIFORNIA", "Frutas y Verduras"),
        ("TOMATE NEGRO BANDEJA", "Frutas y Verduras"),
        ("ISOTONICO NARANJA", "Bebida y Snacks"),
        ("SERVILLETAS PAPEL", "No comestibles"),
    ],
)
def test_sugiere_por_palabras_clave(con, descripcion, categoria):
    assert sugerir_categoria(con, descripcion)[0] == categoria


def test_no_inventa_si_no_sabe(con):
    assert sugerir_categoria(con, "RESERVA TACOS-M") is None
    assert sugerir_categoria(con, "") is None


def test_aprende_de_lo_ya_guardado(con):
    for n, (codigo, desc) in enumerate([("111", "XYZZY UNO"), ("222", "XYZZY DOS")], 1):
        guardar_albaran(
            con, dt.date(2026, 10, n), f"DON12342026100{n}00001",
            [Linea(codigo=codigo, descripcion=desc, cantidad=1, unidad="UN")],
            categorias_elegidas={codigo: "Despensa"},
        )
    categoria, explicacion = sugerir_categoria(con, "XYZZY TRES")
    assert categoria == "Despensa"
    assert "anteriores" in explicacion


def test_la_revision_marca_las_sugeridas(con):
    albaran = Albaran(
        fecha=None, num_albaran=None,
        lineas=[Linea(codigo="1", descripcion="FLAN VAINILLA", cantidad=2, unidad="UN"),
                Linea(codigo="2", descripcion="RESERVA TACOS-M", cantidad=1, unidad="UN")],
    )
    tabla = preparar_revision(albaran, con)
    assert list(tabla["Estado"]) == ["Sugerida", "Nuevo"]
    assert tabla.loc[0, "Categoría"] == "Lacteos y Huevos"
    assert tabla["Categoría"].isna().tolist() == [False, True]
