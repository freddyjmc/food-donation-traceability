"""Convertir el texto del OCR en un albarán con líneas validadas. Paso 5.

Son funciones puras: reciben texto y devuelven datos, sin OCR ni pantalla.
Principio: una línea que no se entiende NO se descarta, se marca como dudosa para revisarla.
"""

import datetime as dt
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from trazabilidad.registro import Linea

# Código (3-6 cifras) + descripción + cantidad + unidad. Lo que haya antes del código
# (trazos de lápiz leídos como símbolos) se ignora.
RE_LINEA = re.compile(
    r"(?<!\d)(?P<codigo>\d{3,6})\s+(?P<descripcion>\S.*?)(?:\s+|(?<=[^\w\s]))"
    r"(?P<cantidad>\d{1,3}(?:[.,]\d{1,3})?|\d{1,3}000)\s*(?P<unidad>[A-Z]{2})\s*$"
)
# (el espacio antes de la cantidad puede faltar si el OCR pega un símbolo: «“8,000 UN»)
# Una línea que acaba en cantidad + unidad pero no se pudo leer entera
RE_COLA = re.compile(r"(?P<cantidad>\d{1,3}[.,]\d{1,3}|\d{1,3}000)\s*(?P<unidad>[A-Z]{2})\s*$")
# Línea con código, descripción y unidad pero con la cantidad leída como un símbolo o una letra
# suelta («{», «|», «a»), o sin cantidad:
# no se descarta, se manda a revisar para que se escriba la cantidad.
RE_SIN_CANTIDAD = re.compile(
    r"(?<!\d)\d{3,6}\s+[A-ZÁÉÍÓÚÑ0-9].*?(?:\s+\S{1,2})?\s+(?:UN|KG)\s*$"
)
RE_FECHA = re.compile(r"Fecha:?\s*(\d{2})[-/](\d{2})[-/](\d{4})")
# Otro formato del albarán: «RESUMEN DE DONACIONES DIARIAS 12-05-2026» (sin la palabra «Fecha»)
RE_FECHA_RESUMEN = re.compile(
    r"DONACIONES\s+DIARIAS\s*:?\s*(\d{2})[-/.](\d{2})[-/.](\d{4})", re.IGNORECASE
)
# El número de albarán lleva la fecha dentro: DON + 4 cifras del centro + AAAAMMDD + 5 cifras
RE_FECHA_EN_NUMERO = re.compile(r"DON\d{4}(\d{4})(\d{2})(\d{2})\d{5}$")
RE_NUMERO = re.compile(r"DON\d{15,22}")


@dataclass
class Albaran:
    fecha: dt.date | None = None
    num_albaran: str | None = None
    lineas: list[Linea] = field(default_factory=list)
    dudosas: list[str] = field(default_factory=list)  # texto de las líneas que hay que revisar
    avisos: list[str] = field(default_factory=list)
    orden: list[str] = field(default_factory=list)  # «l»/«d»: orden original de líneas y dudosas


def cantidad_a_numero(texto: str) -> float:
    """'1,000' -> 1.0 ; '6,75' -> 6.75 ; '13' -> 13.0 (el albarán usa coma decimal).

    '4000' -> 4.0: el OCR a veces pierde la coma de «4,000» (nadie recibe 4000 unidades)."""
    if re.fullmatch(r"\d{1,3}000", texto):
        return float(texto[:-3])
    return float(texto.replace(",", "."))


def limpiar_descripcion(texto: str) -> str:
    """Quita el ruido del OCR (trazos de lápiz leídos como símbolos o letras sueltas en minúscula).

    Las descripciones del albarán van siempre en mayúsculas, así que una palabra solo en
    minúsculas al principio ('ease', 'ie', 'j') es ruido.
    """
    texto = texto.strip()
    anterior = None
    while anterior != texto:
        anterior = texto
        texto = re.sub(r"^(?:[\W_]+|[a-záéíóúñü]+(?=\s))\s*", "", texto)
    return re.sub(r"[\s|&_~—–\\^*`´\"';:{}\[\]()<>]+$", "", texto)


def leer_linea(texto: str) -> Linea | None:
    """Devuelve la línea validada, o None si el texto no tiene la forma de una línea."""
    coincidencia = RE_LINEA.search(texto.strip())
    if not coincidencia:
        return None
    try:
        return Linea(
            codigo=coincidencia["codigo"],
            descripcion=limpiar_descripcion(coincidencia["descripcion"]),
            cantidad=cantidad_a_numero(coincidencia["cantidad"]),
            unidad=coincidencia["unidad"],
        )
    except ValidationError:
        return None


