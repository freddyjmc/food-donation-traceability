"""OCR con Tesseract: pasa las imágenes de un albarán a texto."""

import os
import re
import shutil
from pathlib import Path

import pytesseract
from PIL import Image

RUTAS_WINDOWS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


class TesseractNoEncontrado(RuntimeError):
    """Tesseract no está instalado (o Python no lo encuentra)."""


def configurar_tesseract() -> str:
    """Localiza tesseract.exe (variable TESSERACT_CMD, PATH o carpetas habituales de Windows)."""
    candidatos = [os.environ.get("TESSERACT_CMD"), shutil.which("tesseract"), *RUTAS_WINDOWS]
    for candidato in candidatos:
        if candidato and Path(candidato).exists():
            pytesseract.pytesseract.tesseract_cmd = candidato
            return candidato
    raise TesseractNoEncontrado(
        "No encuentro Tesseract. Instálalo (con el idioma Spanish) o define la variable "
        "TESSERACT_CMD con la ruta de tesseract.exe."
    )


def idioma() -> str:
    """'spa' si Tesseract lo tiene instalado; si no, 'eng' (peor con tildes, igual con números)."""
    configurar_tesseract()
    return "spa" if "spa" in pytesseract.get_languages(config="") else "eng"


UNIDADES = ("UN", "KG")
RE_NUMERO_CANTIDAD = re.compile(r"^(?:\d{1,3}(?:[.,]\d{1,3})?|\d{1,3}000)$")


def _cantidad_de_la_celda(imagen: Image.Image, caja: tuple[int, int, int, int]) -> str | None:
    """Vuelve a leer, solo como cifras, el hueco de la cantidad (ampliado)."""
    izquierda, arriba, derecha, abajo = caja
    if derecha - izquierda < 10 or abajo - arriba < 10:
        return None
    celda = imagen.crop(caja)
    margen = celda.width // 6  # sin los bordes: a veces hay una mancha o una raya pegada
    variantes = [(celda, "7"), (celda, "8"), (celda.crop((margen, 0, celda.width - margen,
                                                           celda.height)), "7")]
    for imagen_celda, modo in variantes:
        ampliada = imagen_celda.resize((imagen_celda.width * 2, imagen_celda.height * 2))
        texto = pytesseract.image_to_string(
            ampliada, lang="eng",
            config=f"--psm {modo} -c tessedit_char_whitelist=0123456789,.",
        ).strip()
        if RE_NUMERO_CANTIDAD.match(texto):
            return texto
    return None


def _es_codigo(texto: str) -> bool:
    return texto.isdigit() and 3 <= len(texto) <= 6


def reconstruir_lineas(datos: dict, ancho: int, leer_celda) -> list[str]:
    """Líneas de texto de una página a partir de las palabras y sus posiciones.

    Las filas «código … descripción … cantidad UN» cuya cantidad no se leyó como número (salió
    un símbolo, una letra suelta o nada) se arreglan usando la COLUMNA de la cantidad: las
    palabras que caen en esa columna se quitan y el hueco se lee de nuevo solo como cifras.
    Así una letra suelta («a», «L», «q») nunca se queda pegada a la descripción.
    `leer_celda(izquierda, arriba, derecha, abajo)` devuelve la cantidad leída o None.
    """
    lineas: dict[tuple, list[int]] = {}
    for i, palabra in enumerate(datos["text"]):
        if str(palabra).strip():
            clave = (datos["block_num"][i], datos["par_num"][i], datos["line_num"][i])
            lineas.setdefault(clave, []).append(i)

    columna = None  # (izquierda, derecha) de la columna «Cantidad», según la cabecera
    for i, palabra in enumerate(datos["text"]):
        if str(palabra).strip().lower().startswith("cantid"):
            holgura = ancho * 0.03
            columna = (datos["left"][i] - holgura, datos["left"][i] + datos["width"][i] + holgura)
            break

    salida = []
    for indices in lineas.values():
        indices = sorted(indices, key=lambda i: datos["left"][i])
        textos = [str(datos["text"][i]).strip() for i in indices]
        if len(textos) < 3 or textos[-1] not in UNIDADES or not _es_codigo(textos[0]):
            salida.append(" ".join(textos))
            continue
        unidad = indices[-1]
        medios = indices[:-1]
        if columna:
            izq, der = columna
        else:  # sin cabecera en la página: la mitad derecha, hasta la unidad
            izq, der = ancho / 2, datos["left"][unidad]
        en_columna = [i for i in medios
                      if izq <= datos["left"][i] + datos["width"][i] / 2 <= der]
        leidas = [str(datos["text"][i]).strip() for i in en_columna]
        numericas = [t for t in leidas if RE_NUMERO_CANTIDAD.match(t)]
        sobrantes = [t for t in leidas if not RE_NUMERO_CANTIDAD.match(t)]
        if len(numericas) == 1 and all(len(t) <= 2 and not t.isalnum() for t in sobrantes):
            # la cantidad está bien leída (a veces con un símbolo suelto al lado: «2 :»)
            antes = [str(datos["text"][i]).strip() for i in medios if i not in en_columna]
            salida.append(" ".join(antes + numericas + [textos[-1]]))
            continue
        if not columna:  # sin columna fiable, solo se quitan símbolos o letras sueltas
            en_columna = [i for i in en_columna
                          if len(str(datos["text"][i]).strip()) <= 2
                          and not RE_NUMERO_CANTIDAD.match(str(datos["text"][i]).strip())]
        descripcion = [str(datos["text"][i]).strip() for i in medios if i not in en_columna]
        # alto de la fila según la mediana de sus palabras (una mancha o una raya suelta de la
        # tabla en la misma línea no debe agrandar el recuadro de la cantidad)
        tops = sorted(datos["top"][i] for i in indices)
        altos = sorted(datos["height"][i] for i in indices)
        arriba = tops[len(tops) // 2] - 6
        abajo = tops[len(tops) // 2] + altos[len(altos) // 2] + 6
        cantidad = leer_celda(int(izq), arriba, int(min(der, datos["left"][unidad] - 5)), abajo)
        partes = descripcion + ([cantidad] if cantidad else []) + [textos[-1]]
        salida.append(" ".join(partes))
    return salida


def leer_texto(imagen: Image.Image) -> str:
    """Texto de una página. psm 6 = 'un bloque de texto uniforme', va bien con tablas.

    Si la cantidad de una fila sale ilegible (un símbolo, una letra o nada), se vuelve a leer
    solo ese hueco como cifras (ver `reconstruir_lineas`).
    """
    try:
        datos = pytesseract.image_to_data(
            imagen, lang=idioma(), config="--psm 6", output_type=pytesseract.Output.DICT
        )
        return "\n".join(reconstruir_lineas(
            datos, imagen.width,
            lambda i, a, d, b: _cantidad_de_la_celda(imagen, (i, a, d, b)),
        ))
    except pytesseract.TesseractError:
        return pytesseract.image_to_string(imagen, lang=idioma(), config="--psm 6")


def leer_albaran(imagenes: list[Image.Image]) -> str:
    """Texto de todas las páginas de un albarán, una detrás de otra."""
    return "\n".join(leer_texto(imagen) for imagen in imagenes)
