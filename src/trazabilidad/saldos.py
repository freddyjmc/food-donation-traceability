"""Salidas y saldos: reparto "el primero que entra es el primero que sale" (FIFO). Paso 7.

El corazón son funciones puras (asignar_fifo, avisos_antiguos): reciben listas y devuelven
datos, sin base de datos, para poder probarlas a fondo. Abajo van las que usan SQLite.
"""

import datetime as dt
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from trazabilidad.registro import MOTIVOS

# Días tras los cuales, si aún quedan unidades en existencias, se avisa para revisarlas.
# PROVISIONAL: son valores orientativos, ajustables a cada centro.
VIDA_UTIL_POR_DEFECTO = {
    "Comida preparada y congelados": 7,
    "Carnes y Embutidos": 14,
    "Frutas y Verduras": 21,
    "Despensa": 180,
    "Pescados y Mariscos": 5,
    "Panadería y bollería": 7,
    "Lacteos y Huevos": 7,
    "Bebida y Snacks": 7,
}


@dataclass(frozen=True)
class Entrada:
    """Unidades de una categoría que llegaron en un albarán."""

    fecha: dt.date
    num_albaran: str
    categoria: str
    cantidad: float
    unidad: str = "UN"


@dataclass(frozen=True)
class Salida:
    fecha: dt.date
    categoria: str
    unidades: float
    motivo: str = "consumo"
    id: int | None = None
    unidad: str = "UN"


@dataclass(frozen=True)
class Asignacion:
    """De qué albarán se descontaron unidades en una salida."""

    num_albaran: str
    unidades: float


@dataclass
class ResultadoFifo:
    restante: list[float]  # unidades que quedan de cada entrada (mismo orden que la lista)
    asignaciones: list[list[Asignacion]]  # por salida (mismo orden)
    sin_cubrir: list[float]  # por salida: unidades que no se pudieron descontar
    usos: dict[tuple[str, str], tuple[dt.date, dt.date]] = field(default_factory=dict)
    # usos: (albarán, categoría) -> (primer día, último día) en que se usó  ("desde-hasta")


@dataclass(frozen=True)
class Aviso:
    """Unidades que llevan más días en existencias de lo esperado para su categoría."""

    num_albaran: str
    categoria: str
    fecha_entrada: dt.date
    unidades: float
    dias: int
    limite: int
    unidad: str = "UN"


class SalidaExcedeExistencias(ValueError):
    """Se intenta anotar una salida mayor que las existencias disponibles."""


def asignar_fifo(entradas: list[Entrada], salidas: list[Salida]) -> ResultadoFifo:
    """Descuenta cada salida del albarán más antiguo de su categoría (y unidad: UN o KG)
    que ya hubiera llegado."""
    restante = [e.cantidad for e in entradas]
    cola: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, e in sorted(enumerate(entradas), key=lambda p: (p[1].fecha, p[1].num_albaran, p[0])):
        cola[(e.categoria, e.unidad)].append(i)

    resultado = ResultadoFifo(
        restante=restante,
        asignaciones=[[] for _ in salidas],
        sin_cubrir=[0.0] * len(salidas),
    )
    orden = sorted(enumerate(salidas), key=lambda p: (p[1].fecha, p[1].id or 0, p[0]))
    for j, salida in orden:
        falta = salida.unidades
        for i in cola[(salida.categoria, salida.unidad)]:
            if falta <= 0 or entradas[i].fecha > salida.fecha:
                break
            if restante[i] <= 0:
                continue
            usado = min(restante[i], falta)
            restante[i] -= usado
            falta -= usado
            clave = (entradas[i].num_albaran, entradas[i].categoria)
            resultado.asignaciones[j].append(Asignacion(entradas[i].num_albaran, usado))
            desde, hasta = resultado.usos.get(clave, (salida.fecha, salida.fecha))
            resultado.usos[clave] = (min(desde, salida.fecha), max(hasta, salida.fecha))
        resultado.sin_cubrir[j] = max(falta, 0.0)
    return resultado


def avisos_antiguos(
    entradas: list[Entrada],
    resultado: ResultadoFifo,
    hoy: dt.date,
    vida_util: dict[str, int] | None = None,
    pospuestos: dict[tuple[str, str], dt.date] | None = None,
) -> list[Aviso]:
    """Entradas con unidades pendientes más tiempo del esperado, las más antiguas primero.

    Los avisos pospuestos ("sigue en buen estado") no salen hasta que pasa su fecha.
    """
    limites = VIDA_UTIL_POR_DEFECTO if vida_util is None else vida_util
    pospuestos = pospuestos or {}
    avisos = []
    for entrada, quedan in zip(entradas, resultado.restante, strict=True):
        limite = limites.get(entrada.categoria)
        dias = (hoy - entrada.fecha).days
        hasta = pospuestos.get((entrada.num_albaran, entrada.categoria))
        if hasta is not None and hoy <= hasta:
            continue
        if quedan > 0 and limite is not None and dias > limite:
            avisos.append(
                Aviso(entrada.num_albaran, entrada.categoria, entrada.fecha, quedan, dias, limite,
                      entrada.unidad)
            )
    return sorted(avisos, key=lambda a: -a.dias)


# ---------- con la base de datos ----------


def cargar_entradas(con: sqlite3.Connection) -> list[Entrada]:
    """Una entrada por albarán y categoría (suma las líneas del mismo albarán)."""
    filas = con.execute(
        "SELECT fecha, num_albaran, categoria, upper(trim(unidad)), SUM(cantidad) FROM entradas"
        " GROUP BY fecha, num_albaran, categoria, upper(trim(unidad))"
    )
    return [Entrada(dt.date.fromisoformat(f[0]), f[1], f[2], f[4], f[3]) for f in filas]


