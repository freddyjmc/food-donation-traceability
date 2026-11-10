import datetime as dt

import openpyxl

from trazabilidad.catalogo import (
    cargar_catalogo,
    categoria_de,
    construir_catalogo,
    leer_codigos_excel,
    limpiar_categoria,
)
from trazabilidad.registro import abrir_base


def hacer_excel_de_prueba(ruta):
    """Excel mínimo con la misma forma que el Excel de partida: una hoja por categoría."""
    libro = openpyxl.Workbook()
    pan = libro.active
    pan.title = "Panadería y bollería "
    pan["A16"], pan["C16"] = dt.datetime(2025, 9, 1), 84692
    pan["C17"] = 4912  # sin fecha: hereda el 1 de septiembre
    pan["C18"] = "CÓDIGO"  # una cabecera repetida no es un código
    carnes = libro.create_sheet("Carnes y Embutidos")
    carnes["A16"], carnes["C16"] = dt.datetime(2025, 9, 5), 4912
    fruta = libro.create_sheet("Frutas y Verduras 🍏")
    fruta["A16"], fruta["C16"] = dt.datetime(2025, 9, 2), 69591
    libro.save(ruta)


def test_limpia_emojis_y_espacios():
    assert limpiar_categoria("Frutas y Verduras 🍏") == "Frutas y Verduras"
    assert limpiar_categoria("Panadería y bollería ") == "Panadería y bollería"


def test_lee_codigos_con_su_fecha_y_salta_cabeceras(tmp_path):
    ruta = tmp_path / "e.xlsx"
    hacer_excel_de_prueba(ruta)
    lineas = leer_codigos_excel(ruta)
    assert ("4912", "Panadería y bollería", dt.date(2025, 9, 1)) in lineas
    assert len(lineas) == 4


def test_codigo_en_dos_categorias_gana_la_mas_reciente(tmp_path):
    ruta = tmp_path / "e.xlsx"
    hacer_excel_de_prueba(ruta)
    catalogo, conflictos = construir_catalogo(leer_codigos_excel(ruta))
    assert catalogo["4912"] == "Carnes y Embutidos"
    assert set(conflictos["4912"]) == {"Panadería y bollería", "Carnes y Embutidos"}
    assert "69591" not in conflictos


def test_cargar_y_consultar_en_la_base(tmp_path):
    ruta = tmp_path / "e.xlsx"
    hacer_excel_de_prueba(ruta)
    catalogo, _ = construir_catalogo(leer_codigos_excel(ruta))
    con = abrir_base(tmp_path / "p.db")
    assert cargar_catalogo(con, catalogo) == 3
    assert categoria_de(con, "69591") == "Frutas y Verduras"
    assert categoria_de(con, "00000") is None
    assert cargar_catalogo(con, catalogo) == 0  # volver a cargar no duplica
