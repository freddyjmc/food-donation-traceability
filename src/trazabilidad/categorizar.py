"""Sugiere la categoría de un producto nuevo a partir de su descripción.

Nunca decide por su cuenta: la tabla de revisión muestra la sugerencia como «Sugerida» y la
persona la confirma. Si no hay base para sugerir, devuelve None y la fila queda sin categoría.
"""

import re
import sqlite3
import unicodedata

PANADERIA = "Panadería y bollería"
LACTEOS = "Lacteos y Huevos"
CARNES = "Carnes y Embutidos"
PESCADOS = "Pescados y Mariscos"
FRUTAS = "Frutas y Verduras"
PREPARADA = "Comida preparada y congelados"
DESPENSA = "Despensa"
BEBIDA = "Bebida y Snacks"
NO_COMESTIBLES = "No comestibles"

# Las reglas se prueban en orden: la primera que encaja gana. Por eso «ATUN» (conserva) y
# «SOPA» (preparada) van antes que pescados y verduras. Cada regla es (palabras, categoría).
REGLAS: tuple[tuple[str, str], ...] = (
    (r"BOLSA|SERVILLETA|DETERGENTE|LEJIA|FREGONA|ESTROPAJO|PAPEL (?:HIGIENICO|COCINA)|"
     r"LIMPIA|JABON|GUANTE|FILM|ALUMINIO|VASO|PLATO DESECH|PILA", NO_COMESTIBLES),
    (r"GOURMET|ENSALADA (?:DE )?(?:JAMON|POLLO|ATUN|PASTA|ARROZ|CAMPERA|CESAR|GAMBA|SURIMI)|"
     r"SOPA|SALMOREJO|GAZPACHO|CREMA DE|CALDO FRESCO|LASANA|CROQUETA|EMPANADILLA|PIZZA|"
     r"TORTILLA|ENSALADILLA|POTAJE|GUISO|PLATO PREPARADO|CONGELAD|MENU|ARROZ CON (?!LECHE)|"
     r"PAELLA|COCIDO|HAMBURGUESA VEGETAL", PREPARADA),
    (r"ATUN|SARDINA|MEJILLON|BERBERECHO|CABALLA EN|FABADA|LENTEJA|GARBANZO|ALUBIA|"
     r"CONSERVA|TOMATE FRITO|TOMATE TRITURADO|LECHE CONDEN|JUDIA.*BOTE", DESPENSA),
    (r"YOGUR|YOGURT|NATILLA|FLAN|QUESO|LECHE|MANTEQUILLA|NATA|CUAJADA|KEFIR|HUEVO|BATIDO|"
     r"REQUESON|PETIT|GELATINA|ARROZ CON LECHE|CREMA CATALANA", LACTEOS),
    (r"PAN\b|BARRA|CROISSANT|BERLINA|DONUT|MAGDALENA|NAPOLITANA|PALMERA|ENSAIMADA|BOLLO|"
     r"TARTA|BIZCOCHO|HOJALDRE|TOSTADA|PICOS|REGANAS|MOLDE|BAGUETTE|CHAPATA|PANECILLO|"
     r"SOBAO|MADALENA|CUERNO", PANADERIA),
    (r"SAL\b|AZUCAR|HARINA|ARROZ|PASTA\b|ESPAGUETI|MACARRON|FIDEO|ACEITE|VINAGRE|"
     r"CACAO EN POLVO|CAFE|COLACAO|CEREAL|GALLETA|MERMELADA|MIEL\b|LEVADURA|MAIZ|PURE\b|"
     r"CALDO|SOPA (?:DE )?SOBRE", DESPENSA),
    (r"POLLO|PAVO|CERDO|TERNERA|VACUNO|CORDERO|PAPADA|RABO|COSTILLA|LOMO|SOLOMILLO|"
     r"CHULETA|JAMON|CHORIZO|SALCHICHA|SALCHICHON|MORTADELLA|FUET|BACON|PANCETA|BUTIFARRA|"
     r"MORCILLA|CARNE|HIGADO|PECHUGA|MUSLO|ALBONDIGA|LACON|TOCINO|LONGANIZA|PATA", CARNES),
    (r"MERLUZA|SALMON|BACALAO|GAMBA|LANGOSTINO|CALAMAR|SEPIA|PULPO|DORADA|LUBINA|RAPE|"
     r"PESCADO|ANCHOA|BOQUERON|MEJILLONES FRESC|ALMEJA|SURIMI|LENGUADO|PANGASIUS|TRUCHA", PESCADOS),
    (r"AGUA|REFRESCO|COLA|ZUMO|CERVEZA|VINO|ISOTONICO|ENERGETIC|MONSTER|NESTEA|TE FRIO|"
     r"LIMONADA|BEBIDA|PATATAS FRITAS|SNACK|GANCHITOS|CHOCOLATINA|BARRITA|CHUCHE|GOMINOLA|"
     r"CARAMELO|CHICLE|TURRON|GOLOSINA|JELLY|PALOMITAS|FRUTOS SECOS|CACAHUETE|PIPAS|"
     r"CHOCOLATE|BOMBON", BEBIDA),
    (r"TOMATE|CEBOLLA|PATATA|ZANAHORIA|LECHUGA|ROMANA|ESCAROLA|COGOLLO|ENDIBIA|APIO|RUCULA|"
     r"ESPINACA|ACELGA|BROCOLI|COLIFLOR|CALABAZA|CALABACIN|BERENJENA|PIMIENTO|PEPINO|"
     r"PUERRO|AJO|SETA|CHAMPINON|JUDIA VERDE|GUISANTE|ALBAHACA|PEREJIL|HIERBABUENA|CILANTRO|"
     r"MENTA|BROTES|ENSALADA|VERDURA|HORTALIZA|FRESA|MANZANA|PERA|PLATANO|NARANJA|MANDARINA|"
     r"LIMON|UVA|MELON|SANDIA|MELOCOTON|NECTARINA|CIRUELA|ALBARICOQUE|KIWI|PINA|MANGO|"
     r"AGUACATE|CEREZA|HIGO|GRANADA|COCO\b|FRUTA|REMOLACHA|RABANO|NABO|BATATA|MAZORCA", FRUTAS),
)
_REGLAS_COMPILADAS = tuple((re.compile(rf"\b(?:{p})", re.IGNORECASE), c) for p, c in REGLAS)


