"""Lógica de la pantalla de revisión: prepara la tabla editable y valida lo corregido.

Sin Streamlit ni OCR: solo datos, para poder probarla con pytest.
"""

import difflib
import re
import sqlite3

import pandas as pd
from pydantic import ValidationError

from trazabilidad.categorizar import sugerir_categoria
from trazabilidad.parser import RE_COLA, Albaran, cantidad_a_numero, limpiar_descripcion
from trazabilidad.registro import Linea

CATEGORIAS_BASE = (
    "Panadería y bollería",
    "Lacteos y Huevos",
    "Carnes y Embutidos",
    "Pescados y Mariscos",
    "Frutas y Verduras",
    "Comida preparada y congelados",
    "Despensa",
    "Bebida y Snacks",
    "No comestibles",
)
RE_SIN_CANTIDAD_COLA = re.compile(r"(?:\s+(?P<resto>\S{1,2}))?\s+(?P<unidad>UN|KG)\s*$")


def _es_basura(token: str | None) -> bool:
    """Un símbolo, una letra suelta o una palabra en minúsculas: ruido, no parte del nombre."""
    return bool(token) and (len(token) == 1 or not token.isalnum() or token.islower())
LIMITE_UN = 60  # más unidades que esto en una línea del albarán se pide revisarlo
LIMITE_KG = 30  # y más kilos que esto
COLUMNAS = ["Estado", "Código", "Descripción", "Cantidad", "Unidad", "Categoría", "Nota"]
UMBRAL_MISMA_DESCRIPCION = 0.85
UMBRAL_DESCRIPCION_DISTINTA = 0.60
NOMBRE_COLUMNA = {
    "codigo": "Código",
    "descripcion": "Descripción",
    "cantidad": "Cantidad",
    "unidad": "Unidad",
}


def parecido(a: str, b: str) -> float:
    """De 0 a 1: cuánto se parecen dos descripciones."""
    return difflib.SequenceMatcher(None, a.upper(), b.upper()).ratio()


def categorias_disponibles(con: sqlite3.Connection) -> list[str]:
    """Las 9 categorías de siempre más cualquier otra que exista ya en el catálogo."""
    extra = [f[0] for f in con.execute("SELECT DISTINCT categoria FROM catalogo ORDER BY 1")]
    return list(dict.fromkeys([*CATEGORIAS_BASE, *extra]))


def _buscar_por_descripcion(con: sqlite3.Connection, descripcion: str) -> sqlite3.Row | None:
    mejor, mejor_valor = None, UMBRAL_MISMA_DESCRIPCION
    for fila in con.execute("SELECT codigo, descripcion, categoria FROM catalogo"):
        if fila["descripcion"]:
            valor = parecido(fila["descripcion"], descripcion)
            if valor >= mejor_valor:
                mejor, mejor_valor = fila, valor
    return mejor


def _fila(estado, codigo, descripcion, cantidad, unidad, categoria, nota) -> dict:
    valores = [estado, codigo, descripcion, cantidad, unidad, categoria, nota]
    return dict(zip(COLUMNAS, valores, strict=True))


def preparar_revision(albaran: Albaran, con: sqlite3.Connection) -> pd.DataFrame:
    """Tabla para revisar: cada línea con su estado (OK / Nuevo / Revisar) y una nota."""
    filas = []
    for linea in albaran.lineas:
        conocido = con.execute(
            "SELECT descripcion, categoria FROM catalogo WHERE codigo = ?", (linea.codigo,)
        ).fetchone()
        if conocido:
            estado, categoria, nota = "OK", conocido["categoria"], ""
            en_catalogo = conocido["descripcion"]
            distinta = parecido(en_catalogo, linea.descripcion) < UMBRAL_DESCRIPCION_DISTINTA
            if en_catalogo and distinta:
                estado = "Revisar"
                nota = f"El catálogo tiene este código como «{en_catalogo}»: ¿código mal leído?"
        else:
            parecida = _buscar_por_descripcion(con, linea.descripcion)
            if parecida:
                estado, categoria = "Revisar", parecida["categoria"]
                nota = f"¿Es el código {parecida['codigo']}? Misma descripción en el catálogo"
            elif sugerida := sugerir_categoria(con, linea.descripcion):
                estado, categoria, nota = "Sugerida", sugerida[0], f"{sugerida[1]}: confírmala"
            else:
                estado, categoria, nota = "Nuevo", None, "Código nuevo: elige su categoría"
        limite = LIMITE_KG if linea.unidad == "KG" else LIMITE_UN
        if linea.cantidad > limite:  # casi seguro un error de lectura (p. ej. «6,75» -> «675»)
            estado = "Revisar"
            aviso = (f"Cantidad muy alta ({linea.cantidad:g} {linea.unidad}): "
                     "comprueba si falta la coma")
            nota = f"{nota} · {aviso}" if nota else aviso
        filas.append(
            _fila(estado, linea.codigo, linea.descripcion, linea.cantidad, linea.unidad,
                  categoria, nota)
        )

    dudosas: list[dict] = []
    for texto in albaran.dudosas:
        cola = RE_COLA.search(texto)
        cantidad_txt, unidad = (cola["cantidad"], cola["unidad"]) if cola else ("", "UN")
        descripcion = limpiar_descripcion(texto[: cola.start()] if cola else texto)
        sin_cantidad = None if cola else RE_SIN_CANTIDAD_COLA.search(texto)
        if sin_cantidad:  # «COLA { UN»: la cantidad se leyó como un símbolo o una letra
            unidad = sin_cantidad["unidad"]
            fin = sin_cantidad.start() if _es_basura(sin_cantidad["resto"]) else (
                sin_cantidad.start("unidad") - 1)
            descripcion = limpiar_descripcion(texto[:fin])
        cantidad = cantidad_a_numero(cantidad_txt) if cantidad_txt else None
        con_codigo = re.match(r"(?<!\d)(\d{3,6})\s+(\S.*)$", descripcion)
        if con_codigo:  # el código sí está en el texto: se separa de la descripción
            codigo_leido = con_codigo.group(1)
            descripcion = limpiar_descripcion(con_codigo.group(2))
            sugerida = sugerir_categoria(con, descripcion)
            conocido = con.execute(
                "SELECT categoria FROM catalogo WHERE codigo = ?", (codigo_leido,)
            ).fetchone()
            categoria = conocido["categoria"] if conocido else (sugerida[0] if sugerida else None)
            dudosas.append(
                _fila("Revisar", codigo_leido, descripcion, cantidad, unidad, categoria,
                      "Cantidad no leída: mira el albarán y escríbela" if sin_cantidad
                      else "Línea leída con símbolos de más: comprueba el código y la cantidad")
            )
            continue
        parecida = _buscar_por_descripcion(con, descripcion) if descripcion else None
        if parecida:
            dudosas.append(
                _fila("Revisar", parecida["codigo"], descripcion, cantidad, unidad,
                      parecida["categoria"],
                      f"Código no leído: ¿es el {parecida['codigo']}? Misma descripción")
            )
        else:
            sugerida = sugerir_categoria(con, descripcion)
            dudosas.append(
                _fila("Revisar", "", descripcion, cantidad, unidad,
                      sugerida[0] if sugerida else None,
                      "No se leyó el código: escríbelo (o borra la fila si no es una línea)")
            )
    # cada fila vuelve a su sitio original en el albarán (no todas las dudosas al final)
    orden = getattr(albaran, "orden", [])
    if orden and orden.count("l") == len(filas) and orden.count("d") == len(dudosas):
        sigue_l, sigue_d, mezcladas = iter(filas), iter(dudosas), []
        mezcladas = [next(sigue_l) if t == "l" else next(sigue_d) for t in orden]
        filas = mezcladas
    else:
        filas = filas + dudosas
    return pd.DataFrame(filas, columns=COLUMNAS)


