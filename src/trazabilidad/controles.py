"""Control diario de aptitud y recuento de lo almacenado a fin de mes.

Cada día la cocina responde: ¿se ha tirado algo? Eso deja un registro fechado (el control) y,
si se tiró algo, las salidas por «caducado o desechado». El recuento de fin de mes recoge lo
que sigue almacenado de lo que no se consume enseguida (despensa y no comestibles).
"""

import datetime as dt
import sqlite3
from dataclasses import dataclass

from trazabilidad.saldos import Salida, registrar_salidas

# Lo que se almacena y se usa según necesidad: no se da por consumido al llegar.
ALMACENABLES = ("Despensa", "No comestibles")


@dataclass(frozen=True)
class Control:
    fecha: dt.date
    hubo_desecho: bool
    responsable: str
    nota: str


def guardar_control(
    con: sqlite3.Connection,
    fecha: dt.date,
    desechos: list[Salida],
    responsable: str = "",
    nota: str = "",
) -> None:
    """Anota el control del día. Con `desechos` vacío significa «hoy no se tiró nada».

    Si ese día ya había control, se actualiza (y los desechos nuevos se suman a los anteriores).
    Es atómico: si algún desecho no cabe en las existencias, no se guarda nada.
    """
    for desecho in desechos:
        if desecho.fecha != fecha or desecho.motivo != "caducado o desechado":
            raise ValueError("Los desechos del control deben ser del mismo día y de ese motivo")
    if desechos:
        registrar_salidas(con, desechos)  # valida y guarda (atómico por sí mismo)
    anterior = con.execute(
        "SELECT hubo_desecho FROM controles WHERE fecha = ?", (fecha.isoformat(),)
    ).fetchone()
    hubo = bool(desechos) or bool(anterior and anterior[0])
    with con:
        con.execute(
            "INSERT OR REPLACE INTO controles (fecha, hubo_desecho, responsable, nota)"
            " VALUES (?, ?, ?, ?)",
            (fecha.isoformat(), int(hubo), responsable.strip(), nota.strip()),
        )


def cargar_controles(con: sqlite3.Connection) -> dict[dt.date, Control]:
    filas = con.execute("SELECT fecha, hubo_desecho, responsable, nota FROM controles")
    return {
        dt.date.fromisoformat(f[0]): Control(dt.date.fromisoformat(f[0]), bool(f[1]), f[2], f[3])
        for f in filas
    }


def _clave_mes(mes: dt.date) -> str:
    return f"{mes.year}-{mes.month:02d}"


def guardar_recuento(
    con: sqlite3.Connection, mes: dt.date, categoria: str, unidad: str, cantidad: float
) -> None:
    """Lo que queda almacenado al cerrar el mes (de la categoría y unidad indicadas)."""
    if cantidad < 0:
        raise ValueError("La cantidad no puede ser negativa")
    with con:
        con.execute(
            "INSERT OR REPLACE INTO recuentos (mes, categoria, unidad, cantidad)"
            " VALUES (?, ?, ?, ?)",
            (_clave_mes(mes), categoria, unidad.upper().strip(), float(cantidad)),
        )


def cargar_recuentos(con: sqlite3.Connection) -> dict[tuple[str, str, str], float]:
    """{(mes 'AAAA-MM', categoría, unidad): cantidad}"""
    filas = con.execute("SELECT mes, categoria, unidad, cantidad FROM recuentos")
    return {(f[0], f[1], f[2]): f[3] for f in filas}


def clave_mes(mes: dt.date) -> str:
    return _clave_mes(mes)