def cargar_salidas(con: sqlite3.Connection) -> list[Salida]:
    filas = con.execute(
        "SELECT id, fecha, categoria, unidades, motivo, unidad FROM salidas ORDER BY id"
    )
    return [Salida(dt.date.fromisoformat(f[1]), f[2], f[3], f[4], f[0], f[5]) for f in filas]


def existencias_a_fecha(
    entradas: list[Entrada], salidas: list[Salida], fecha: dt.date
) -> dict[tuple[str, str], float]:
    """Disponible por (categoría, unidad) a una fecha (solo cuenta lo anterior o de ese día)."""
    hasta_fecha = [e for e in entradas if e.fecha <= fecha]
    resultado = asignar_fifo(hasta_fecha, [x for x in salidas if x.fecha <= fecha])
    total: dict[tuple[str, str], float] = defaultdict(float)
    for entrada, quedan in zip(hasta_fecha, resultado.restante, strict=True):
        total[(entrada.categoria, entrada.unidad)] += quedan
    return dict(total)


def existencias(con: sqlite3.Connection) -> dict[tuple[str, str], float]:
    """En existencias ahora mismo, por (categoría, unidad): entradas menos salidas."""
    return existencias_a_fecha(cargar_entradas(con), cargar_salidas(con), dt.date.max)


def resumen_existencias(
    entradas: list[Entrada], resultado: ResultadoFifo, hoy: dt.date
) -> list[dict]:
    """Por categoría y unidad con existencias, y el albarán más antiguo que aún tiene."""
    por_categoria: dict[tuple[str, str], dict] = {}
    for entrada, quedan in zip(entradas, resultado.restante, strict=True):
        if quedan <= 0:
            continue
        fila = por_categoria.setdefault(
            (entrada.categoria, entrada.unidad),
            {"categoria": entrada.categoria, "unidad": entrada.unidad, "unidades": 0.0,
             "fecha": entrada.fecha, "albaran": entrada.num_albaran},
        )
        fila["unidades"] += quedan
        if (entrada.fecha, entrada.num_albaran) < (fila["fecha"], fila["albaran"]):
            fila["fecha"], fila["albaran"] = entrada.fecha, entrada.num_albaran
    for fila in por_categoria.values():
        fila["dias"] = (hoy - fila["fecha"]).days
    return sorted(por_categoria.values(), key=lambda f: (f["categoria"], f["unidad"]))


def registrar_salidas(con: sqlite3.Connection, nuevas: list[Salida]) -> list[int]:
    """Anota varias salidas a la vez (todas o ninguna). Devuelve sus ids."""
    for salida in nuevas:
        if salida.motivo not in MOTIVOS:
            raise ValueError(f"Motivo no válido: {salida.motivo}. Opciones: {', '.join(MOTIVOS)}")
        if salida.unidades <= 0:
            raise ValueError("Las unidades deben ser mayores que 0")
    todas = [*cargar_salidas(con), *nuevas]
    resultado = asignar_fifo(cargar_entradas(con), todas)
    for salida, falta in zip(todas, resultado.sin_cubrir, strict=True):
        if falta > 0:
            raise SalidaExcedeExistencias(
                f"No hay suficiente de «{salida.categoria}» ({salida.unidad}) a fecha "
                f"{salida.fecha:%d/%m/%Y} (faltan {falta:g}). ¿Falta cargar algún albarán?"
            )
    ids = []
    with con:
        for salida in nuevas:
            cursor = con.execute(
                "INSERT INTO salidas (fecha, categoria, unidades, motivo, unidad)"
                " VALUES (?, ?, ?, ?, ?)",
                (salida.fecha.isoformat(), salida.categoria, salida.unidades, salida.motivo,
                 salida.unidad),
            )
            ids.append(int(cursor.lastrowid or 0))
    return ids


def registrar_salida(
    con: sqlite3.Connection,
    fecha: dt.date,
    categoria: str,
    unidades: float,
    motivo: str = "consumo",
    unidad: str = "UN",
) -> int:
    """Anota una salida si hay existencias suficientes. Devuelve su id."""
    return registrar_salidas(con, [Salida(fecha, categoria, unidades, motivo, unidad=unidad)])[0]


def posponer(con: sqlite3.Connection, num_albaran: str, categoria: str, hasta: dt.date) -> None:
    """'Sigue en buen estado': no volver a avisar de este albarán hasta esa fecha."""
    with con:
        con.execute(
            "INSERT OR REPLACE INTO pospuestos (num_albaran, categoria, hasta) VALUES (?, ?, ?)",
            (num_albaran, categoria, hasta.isoformat()),
        )


def cargar_pospuestos(con: sqlite3.Connection) -> dict[tuple[str, str], dt.date]:
    filas = con.execute("SELECT num_albaran, categoria, hasta FROM pospuestos")
    return {(f[0], f[1]): dt.date.fromisoformat(f[2]) for f in filas}


def cargar_vida_util(con: sqlite3.Connection) -> dict[str, int]:
    """Días de aviso por categoría: los de por defecto, cambiados por lo guardado en la base."""
    guardados = {f[0]: f[1] for f in con.execute("SELECT categoria, dias FROM vida_util")}
    return {**VIDA_UTIL_POR_DEFECTO, **guardados}


def guardar_vida_util(con: sqlite3.Connection, dias: dict[str, int]) -> None:
    with con:
        for categoria, valor in dias.items():
            con.execute(
                "INSERT OR REPLACE INTO vida_util (categoria, dias) VALUES (?, ?)",
                (categoria, int(valor)),
            )