def _fechas(trozos: list[tuple[str, str, str]]) -> set[dt.date]:
    fechas = set()
    for d, m, a in trozos:
        try:
            fechas.add(dt.date(int(a), int(m), int(d)))
        except ValueError:
            pass  # una fecha imposible (mes 13...) es un error de lectura: se ignora
    return fechas


def _distancia(a: str, b: str) -> int:
    """Cifras distintas entre dos números (si tienen distinto largo, se cuenta la diferencia)."""
    return sum(x != y for x, y in zip(a, b, strict=False)) + abs(len(a) - len(b))


def _mismo_albaran(a: str, b: str) -> bool:
    """Mismo mes, día y nº de orden, y como mucho 2 cifras distintas en «DON» + centro + año.

    Un fallo del OCR suele estar en el año («2026» -> «2626»). Si cambia el día o el nº de
    orden puede ser otro albarán de verdad, y entonces sí se avisa."""
    return a[-9:] == b[-9:] and _distancia(a[:-9], b[:-9]) <= 2


def _elegir_numero(albaran: Albaran, leidos: list[str]) -> None:
    """Elige el número de albarán entre las lecturas de todas las páginas.

    El OCR a veces confunde una cifra en una página («2026» -> «2626»): lecturas casi iguales
    son el mismo albarán. Se prefiere la que cuadra con la fecha; solo se avisa si de verdad
    hay números distintos.
    """
    if not leidos:
        albaran.avisos.append("No se ha leído el número de albarán")
        return
    veces: dict[str, int] = {}
    for numero in leidos:
        veces[numero] = veces.get(numero, 0) + 1

    def puntos(numero: str) -> tuple[int, int, int]:
        en_numero = RE_FECHA_EN_NUMERO.match(numero)
        fecha_ok = bool(en_numero) and albaran.fecha is not None and (
            "".join(en_numero.groups()) == albaran.fecha.strftime("%Y%m%d")
        )
        return (fecha_ok, numero.startswith("DON"), veces[numero])

    ordenados = sorted(veces, key=puntos, reverse=True)
    elegido = ordenados[0]
    if albaran.fecha and not puntos(elegido)[0]:
        # ninguna lectura cuadra con la fecha: si una está a ≤2 cifras de lo esperado, se corrige
        esperado = elegido[:7] + albaran.fecha.strftime("%Y%m%d") + elegido[-5:]
        if _distancia(elegido, esperado) <= 2:
            albaran.avisos.append(
                f"El número leído ({elegido}) no cuadra con la fecha: se ha corregido a "
                f"{esperado}. Compruébalo con el papel."
            )
            elegido = esperado
    albaran.num_albaran = elegido
    distintos = [n for n in ordenados if not _mismo_albaran(n, elegido)]
    if distintos:
        albaran.avisos.append("Las páginas tienen números de albarán distintos")


def leer_albaran(texto: str) -> Albaran:
    """Lee el texto completo de un albarán (una o varias páginas unidas)."""
    albaran = Albaran()

    fechas = _fechas(RE_FECHA.findall(texto)) or _fechas(RE_FECHA_RESUMEN.findall(texto))
    if fechas:
        albaran.fecha = min(fechas)
    if len(fechas) > 1:
        albaran.avisos.append("Las páginas tienen fechas distintas")

    _elegir_numero(albaran, RE_NUMERO.findall(texto))
    if albaran.fecha is None and albaran.num_albaran:
        en_numero = RE_FECHA_EN_NUMERO.match(albaran.num_albaran)
        if en_numero:
            try:
                albaran.fecha = dt.date(*(int(g) for g in en_numero.groups()))
                albaran.avisos.append(
                    "No se leyó la fecha en el albarán: se ha tomado del número. Compruébala."
                )
            except ValueError:
                pass

    for linea in texto.splitlines():
        leida = leer_linea(linea)
        if leida:
            albaran.lineas.append(leida)
            albaran.orden.append("l")
        elif RE_COLA.search(linea.strip()) or RE_SIN_CANTIDAD.search(linea.strip()):
            albaran.dudosas.append(linea.strip())
            albaran.orden.append("d")

    return albaran
