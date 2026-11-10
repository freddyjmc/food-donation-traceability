import sqlite3

import pytest

from trazabilidad.registro import abrir_base


def test_crea_las_tres_tablas(tmp_path):
    con = abrir_base(tmp_path / "prueba.db")
    tablas = {f["name"] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"catalogo", "entradas", "salidas"} <= tablas


def test_rechaza_cantidad_cero(tmp_path):
    con = abrir_base(tmp_path / "prueba.db")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO entradas (fecha, num_albaran, codigo, descripcion, categoria,"
            " cantidad, unidad) VALUES ('2025-09-09', '1', '123', 'x', 'Lácteos', 0, 'ud')"
        )


def test_rechaza_motivo_desconocido(tmp_path):
    con = abrir_base(tmp_path / "prueba.db")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO salidas (fecha, categoria, unidades, motivo)"
            " VALUES ('2025-09-09', 'Lácteos', 1, 'regalo')"
        )
