import csv
import datetime as dt

import openpyxl

from trazabilidad.cargar_catalogo import cargar
from trazabilidad.registro import abrir_base


def excel_de_prueba(ruta):
    libro = openpyxl.Workbook()
    pan = libro.active
    pan.title = "Panadería y bollería "
    pan["A16"], pan["C16"] = dt.datetime(2025, 9, 1), 4912
    carnes = libro.create_sheet("Carnes y Embutidos")
    carnes["A16"], carnes["C16"] = dt.datetime(2025, 9, 5), 4912
    carnes["C17"] = 2635
    libro.save(ruta)


def test_carga_el_catalogo_y_guarda_los_conflictos(tmp_path):
    excel_de_prueba(tmp_path / "e.xlsx")
    resultado = cargar(tmp_path / "e.xlsx", tmp_path / "datos")
    assert (resultado["lineas"], resultado["codigos"], resultado["conflictos"]) == (3, 2, 1)
    con = abrir_base(tmp_path / "datos" / "registro.db")
    assert con.execute("SELECT COUNT(*) FROM catalogo").fetchone()[0] == 2
    with open(resultado["csv"], encoding="utf-8-sig") as archivo:
        filas = list(csv.reader(archivo, delimiter=";"))
    assert filas[1][:2] == ["4912", "Carnes y Embutidos"]


def test_cargar_dos_veces_no_duplica(tmp_path):
    excel_de_prueba(tmp_path / "e.xlsx")
    cargar(tmp_path / "e.xlsx", tmp_path / "datos")
    assert cargar(tmp_path / "e.xlsx", tmp_path / "datos")["anadidos"] == 0
