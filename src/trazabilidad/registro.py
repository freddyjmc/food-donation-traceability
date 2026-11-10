"""Registro de trazabilidad: base de datos SQLite con Entradas, Salidas y Catálogo."""

import datetime as dt
import re
import sqlite3
from pathlib import Path

from pydantic import BaseModel, Field

from trazabilidad.catalogo import categoria_de

MOTIVOS = ("consumo", "caducado o desechado", "otro")

# DON + 4 cifras del centro + fecha AAAAMMDD + 5 cifras de orden. Ej.: DON12342025092000001
PATRON_ALBARAN = re.compile(r"^DON(\d{4})(\d{8})(\d{5})$")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS catalogo (
    codigo      TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL,
    categoria   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entradas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha        TEXT NOT NULL,
    num_albaran  TEXT NOT NULL,
    codigo       TEXT NOT NULL,
    descripcion  TEXT NOT NULL,
    categoria    TEXT NOT NULL,
    cantidad     REAL NOT NULL CHECK (cantidad > 0),
    unidad       TEXT NOT NULL,
    enlace_pdf   TEXT
);

CREATE TABLE IF NOT EXISTS salidas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha     TEXT NOT NULL,
    categoria TEXT NOT NULL,
    unidades  REAL NOT NULL CHECK (unidades > 0),
    motivo    TEXT NOT NULL CHECK (motivo IN ('consumo', 'caducado o desechado', 'otro')),
    unidad    TEXT NOT NULL DEFAULT 'UN'
);

CREATE TABLE IF NOT EXISTS pospuestos (
    num_albaran TEXT NOT NULL,
    categoria   TEXT NOT NULL,
    hasta       TEXT NOT NULL,
    PRIMARY KEY (num_albaran, categoria)
);

CREATE TABLE IF NOT EXISTS controles (
    fecha       TEXT PRIMARY KEY,
    hubo_desecho INTEGER NOT NULL CHECK (hubo_desecho IN (0, 1)),
    responsable TEXT NOT NULL DEFAULT '',
    nota        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS recuentos (
    mes       TEXT NOT NULL,
    categoria TEXT NOT NULL,
    unidad    TEXT NOT NULL,
    cantidad  REAL NOT NULL CHECK (cantidad >= 0),
    PRIMARY KEY (mes, categoria, unidad)
);

CREATE TABLE IF NOT EXISTS ajustes (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vida_util (
    categoria TEXT PRIMARY KEY,
    dias      INTEGER NOT NULL CHECK (dias > 0)
);
"""


class AlbaranInvalido(ValueError):
    """El albarán no se puede guardar (número raro, repetido o vacío)."""


class CodigosSinCategoria(ValueError):
    """Hay códigos nuevos a los que falta asignar categoría en la revisión."""

    def __init__(self, codigos: list[str]):
        self.codigos = codigos
        super().__init__(f"Faltan categorías para los códigos: {', '.join(codigos)}")


class Linea(BaseModel):
    """Una línea de albarán ya validada."""

    codigo: str = Field(pattern=r"^\d+$")
    descripcion: str = Field(min_length=1)
    cantidad: float = Field(gt=0)
    unidad: str = Field(min_length=1)


def abrir_base(ruta: str | Path) -> sqlite3.Connection:
    """Abre (o crea) la base de datos y se asegura de que las tablas existen."""
    conexion = sqlite3.connect(ruta)
    conexion.row_factory = sqlite3.Row
    conexion.executescript(ESQUEMA)
    columnas = [f[1] for f in conexion.execute("PRAGMA table_info(salidas)")]
    if "unidad" not in columnas:  # bases creadas antes de separar UN y KG
        with conexion:
            conexion.execute("ALTER TABLE salidas ADD COLUMN unidad TEXT NOT NULL DEFAULT 'UN'")
    return conexion


def comprobar_numero_albaran(num_albaran: str, fecha: dt.date) -> None:
    """El nº de albarán lleva la fecha dentro: si no coincide, hay un error de tecleo."""
    coincidencia = PATRON_ALBARAN.match(num_albaran)
    if not coincidencia:
        raise AlbaranInvalido(f"El nº de albarán '{num_albaran}' no tiene el formato esperado")
    if coincidencia.group(2) != fecha.strftime("%Y%m%d"):
        raise AlbaranInvalido(
            f"El nº de albarán '{num_albaran}' no coincide con la fecha {fecha.isoformat()}"
        )


def guardar_albaran(
    con: sqlite3.Connection,
    fecha: dt.date,
    num_albaran: str,
    lineas: list[Linea],
    enlace_pdf: str | None = None,
    categorias_elegidas: dict[str, str] | None = None,
) -> int:
    """Guarda un albarán entero (todo o nada). Devuelve cuántas líneas guardó.

    La categoría sale del catálogo; si en la revisión se eligió otra (o el código es nuevo),
    se usa la elegida y el catálogo se actualiza. También rellena la descripción del catálogo.
    """
    comprobar_numero_albaran(num_albaran, fecha)
    if not lineas:
        raise AlbaranInvalido("El albarán no tiene líneas")
    if con.execute("SELECT 1 FROM entradas WHERE num_albaran = ?", (num_albaran,)).fetchone():
        raise AlbaranInvalido(f"El albarán {num_albaran} ya está guardado")

    elegidas = categorias_elegidas or {}
    categorias = {}
    for linea in lineas:
        categorias[linea.codigo] = elegidas.get(linea.codigo) or categoria_de(con, linea.codigo)
    faltan = sorted(codigo for codigo, categoria in categorias.items() if not categoria)
    if faltan:
        raise CodigosSinCategoria(faltan)

    with con:  # si algo falla, no se guarda nada
        for linea in lineas:
            categoria = categorias[linea.codigo]
            con.execute(
                "INSERT INTO catalogo (codigo, descripcion, categoria) VALUES (?, ?, ?)"
                " ON CONFLICT(codigo) DO UPDATE SET categoria = excluded.categoria,"
                " descripcion = CASE WHEN catalogo.descripcion = '' THEN excluded.descripcion"
                " ELSE catalogo.descripcion END",
                (linea.codigo, linea.descripcion, categoria),
            )
            con.execute(
                "INSERT INTO entradas (fecha, num_albaran, codigo, descripcion, categoria,"
                " cantidad, unidad, enlace_pdf) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fecha.isoformat(),
                    num_albaran,
                    linea.codigo,
                    linea.descripcion,
                    categoria,
                    linea.cantidad,
                    linea.unidad,
                    enlace_pdf,
                ),
            )
    return len(lineas)
