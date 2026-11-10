"""Crea datos 100 % ficticios para probar la aplicación y hacer capturas.

Uso (con el entorno activado, desde la carpeta del proyecto):
    python scripts/crear_datos_demo.py            # crea ./datos_demo
    TRAZABILIDAD_DATOS=datos_demo streamlit run src/trazabilidad/app.py

Genera también un albarán de ejemplo en PDF (datos_demo/albaran_ejemplo.pdf) para probar
la pantalla «Subir albarán». Ni los productos, ni las cantidades, ni el donante son reales.
"""

import datetime as dt
import random
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trazabilidad.controles import guardar_control, guardar_recuento  # noqa: E402
from trazabilidad.informes import (  # noqa: E402
    guardar_inicio_registro,
    guardar_personas,
    guardar_recapitulativo,
)
from trazabilidad.registro import Linea, abrir_base, guardar_albaran  # noqa: E402
from trazabilidad.saldos import Salida  # noqa: E402

CENTRO = "1234"  # código de centro inventado
PRODUCTOS = {  # categoría -> [(código, descripción, unidad)]
    "Panadería y bollería": [
        ("10010", "BARRA DE PAN RUSTICA", "UN"), ("10011", "BOLLERIA SURTIDA", "UN"),
        ("10012", "PAN DE MOLDE INTEGRAL", "UN")],
    "Lacteos y Huevos": [
        ("20010", "YOGUR NATURAL PACK 4", "UN"), ("20011", "LECHE ENTERA 1L", "UN"),
        ("20012", "QUESO FRESCO", "UN")],
    "Carnes y Embutidos": [
        ("30010", "POLLO ENTERO", "KG"), ("30011", "JAMON COCIDO LONCHAS", "UN"),
        ("30012", "SALCHICHAS FRESCAS", "UN")],
    "Pescados y Mariscos": [("40010", "MERLUZA FILETES", "KG"), ("40011", "SALMON LOMOS", "KG")],
    "Frutas y Verduras": [
        ("50010", "MANZANA GOLDEN", "KG"), ("50011", "TOMATE RAMA", "KG"),
        ("50012", "LECHUGA ROMANA", "UN"), ("50013", "PLATANO", "KG")],
    "Comida preparada y congelados": [
        ("60010", "LASAÑA CONGELADA", "UN"), ("60011", "ENSALADA LISTA PARA COMER", "UN")],
    "Despensa": [("70010", "ARROZ REDONDO 1KG", "UN"), ("70011", "LENTEJAS COCIDAS", "UN")],
    "Bebida y Snacks": [("80010", "ZUMO DE NARANJA 1L", "UN"), ("80011", "GALLETAS MARIA", "UN")],
    "No comestibles": [("90010", "SERVILLETAS PAPEL", "UN"), ("90011", "BOLSAS BASURA", "UN")],
}
PESO = {"Frutas y Verduras": 3, "Panadería y bollería": 3, "Lacteos y Huevos": 3}


def numero(fecha: dt.date, orden: int) -> str:
    return f"DON{CENTRO}{fecha:%Y%m%d}{orden:05d}"


def cantidad(unidad: str, rng: random.Random) -> float:
    return float(rng.randint(2, 18)) if unidad == "UN" else round(rng.uniform(1.2, 9.8), 2)


def albaran_del_dia(fecha: dt.date, orden: int, rng: random.Random) -> list[tuple]:
    catalogo = [(cat, *p) for cat, ps in PRODUCTOS.items() for p in ps]
    pesos = [PESO.get(c[0], 1) for c in catalogo]
    elegidos = {}
    while len(elegidos) < rng.randint(9, 14):
        c = rng.choices(catalogo, pesos)[0]
        elegidos[c[1]] = c
    return list(elegidos.values())


def crear_pdf_ejemplo(ruta: Path, fecha: dt.date, filas: list[tuple]) -> None:
    c = canvas.Canvas(str(ruta), pagesize=A4)
    ancho, alto = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, alto - 2.5 * cm, "PROVEEDOR EJEMPLO S.A.")
    c.setFont("Helvetica", 11)
    c.drawString(2 * cm, alto - 3.3 * cm, "ALBARAN DE DONACION (documento ficticio)")
    c.drawString(2 * cm, alto - 4.1 * cm, f"Fecha: {fecha:%d-%m-%Y}")
    c.drawString(2 * cm, alto - 4.9 * cm, f"Albaran: {numero(fecha, 1)}")
    y = alto - 6.5 * cm
    c.setFont("Helvetica-Bold", 11)
    for texto, x in (("Codigo", 2), ("Descripcion", 4.2), ("Cantidad", 14.2), ("Unidad", 17)):
        c.drawString(x * cm, y, texto)
    c.line(2 * cm, y - 0.2 * cm, ancho - 2 * cm, y - 0.2 * cm)
    c.setFont("Helvetica", 11)
    for _cat, codigo, desc, unidad in filas:
        y -= 0.8 * cm
        c.drawString(2 * cm, y, codigo)
        c.drawString(4.2 * cm, y, desc)
        q = "8,000" if unidad == "UN" else "4,250"
        c.drawRightString(16.2 * cm, y, q)
        c.drawString(17 * cm, y, unidad)
    c.setFillColor(colors.grey)
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(2 * cm, 1.5 * cm, "Datos inventados. No corresponde a ninguna empresa real.")
    c.save()


def main(destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "registro.db").unlink(missing_ok=True)
    rng = random.Random(7)
    con = abrir_base(destino / "registro.db")
    guardar_personas(con, 50)
    guardar_inicio_registro(con, dt.date(2026, 11, 1))
    # Octubre (solo «recibido») y noviembre hasta el día 9
    dias = [dt.date(2026, 10, 1) + dt.timedelta(days=i) for i in range(40)]
    dias = [d for d in dias if d <= dt.date(2026, 11, 9) and d.weekday() < 6]
    primero_nov = None
    for fecha in dias:
        filas = albaran_del_dia(fecha, 1, rng)
        lineas = [Linea(codigo=c, descripcion=d, cantidad=cantidad(u, rng), unidad=u)
                  for _cat, c, d, u in filas]
        categorias = {c: cat for cat, c, _d, _u in filas}
        guardar_albaran(con, fecha, numero(fecha, 1), lineas, categorias_elegidas=categorias)
        if fecha >= dt.date(2026, 11, 1):
            primero_nov = primero_nov or fecha
            desechos = []
            if fecha.day in (4, 6):
                desechos = [Salida(fecha, "Frutas y Verduras", 0.8, "caducado o desechado",
                                   unidad="KG")]
            guardar_control(con, fecha, desechos, responsable="Responsable de cocina",
                            nota="Producto en mal estado" if desechos else "")
    for categoria, unidad in (("Despensa", "UN"), ("No comestibles", "UN")):
        guardar_recuento(con, dt.date(2026, 10, 1), categoria, unidad, 0.0)
    guardar_recapitulativo(con, dt.date(2026, 10, 1), None, None)
    filas = albaran_del_dia(dt.date(2026, 11, 9), 1, random.Random(3))
    crear_pdf_ejemplo(destino / "albaran_ejemplo.pdf", dt.date(2026, 11, 10), filas[:12])
    print(f"Datos de demostración creados en {destino}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("datos_demo"))
