import datetime as dt

import pytest

from trazabilidad.controles import (
    cargar_controles,
    cargar_recuentos,
    guardar_control,
    guardar_recuento,
)
from trazabilidad.registro import Linea, abrir_base, guardar_albaran
from trazabilidad.saldos import Salida, SalidaExcedeExistencias, existencias

D = dt.date
PAN = "Panadería y bollería"


@pytest.fixture
def con():
    con = abrir_base(":memory:")
    guardar_albaran(
        con, D(2026, 10, 9), "DON12342026100900001",
        [Linea(codigo="1", descripcion="PAN", cantidad=10, unidad="UN")],
        categorias_elegidas={"1": PAN},
    )
    return con


def tirado(unidades):
    return Salida(D(2026, 10, 9), PAN, unidades, "caducado o desechado")


def test_control_sin_desecho(con):
    guardar_control(con, D(2026, 10, 9), [], "Ana", "todo bien")
    control = cargar_controles(con)[D(2026, 10, 9)]
    assert (control.hubo_desecho, control.responsable, control.nota) == (False, "Ana", "todo bien")


def test_control_con_desecho_descuenta_existencias(con):
    guardar_control(con, D(2026, 10, 9), [tirado(3)], "Ana")
    assert cargar_controles(con)[D(2026, 10, 9)].hubo_desecho
    assert existencias(con)[(PAN, "UN")] == 7


def test_desecho_mayor_que_lo_recibido_se_rechaza_y_no_deja_control(con):
    with pytest.raises(SalidaExcedeExistencias):
        guardar_control(con, D(2026, 10, 9), [tirado(99)], "Ana")
    assert cargar_controles(con) == {}


def test_segundo_control_del_dia_suma_desechos_y_mantiene_que_hubo(con):
    guardar_control(con, D(2026, 10, 9), [tirado(1)], "Ana")
    guardar_control(con, D(2026, 10, 9), [], "Ana", "revisado otra vez")
    assert cargar_controles(con)[D(2026, 10, 9)].hubo_desecho
    assert existencias(con)[(PAN, "UN")] == 9


def test_desecho_de_otro_dia_o_motivo_no_vale(con):
    with pytest.raises(ValueError):
        guardar_control(con, D(2026, 10, 10), [tirado(1)])
    with pytest.raises(ValueError):
        guardar_control(con, D(2026, 10, 9), [Salida(D(2026, 10, 9), PAN, 1, "consumo")])


def test_recuentos(con):
    guardar_recuento(con, D(2026, 10, 31), "Despensa", "un", 12)
    guardar_recuento(con, D(2026, 10, 1), "Despensa", "UN", 14)  # mismo mes: sustituye
    assert cargar_recuentos(con) == {("2026-10", "Despensa", "UN"): 14}
    with pytest.raises(ValueError):
        guardar_recuento(con, D(2026, 10, 31), "Despensa", "UN", -1)
