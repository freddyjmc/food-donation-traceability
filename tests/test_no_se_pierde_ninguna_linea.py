"""Propiedad principal: una línea con código y unidad NUNCA desaparece del albarán leído."""

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trazabilidad.parser import leer_albaran
from trazabilidad.registro import abrir_base
from trazabilidad.revision import preparar_revision

DESCRIPCION = st.from_regex(r"[A-Z][A-Z0-9%/.,]{2,9}( [A-Z0-9%]{1,8}){0,3}", fullmatch=True)
CANTIDAD = st.one_of(
    st.integers(1, 99).map(str),
    st.sampled_from(["1,000", "12,000", "0,834", "{", "|", "-", "a", "L", "q", "~", "“", "é", ""]),
)
UNIDAD = st.sampled_from(["UN", "KG"])
ADORNO = st.sampled_from(["", " ", "| ", "~ ", "ie ", "j "])


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    return abrir_base(tmp_path_factory.mktemp("p") / "p.db")


@settings(max_examples=300, deadline=None)
@given(
    filas=st.lists(
        st.tuples(ADORNO, st.integers(100, 99999).map(str), DESCRIPCION, CANTIDAD, UNIDAD),
        min_size=1, max_size=12,
    )
)
def test_ninguna_fila_se_descarta(con, filas):
    texto = "Fecha: 05-05-2026 DON12342026050500001\n" + "\n".join(
        f"{adorno}{codigo} {descripcion} {cantidad} {unidad}".replace("  ", " ")
        for adorno, codigo, descripcion, cantidad, unidad in filas
    )
    albaran = leer_albaran(texto)
    assert len(albaran.lineas) + len(albaran.dudosas) == len(filas)
    tabla = preparar_revision(albaran, con)
    assert len(tabla) == len(filas)
    # las filas dudosas nunca dejan basura pegada al final de la descripción
    for _, fila in tabla[tabla["Estado"] == "Revisar"].iterrows():
        descripcion = str(fila["Descripción"])
        assert descripcion == descripcion.strip()
        assert not descripcion.endswith(("{", "|", "~", "“", "-"))


@pytest.mark.parametrize(
    ("texto", "codigo", "descripcion"),
    [
        ("84785 BERLINA CACAO 4 UDS a UN", "84785", "BERLINA CACAO 4 UDS"),
        ("14725 HOJALDRE PIZZA L UN", "14725", "HOJALDRE PIZZA"),
        ("68163 CHAMPIÑON GRANDE BAN q UN", "68163", "CHAMPIÑON GRANDE BAN"),
        ("67563 PAN QUESO 18% UN", "67563", "PAN QUESO 18%"),
        ("27326 COLA { UN", "27326", "COLA"),
        ("9220 PAN DE LA ABUELA UN", "9220", "PAN DE LA ABUELA"),
    ],
)
def test_filas_reales_con_cantidad_ilegible(con, texto, codigo, descripcion):
    albaran = leer_albaran("DON12342026050500001\n" + texto + "\n")
    assert albaran.dudosas == [texto] and not albaran.lineas
    fila = preparar_revision(albaran, con).iloc[0]
    assert fila["Código"] == codigo and fila["Descripción"] == descripcion
    assert pd.isna(fila["Cantidad"]) and fila["Estado"] == "Revisar"
    assert "Cantidad no leída" in fila["Nota"]


def test_las_filas_dudosas_conservan_su_posicion_en_el_albaran(con):
    texto = (
        "DON12342026050500001\n"
        "1001 ARROZ LARGO 2 UN\n"
        "27326 COLA { UN\n"
        "1002 LECHE ENTERA 6 UN\n"
        "14725 HOJALDRE PIZZA L UN\n"
        "1003 YOGUR NATURAL 3 UN\n"
    )
    tabla = preparar_revision(leer_albaran(texto), con)
    assert list(tabla["Código"]) == ["1001", "27326", "1002", "14725", "1003"]
