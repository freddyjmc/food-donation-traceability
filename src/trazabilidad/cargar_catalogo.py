"""Carga el catálogo inicial desde el Excel antiguo.

Uso (desde la carpeta del proyecto, con el entorno activado):
    python -m trazabilidad.cargar_catalogo "C:\\ruta\\SEPTIEMBRE_2025.xlsx"
"""

import csv
import os
import sys
from pathlib import Path

from trazabilidad.catalogo import cargar_catalogo, construir_catalogo, leer_codigos_excel
from trazabilidad.registro import abrir_base


def cargar(ruta_excel: str | Path, datos: str | Path) -> dict:
    """Lee el Excel, carga el catálogo en datos/registro.db y guarda los conflictos en un CSV."""
    datos = Path(datos)
    datos.mkdir(parents=True, exist_ok=True)
    lineas = leer_codigos_excel(ruta_excel)
    catalogo, conflictos = construir_catalogo(lineas)
    con = abrir_base(datos / "registro.db")
    anadidos = cargar_catalogo(con, catalogo)
    csv_conflictos = datos / "conflictos_catalogo.csv"
    with open(csv_conflictos, "w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.writer(archivo, delimiter=";")
        escritor.writerow(["codigo", "categoria_elegida", "categorias_en_el_excel"])
        for codigo, categorias in sorted(conflictos.items()):
            escritor.writerow([codigo, catalogo[codigo], " | ".join(categorias)])
    return {
        "lineas": len(lineas),
        "codigos": len(catalogo),
        "anadidos": anadidos,
        "conflictos": len(conflictos),
        "csv": csv_conflictos,
    }


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Uso: python -m trazabilidad.cargar_catalogo RUTA_DEL_EXCEL.xlsx")
    datos = os.environ.get("TRAZABILIDAD_DATOS", Path(__file__).resolve().parents[2] / "datos")
    r = cargar(sys.argv[1], datos)
    print(f"Líneas leídas del Excel: {r['lineas']}")
    print(f"Códigos distintos: {r['codigos']} (añadidos al catálogo: {r['anadidos']})")
    print(f"Códigos en más de una categoría: {r['conflictos']} (se eligió la más reciente)")
    print(f"Revísalos en: {r['csv']}")


if __name__ == "__main__":
    main()
