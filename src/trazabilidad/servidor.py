"""Copia de seguridad y archivo ordenado en una carpeta del servidor de la empresa.

En la carpeta elegida (por ejemplo \\\\servidor\\carpeta\\Registro) se guardan:
- informes/AAAA/AAAA-MM/   informe, anexo y recapitulativo de cada mes (y semanales)
- albaranes_pdf/           los PDF originales de los albaranes
- copias_seguridad/        una copia de la base de datos por día (registro_AAAA-MM-DD.db)
"""

import datetime as dt
import shutil
import sqlite3
from pathlib import Path


def cargar_carpeta(con: sqlite3.Connection) -> str:
    fila = con.execute("SELECT valor FROM ajustes WHERE clave = 'carpeta_servidor'").fetchone()
    return fila[0] if fila else ""


def guardar_carpeta(con: sqlite3.Connection, ruta: str) -> None:
    with con:
        if ruta.strip():
            con.execute(
                "INSERT OR REPLACE INTO ajustes (clave, valor) VALUES ('carpeta_servidor', ?)",
                (ruta.strip(),),
            )
        else:
            con.execute("DELETE FROM ajustes WHERE clave = 'carpeta_servidor'")


def _copiar_arbol(origen: Path, destino: Path) -> int:
    """Copia solo lo nuevo o modificado. Devuelve cuántos archivos copió."""
    copiados = 0
    if not origen.exists():
        return 0
    for archivo in origen.rglob("*"):
        if not archivo.is_file():
            continue
        objetivo = destino / archivo.relative_to(origen)
        if objetivo.exists() and objetivo.stat().st_mtime >= archivo.stat().st_mtime:
            continue
        objetivo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archivo, objetivo)
        copiados += 1
    return copiados


def copiar_al_servidor(con: sqlite3.Connection, datos: Path, destino: Path) -> str:
    """Copia todo a `destino`. Devuelve un texto con lo hecho; lanza OSError si no hay acceso."""
    destino.mkdir(parents=True, exist_ok=True)
    carpeta_bd = destino / "copias_seguridad"
    carpeta_bd.mkdir(exist_ok=True)
    ruta_bd = carpeta_bd / f"registro_{dt.date.today():%Y-%m-%d}.db"
    copia = sqlite3.connect(ruta_bd)
    try:
        con.backup(copia)  # copia consistente aunque la app esté abierta
    finally:
        copia.close()
    informes = _copiar_arbol(datos / "informes", destino / "informes")
    pdfs = _copiar_arbol(datos / "pdf_archivo", destino / "albaranes_pdf")
    return (f"Copia hecha en {destino}: base de datos, {informes} archivo(s) de informes y "
            f"{pdfs} PDF de albaranes nuevos.")


def copia_diaria_pendiente(con: sqlite3.Connection) -> bool:
    fila = con.execute("SELECT valor FROM ajustes WHERE clave = 'ultima_copia'").fetchone()
    return not fila or fila[0] != dt.date.today().isoformat()


def marcar_copia_hecha(con: sqlite3.Connection) -> None:
    with con:
        con.execute(
            "INSERT OR REPLACE INTO ajustes (clave, valor) VALUES ('ultima_copia', ?)",
            (dt.date.today().isoformat(),),
        )