def _texto(valor) -> str:
    return "" if valor is None or pd.isna(valor) else str(valor).strip()


def sin_categoria(tabla: pd.DataFrame) -> pd.Series:
    """Qué filas de la tabla no tienen categoría todavía."""
    return tabla["Categoría"].map(lambda valor: not _texto(valor))


def _fila_vacia(fila) -> bool:
    """Fila sin código, descripción ni cantidad (la categoría sola no la hace una línea)."""
    cantidad = fila.get("Cantidad")
    return not (
        _texto(fila.get("Código")) or _texto(fila.get("Descripción"))
    ) and (cantidad is None or pd.isna(cantidad))


def aplicar_categoria(tabla: pd.DataFrame, categoria: str) -> pd.DataFrame:
    """Pone la categoría a las filas con datos que no la tienen (las demás no se tocan)."""
    nueva = tabla.copy()
    vacias = nueva.apply(_fila_vacia, axis=1) if len(nueva) else pd.Series(dtype=bool)
    nueva.loc[sin_categoria(nueva) & ~vacias, "Categoría"] = categoria
    return nueva


def contar_lineas(tabla: pd.DataFrame) -> int:
    """Líneas reales de la tabla: las que tienen código, sin contar filas en blanco."""
    return sum(1 for fila in tabla.to_dict("records") if _texto(fila.get("Código")))


def validar_tabla(tabla: pd.DataFrame) -> tuple[list[Linea], dict[str, str], list[str]]:
    """De la tabla corregida saca (líneas, categorías elegidas por código, errores)."""
    lineas: list[Linea] = []
    categorias: dict[str, str] = {}
    errores: list[str] = []
    for n, fila in enumerate(tabla.to_dict("records"), start=1):
        codigo, descripcion = _texto(fila.get("Código")), _texto(fila.get("Descripción"))
        categoria, unidad = _texto(fila.get("Categoría")), _texto(fila.get("Unidad"))
        cantidad = fila.get("Cantidad")
        if _fila_vacia(fila):
            continue  # fila en blanco (aunque tenga categoría puesta)
        if codigo.endswith(".0"):
            codigo = codigo[:-2]
        try:
            linea = Linea(codigo=codigo, descripcion=descripcion, cantidad=cantidad, unidad=unidad)
        except ValidationError as error:
            campos = ", ".join(sorted({NOMBRE_COLUMNA[str(e["loc"][0])] for e in error.errors()}))
            errores.append(f"Fila {n}: revisa {campos}")
            continue
        if not categoria:
            errores.append(f"Fila {n} (código {codigo}): falta la categoría")
            continue
        if categorias.setdefault(codigo, categoria) != categoria:
            errores.append(f"Código {codigo}: aparece con dos categorías distintas")
            continue
        lineas.append(linea)
    if not lineas and not errores:
        errores.append("No hay ninguna línea que guardar")
    return lineas, categorias, errores


def mover_fila(tabla: pd.DataFrame, origen: int, destino: int) -> pd.DataFrame:
    """Mueve la fila nº `origen` a la posición `destino` (1 = primera). Devuelve tabla 1..n."""
    filas = tabla.reset_index(drop=True)
    n = len(filas)
    if not (1 <= origen <= n and 1 <= destino <= n):
        raise ValueError(f"Los números de fila deben estar entre 1 y {n}")
    orden = list(range(n))
    orden.insert(destino - 1, orden.pop(origen - 1))
    nueva = filas.iloc[orden].reset_index(drop=True)
    nueva.index = range(1, n + 1)
    return nueva
