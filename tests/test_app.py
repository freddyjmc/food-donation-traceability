from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).parents[1] / "src" / "trazabilidad" / "app.py"


def test_la_pantalla_arranca_sin_errores(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAZABILIDAD_DATOS", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Registro de trazabilidad de donaciones"
    assert [t.label for t in app.tabs] == [
        "Subir albarán",
        "Control del día",
        "Informes",
        "Informe del mes",
        "Informe de la semana",
        "Más opciones",
        "Existencias y avisos",
        "Anotar consumo (detalle)",
        "Entradas guardadas",
        "Productos",
    ]


def test_flujo_sencillo_control_del_dia_e_informe(tmp_path, monkeypatch):
    import datetime as dt

    from trazabilidad.registro import Linea, abrir_base, guardar_albaran

    monkeypatch.setenv("TRAZABILIDAD_DATOS", str(tmp_path))
    hoy = dt.date.today()
    con = abrir_base(tmp_path / "registro.db")
    guardar_albaran(
        con, hoy, f"DON1234{hoy:%Y%m%d}00001",
        [Linea(codigo="1", descripcion="PAN", cantidad=10, unidad="UN"),
         Linea(codigo="2", descripcion="ARROZ", cantidad=5, unidad="UN")],
        categorias_elegidas={"1": "Panadería y bollería", "2": "Despensa"},
    )
    con.close()
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    [b for b in app.button if b.label == "Guardar control del día"][0].click()
    app.run()
    assert not app.exception
    assert any("guardado" in m.value for m in app.success)
    [b for b in app.button if b.label == "Crear informe"][0].click()
    app.run()
    assert not app.exception
    assert (tmp_path / "informes").exists()


def test_borrar_un_albaran_desde_la_pantalla(tmp_path, monkeypatch):
    import datetime as dt

    from trazabilidad.registro import Linea, abrir_base, guardar_albaran

    monkeypatch.setenv("TRAZABILIDAD_DATOS", str(tmp_path))
    con = abrir_base(tmp_path / "registro.db")
    guardar_albaran(
        con, dt.date(2026, 10, 9), "DON12342026100900001",
        [Linea(codigo="1", descripcion="PAN", cantidad=10, unidad="UN")],
        categorias_elegidas={"1": "Panadería y bollería"},
    )
    con.close()
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    boton = [b for b in app.button if b.label == "Borrar albarán"][0]
    assert boton.disabled
    app.checkbox(key="seguro_borrar").check().run()
    [b for b in app.button if b.label == "Borrar albarán"][0].click()
    app.run()
    assert not app.exception
    con = abrir_base(tmp_path / "registro.db")
    assert con.execute("SELECT COUNT(*) FROM entradas").fetchone()[0] == 0
    assert list((tmp_path / "copias").glob("*.db"))


def test_borrar_albaran_con_desechos_ofrece_borrarlos_tambien(tmp_path, monkeypatch):
    import datetime as dt

    from trazabilidad.controles import guardar_control
    from trazabilidad.registro import Linea, abrir_base, guardar_albaran
    from trazabilidad.saldos import Salida

    monkeypatch.setenv("TRAZABILIDAD_DATOS", str(tmp_path))
    dia = dt.date(2026, 10, 9)
    con = abrir_base(tmp_path / "registro.db")
    guardar_albaran(
        con, dia, "DON12342026100900001",
        [Linea(codigo="1", descripcion="PAN", cantidad=10, unidad="UN")],
        categorias_elegidas={"1": "Panadería y bollería"},
    )
    guardar_control(con, dia, [Salida(dia, "Panadería y bollería", 2, "caducado o desechado")])
    con.close()
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.checkbox(key="seguro_borrar").check().run()
    [b for b in app.button if b.label == "Borrar albarán"][0].click()
    app.run()
    assert any("Borrar albarán y sus movimientos" == b.label for b in app.button)
    app.checkbox(key="seguro_forzar").check().run()
    [b for b in app.button if b.label == "Borrar albarán y sus movimientos"][0].click()
    app.run()
    assert not app.exception
    con = abrir_base(tmp_path / "registro.db")
    assert con.execute("SELECT COUNT(*) FROM entradas").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM salidas").fetchone()[0] == 0


def test_copia_en_servidor_desde_la_barra_lateral(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAZABILIDAD_DATOS", str(tmp_path / "datos"))
    destino = tmp_path / "servidor" / "Registro"
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.sidebar.text_input[0].set_value(str(destino)).run()
    assert not app.exception
    assert any("Copia hecha" in m.value for m in app.sidebar.success)
    assert list((destino / "copias_seguridad").glob("registro_*.db"))
    app.sidebar.text_input[0].set_value("/ruta/que/no/existe/\0mal").run()
    assert not app.exception
