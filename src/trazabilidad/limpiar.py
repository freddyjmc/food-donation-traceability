"""Borrar datos de prueba con seguridad (siempre con copia previa de la base de datos).

Uso (desde la carpeta del proyecto, con el entorno activado, y con la app cerrada):
    python -m trazabilidad.limpiar albaran DON12342025100900001
    python -m trazabilidad.limpiar todo-lo-de-prueba

«todo-lo-de-prueba» deja la base vacía de movimientos (entradas, salidas, controles,
recuentos, avisos pospuestos) pero conserva el catálogo, los días de aviso y los ajustes.
"""

import datetime as dt
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from trazabilidad.registro import abrir_base
from trazabilidad.saldos import asignar_fifo, cargar_entradas, cargar_salidas

TABLAS_DE_MOVIMIENTOS = ("entradas", "salidas", "controles", "recuentos", "pospuestos")


class BorradoNoPermitido(ValueError):
    """El borrado dejaría el registro sin cuadrar o no hay nada que borrar."""


def copia_de_seguridad(ruta_base: Path) -> Path:
    """Copia la base de datos en datos/copias/ antes de tocar nada."""
    carpeta = ruta_base.parent / "copias"
    carpeta.mkdir(exist_ok=True)
    destino = carpeta / f"registro_antes_de_borrar_{dt.datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(ruta_base, destino)
    return destino


def borrar_albaran(
    con: sqlite3.Connection, num_albaran: str, con_movimientos: bool = False
) -> tuple[int, str | None]:
    """Borra todas las líneas del albarán. Devuelve (líneas borradas, enlace al PDF).

    Si ya hay desechos o consumos anotados que dependían de esas entradas y dejarían de
    cuadrar, lanza BorradoNoPermitido y no borra nada. Con `con_movimientos=True` borra también
    esos movimientos (y los controles de los días que se quedan sin desechos).
    """
    borradas, pdf, _ = _borrar_albaran(con, num_albaran, con_movimientos)
    return borradas, pdf


def borrar_albaran_con_movimientos(
    con: sqlite3.Connection, num_albaran: str
) -> tuple[int, str | None, int]:
    """Como borrar_albaran(..., con_movimientos=True) pero devuelve también cuántas salidas
    (desechos o consumos) se borraron."""
    return _borrar_albaran(con, num_albaran, True)


def _borrar_albaran(
    con: sqlite3.Connection, num_albaran: str, con_movimientos: bool
) -> tuple[int, str | None, int]:
    salidas_borradas = 0
    with con:
        pdf = con.execute(
            "SELECT enlace_pdf FROM entradas WHERE num_albaran = ? LIMIT 1", (num_albaran,)
        ).fetchone()
        borradas = con.execute(
            "DELETE FROM entradas WHERE num_albaran = ?", (num_albaran,)
        ).rowcount
        if not borradas:
            raise BorradoNoPermitido(f"No hay ningún albarán guardado con el número {num_albaran}")
        while True:
            salidas = cargar_salidas(con)
            resultado = asignar_fifo(cargar_entradas(con), salidas)
            sin_cubrir = [s for s, falta in zip(salidas, resultado.sin_cubrir, strict=True)
                          if falta > 1e-9]
            if not sin_cubrir:
                break
            if not con_movimientos:
                raise BorradoNoPermitido(
                    "Ya hay desechos o consumos anotados que dependen de ese albarán."
                )
            for salida in sin_cubrir:
                con.execute("DELETE FROM salidas WHERE id = ?", (salida.id,))
                salidas_borradas += 1
        if con_movimientos:  # controles que dicen «se tiró algo» pero ya no tienen desechos
            con.execute(
                "DELETE FROM controles WHERE hubo_desecho = 1 AND fecha NOT IN "
                "(SELECT fecha FROM salidas WHERE motivo = 'caducado o desechado')"
            )
        con.execute("DELETE FROM pospuestos WHERE num_albaran = ?", (num_albaran,))
    return borradas, pdf[0] if pdf else None, salidas_borradas


def borrar_control(con: sqlite3.Connection, fecha: dt.date) -> int:
    """Borra el control de ese día y los desechos anotados ese día. Devuelve cuántos desechos."""
    with con:
        existe = con.execute("DELETE FROM controles WHERE fecha = ?", (fecha.isoformat(),)).rowcount
        if not existe:
            raise BorradoNoPermitido(f"No hay control guardado el {fecha:%d/%m/%Y}")
        return con.execute(
            "DELETE FROM salidas WHERE fecha = ? AND motivo = 'caducado o desechado'",
            (fecha.isoformat(),),
        ).rowcount


def apartar_pdf(datos: Path, enlace_pdf: str | None) -> Path | None:
    """Mueve el PDF archivado de un albarán borrado a pdf_archivo/_borrados (no lo destruye).

    Así se puede volver a subir el mismo albarán corregido sin chocar con el archivo anterior.
    """
    if not enlace_pdf:
        return None
    origen = datos / enlace_pdf
    if not origen.exists():
        return None
    destino = datos / "pdf_archivo" / "_borrados"
    destino.mkdir(parents=True, exist_ok=True)
    nuevo = destino / f"{dt.datetime.now():%Y%m%d_%H%M%S}_{origen.name}"
    shutil.move(str(origen), nuevo)
    return nuevo


def borrar_todo_lo_de_prueba(con: sqlite3.Connection) -> dict[str, int]:
    """Vacía los movimientos (no el catálogo). Devuelve cuántas filas se borraron por tabla."""
    with con:
        return {
            tabla: con.execute(f"DELETE FROM {tabla}").rowcount  # noqa: S608 (nombres fijos)
            for tabla in TABLAS_DE_MOVIMIENTOS
        }


def main() -> None:
    uso = "Uso: python -m trazabilidad.limpiar albaran NUMERO | todo-lo-de-prueba"
    if len(sys.argv) < 2 or sys.argv[1] not in ("albaran", "todo-lo-de-prueba"):
        sys.exit(uso)
    if sys.argv[1] == "albaran" and len(sys.argv) != 3:
        sys.exit(uso)
    datos = Path(os.environ.get("TRAZABILIDAD_DATOS") or Path(__file__).parents[2] / "datos")
    ruta = datos / "registro.db"
    if not ruta.exists():
        sys.exit(f"No encuentro la base de datos en {ruta}")
    texto = (
        f"el albarán {sys.argv[2]}" if sys.argv[1] == "albaran"
        else "TODAS las entradas, salidas, controles y recuentos (el catálogo se conserva)"
    )
    if input(f"Se va a borrar {texto}. Escribe SI para continuar: ").strip() != "SI":
        sys.exit("No se ha borrado nada.")
    copia = copia_de_seguridad(ruta)
    con = abrir_base(ruta)
    try:
        if sys.argv[1] == "albaran":
            borradas, pdf = borrar_albaran(con, sys.argv[2])
            print(f"Borradas {borradas} líneas del albarán {sys.argv[2]}.")
            if pdf:
                print(f"El PDF archivado sigue en {pdf}; bórralo a mano si no lo quieres.")
        else:
            for tabla, filas in borrar_todo_lo_de_prueba(con).items():
                print(f"{tabla}: {filas} filas borradas")
    except BorradoNoPermitido as error:
        sys.exit(f"No se ha borrado nada: {error}")
    print(f"Copia de seguridad guardada en {copia}")


if __name__ == "__main__":
    main()
