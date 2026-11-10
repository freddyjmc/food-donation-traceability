"""Archivar el PDF (o foto) de cada albarán por mes, con el nº de albarán como nombre."""

import datetime as dt
import shutil
from pathlib import Path


def archivar_pdf(
    origen: str | Path, carpeta_base: str | Path, fecha: dt.date, num_albaran: str
) -> Path:
    """Copia el archivo a  <carpeta_base>/AAAA-MM/<nº albarán>.<extensión>  y devuelve su ruta."""
    origen = Path(origen)
    destino = Path(carpeta_base) / fecha.strftime("%Y-%m") / f"{num_albaran}{origen.suffix.lower()}"
    if destino.exists():
        raise FileExistsError(f"Ya hay un archivo guardado con el nombre {destino.name}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origen, destino)
    return destino
