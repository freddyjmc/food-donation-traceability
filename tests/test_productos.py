import datetime as dt

import pytest

from trazabilidad.productos import CambioNoPermitido, buscar_productos, cambiar_categoria
from trazabilidad.registro import Linea, abrir_base, guardar_albaran
from trazabilidad.saldos import registrar_salida


@pytest.fixture
def con():
    con = abrir_base(":memory:")
    guardar_albaran(
        con, dt.date(2025, 10, 9), "DON12342025100900001",
        [Linea(codigo="69741", descripcion="GOURMET MAXI", cantidad=3, unidad="UN")],
        categorias_elegidas={"69741": "Carnes y Embutidos"},
    )
    return con


def test_busca_por_nombre_y_codigo(con):
    assert buscar_productos(con, "gourmet")[0]["codigo"] == "69741"
    assert buscar_productos(con, "6974")[0]["descripcion"] == "GOURMET MAXI"
    assert buscar_productos(con, "no existe") == []


def test_cambia_catalogo_y_entradas(con):
    assert cambiar_categoria(con, "69741", "Comida preparada y congelados") == 1
    assert con.execute("SELECT categoria FROM catalogo").fetchone()[0].startswith("Comida")
    assert con.execute("SELECT categoria FROM entradas").fetchone()[0].startswith("Comida")


def test_no_deja_salidas_sin_cubrir_y_deshace(con):
    registrar_salida(con, dt.date(2025, 10, 10), "Carnes y Embutidos", 2, "consumo")
    with pytest.raises(CambioNoPermitido):
        cambiar_categoria(con, "69741", "Comida preparada y congelados")
    assert con.execute("SELECT categoria FROM entradas").fetchone()[0] == "Carnes y Embutidos"
    assert con.execute("SELECT categoria FROM catalogo").fetchone()[0] == "Carnes y Embutidos"
