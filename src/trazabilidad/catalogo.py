"""Catálogo de códigos: lee el Excel antiguo (una hoja por categoría) y asigna categorías."""

import datetime as dt
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import openpyxl


def limpiar_categoria(titulo_hoja: str) -> str:
    """'Frutas y Verduras 🍏' -> 'Frutas y Verduras' (quita emojis y espacios sobrantes)."""
    return re.sub(r"[^\w\s]", "", titulo_hoja).strip()


def leer_codigos_excel(ruta: str | Path) -> list[tuple[str, str, dt.date | None]]:
    """Devuelve una tupla (código, categoría, fecha de recepción) por cada línea del Excel.

    La fecha está solo en la primera fila de cada albarán; las demás líneas la heredan.
    """
    libro = openpyxl.load_workbook(ruta, data_only=True)
    lineas: list[tuple[str, str, dt.date | None]] = []
    for hoja in libro.worksheets:
        categoria = limpiar_categoria(hoja.title)
        fecha_actual: dt.date | None = None
        for fila in hoja.iter_rows(min_row=16):
            if isinstance(fila[0].value, dt.datetime):
                fecha_actual = fila[0].value.date()
            codigo = fila[2].value
            if isinstance(codigo, (int, float)):  # salta las cabeceras ("CÓDIGO") y filas vacías
                lineas.append((str(int(codigo)), categoria, fecha_actual))
    return lineas


def construir_catalogo(
    lineas: list[tuple[str, str, dt.date | None]],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """De las líneas saca (catálogo, conflictos).

    catálogo: código -> categoría (si un código sale en varias, gana la más reciente).
    conflictos: código -> sus categorías, solo para los que salen en más de una.
    """
    ultima: dict[str, tuple[dt.date, str]] = {}
    categorias: dict[str, list[str]] = defaultdict(list)
    for codigo, categoria, fecha in lineas:
        fecha = fecha or dt.date.min
        if categoria not in categorias[codigo]:
            categorias[codigo].append(categoria)
        if codigo not in ultima or fecha >= ultima[codigo][0]:
            ultima[codigo] = (fecha, categoria)
    catalogo = {codigo: cat for codigo, (_, cat) in ultima.items()}
    conflictos = {c: cats for c, cats in categorias.items() if len(cats) > 1}
    return catalogo, conflictos


def cargar_catalogo(con: sqlite3.Connection, catalogo: dict[str, str]) -> int:
    """Guarda el catálogo en la base sin pisar códigos ya existentes. Devuelve cuántos añadió."""
    antes = con.execute("SELECT COUNT(*) FROM catalogo").fetchone()[0]
    con.executemany(
        "INSERT OR IGNORE INTO catalogo (codigo, descripcion, categoria) VALUES (?, '', ?)",
        catalogo.items(),
    )
    con.commit()
    return con.execute("SELECT COUNT(*) FROM catalogo").fetchone()[0] - antes


def categoria_de(con: sqlite3.Connection, codigo: str) -> str | None:
    """Categoría de un código, o None si es un código nuevo."""
    fila = con.execute("SELECT categoria FROM catalogo WHERE codigo = ?", (codigo,)).fetchone()
    return fila["categoria"] if fila else None
