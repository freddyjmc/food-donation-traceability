import datetime as dt

import pytest

from trazabilidad.controles import guardar_control, guardar_recuento
from trazabilidad.limpiar import (
    BorradoNoPermitido,
    borrar_albaran,
    borrar_todo_lo_de_prueba,
    copia_de_seguridad,
)
from trazabilidad.registro import Linea, abrir_base, guardar_albaran
from trazabilidad.saldos import Salida

D = dt.date
PAN = "Panadería y bollería"


@pytest.fixture
def con(tmp_path):
    con = abrir_base(tmp_path / "registro.db")
    for n, num in enumerate(["DON12342026100100001", "DON12342026100200001"], start=1):
        guardar_albaran(
            con, D(2026, 10, n), num,
            [Linea(codigo="1", descripcion="PAN", cantidad=10, unidad="UN")],
            enlace_pdf=f"pdf_archivo/{num}.pdf", categorias_elegidas={"1": PAN},
        )
    return con


def test_borra_un_albaran_y_conserva_el_catalogo(con):
    borradas, pdf = borrar_albaran(con, "DON12342026100100001")
    assert borradas == 1 and pdf.endswith("DON12342026100100001.pdf")
    assert con.execute("SELECT COUNT(*) FROM entradas").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM catalogo").fetchone()[0] == 1


def test_albaran_inexistente(con):
    with pytest.raises(BorradoNoPermitido):
        borrar_albaran(con, "DON12342026109900001")


def test_no_borra_si_dejaria_desechos_sin_cubrir(con):
    guardar_control(con, D(2026, 10, 2), [Salida(D(2026, 10, 2), PAN, 15, "caducado o desechado")])
    with pytest.raises(BorradoNoPermitido):
        borrar_albaran(con, "DON12342026100100001")
    assert con.execute("SELECT COUNT(*) FROM entradas").fetchone()[0] == 2


def test_todo_lo_de_prueba_vacia_movimientos_y_deja_el_catalogo(con):
    guardar_control(con, D(2026, 10, 2), [Salida(D(2026, 10, 2), PAN, 1, "caducado o desechado")])
    guardar_recuento(con, D(2026, 10, 31), "Despensa", "UN", 3)
    borrado = borrar_todo_lo_de_prueba(con)
    assert borrado["entradas"] == 2 and borrado["salidas"] == 1 and borrado["controles"] == 1
    for tabla in ("entradas", "salidas", "controles", "recuentos"):
        assert con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM catalogo").fetchone()[0] == 1


def test_copia_de_seguridad(tmp_path, con):
    copia = copia_de_seguridad(tmp_path / "registro.db")
    assert copia.exists() and copia.parent.name == "copias"


def test_borrar_control_quita_sus_desechos(con):
    from trazabilidad.limpiar import borrar_control

    guardar_control(con, D(2026, 10, 2), [Salida(D(2026, 10, 2), PAN, 3, "caducado o desechado")])
    assert borrar_control(con, D(2026, 10, 2)) == 1
    assert con.execute("SELECT COUNT(*) FROM controles").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM salidas").fetchone()[0] == 0
    with pytest.raises(BorradoNoPermitido):
        borrar_control(con, D(2026, 10, 2))


def test_apartar_pdf_lo_mueve_sin_destruirlo(tmp_path):
    from trazabilidad.limpiar import apartar_pdf

    pdf = tmp_path / "pdf_archivo" / "2026-10" / "DON1.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"x")
    nuevo = apartar_pdf(tmp_path, "pdf_archivo/2026-10/DON1.pdf")
    assert not pdf.exists() and nuevo.exists() and nuevo.parent.name == "_borrados"
    assert apartar_pdf(tmp_path, None) is None
    assert apartar_pdf(tmp_path, "pdf_archivo/no_existe.pdf") is None


def test_borrar_albaran_con_movimientos_quita_lo_que_depende(con):
    from trazabilidad.limpiar import borrar_albaran_con_movimientos

    guardar_control(con, D(2026, 10, 2), [Salida(D(2026, 10, 2), PAN, 15, "caducado o desechado")])
    with pytest.raises(BorradoNoPermitido):
        borrar_albaran(con, "DON12342026100100001")
    borradas, _, salidas = borrar_albaran_con_movimientos(con, "DON12342026100100001")
    assert (borradas, salidas) == (1, 1)
    assert con.execute("SELECT COUNT(*) FROM controles").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM entradas").fetchone()[0] == 1
