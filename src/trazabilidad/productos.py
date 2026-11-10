"""Corregir la categoría de un producto ya guardado (catálogo y entradas a la vez)."""

import sqlite3

from trazabilidad.saldos import asignar_fifo, cargar_entradas, cargar_salidas


class CambioNoPermitido(ValueError):
    """El cambio dejaría salidas sin existencias que las cubran."""


def buscar_productos(con: sqlite3.Connection, texto: str = "", limite: int = 50) -> list[dict]:
    """Productos del catálogo cuyo código o descripción contiene el texto, con su categoría."""
    patron = f"%{texto.strip().upper()}%"
    filas = con.execute(
        "SELECT c.codigo, c.descripcion, c.categoria, "
        "(SELECT COUNT(*) FROM entradas e WHERE e.codigo = c.codigo) AS entradas "
        "FROM catalogo c WHERE upper(c.codigo) LIKE ? OR upper(c.descripcion) LIKE ? "
        "ORDER BY (c.descripcion = ''), c.descripcion, c.codigo LIMIT ?",
        (patron, patron, limite),
    )
    return [dict(f) for f in filas]


def cambiar_categoria(con: sqlite3.Connection, codigo: str, nueva: str) -> int:
    """Cambia la categoría del código en el catálogo y en todas sus entradas.

    Devuelve cuántas entradas se movieron. Si tras el cambio alguna salida quedara sin
    existencias que la cubran (por ejemplo, se movió comida ya consumida a otra categoría),
    deshace todo y lanza CambioNoPermitido.
    """
    if not nueva.strip():
        raise ValueError("Falta la categoría")
    with con:
        actual = con.execute("SELECT 1 FROM catalogo WHERE codigo = ?", (codigo,)).fetchone()
        if not actual:
            raise ValueError(f"El código {codigo} no está en el catálogo")
        con.execute("UPDATE catalogo SET categoria = ? WHERE codigo = ?", (nueva, codigo))
        movidas = con.execute(
            "UPDATE entradas SET categoria = ? WHERE codigo = ? AND categoria <> ?",
            (nueva, codigo, nueva),
        ).rowcount
        resultado = asignar_fifo(cargar_entradas(con), cargar_salidas(con))
        if any(falta > 1e-9 for falta in resultado.sin_cubrir):
            raise CambioNoPermitido(
                "No se puede mover: ya hay consumo anotado que dejaría de cuadrar en alguna "
                "categoría. Corrige antes ese consumo."
            )
    return movidas