def normalizar(texto: str) -> str:
    """Mayúsculas y sin tildes, para comparar descripciones."""
    sin_tildes = unicodedata.normalize("NFD", texto.upper())
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")


def por_palabras_clave(descripcion: str) -> tuple[str, str] | None:
    """(categoría, palabra que decidió) según las reglas fijas, o None."""
    texto = normalizar(descripcion)
    for regla, categoria in _REGLAS_COMPILADAS:
        encaje = regla.search(texto)
        if encaje:
            return categoria, encaje.group(0).strip()
    return None


def por_historial(con: sqlite3.Connection, descripcion: str) -> tuple[str, str] | None:
    """Aprende de lo ya guardado: si todos los productos conocidos que comparten una palabra
    (de 4 letras o más) tienen la misma categoría, esa es la sugerencia."""
    palabras = [p for p in re.findall(r"[A-Z]{4,}", normalizar(descripcion))]
    for palabra in palabras:
        filas = con.execute(
            "SELECT DISTINCT categoria FROM catalogo WHERE descripcion <> '' "
            "AND upper(descripcion) LIKE ?",
            (f"%{palabra}%",),
        ).fetchall()
        total = con.execute(
            "SELECT COUNT(*) FROM catalogo WHERE descripcion <> '' AND upper(descripcion) LIKE ?",
            (f"%{palabra}%",),
        ).fetchone()[0]
        if len(filas) == 1 and total >= 2:
            return filas[0][0], palabra
    return None


def sugerir_categoria(con: sqlite3.Connection, descripcion: str) -> tuple[str, str] | None:
    """(categoría, explicación) o None si no hay base para sugerir."""
    if not descripcion.strip():
        return None
    historial = por_historial(con, descripcion)
    if historial:
        return historial[0], f"Sugerida por tus productos anteriores con «{historial[1]}»"
    clave = por_palabras_clave(descripcion)
    if clave:
        return clave[0], f"Sugerida por la palabra «{clave[1]}»"
    return None
