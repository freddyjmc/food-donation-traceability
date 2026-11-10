"""Datos y colores de los gráficos de círculo (los usan el PDF y la pantalla)."""

from trazabilidad.informes import Informe

COLOR_CATEGORIA = {
    "Panadería y bollería": "#E69F00",
    "Lacteos y Huevos": "#56B4E9",
    "Carnes y Embutidos": "#D55E00",
    "Pescados y Mariscos": "#0072B2",
    "Frutas y Verduras": "#009E73",
    "Comida preparada y congelados": "#CC79A7",
    "Despensa": "#8C6D31",
    "Bebida y Snacks": "#6C757D",
    "No comestibles": "#BDBDBD",
}
COLOR_EXTRA = "#999999"
COLOR_DESTINO = {"Consumido": "#2A9D8F", "Tirado": "#E76F51", "Guardado en almacén": "#8D99AE"}
COLOR_DIAS = {
    "Con albarán y control": "#2A9D8F",
    "Con albarán, sin control": "#E9C46A",
    "Sin albarán": "#CED4DA",
}

Rebanada = tuple[str, float, str]  # (nombre, valor, color)


def recibido_por_categoria(informe: Informe) -> list[Rebanada]:
    """Unidades (UN) recibidas por categoría, de mayor a menor."""
    filas = [(f.categoria, f.entradas, COLOR_CATEGORIA.get(f.categoria, COLOR_EXTRA))
             for f in informe.balance if f.unidad == "UN" and f.entradas > 0]
    return sorted(filas, key=lambda r: -r[1])


def destino(informe: Informe) -> list[Rebanada]:
    """Qué pasó con lo recibido (UN): consumido, tirado y guardado en el almacén."""
    un = [f for f in informe.balance if f.unidad == "UN"]
    datos = {
        "Consumido": sum(f.consumo for f in un),
        "Tirado": sum(f.desechado + f.otros for f in un),
        "Guardado en almacén": sum(f.final for f in un),
    }
    return [(n, round(v, 3), COLOR_DESTINO[n]) for n, v in datos.items() if v > 0]


def dias_del_mes(informe: Informe) -> list[Rebanada]:
    """Días del mes según tuvieran albarán y control de aptitud."""
    sin_albaran = len(informe.dias_sin_albaran)
    con_albaran = informe.dias - sin_albaran
    sin_control = len(informe.dias_sin_control)
    datos = {
        "Con albarán y control": con_albaran - sin_control,
        "Con albarán, sin control": sin_control,
        "Sin albarán": sin_albaran,
    }
    return [(n, float(v), COLOR_DIAS[n]) for n, v in datos.items() if v > 0]


def consumo_por_persona_dia(informe: Informe) -> float:
    """Unidades (UN) consumidas por persona y día."""
    total = sum(f.consumo for f in informe.balance if f.unidad == "UN")
    return round(total / informe.dias / informe.personas, 2) if informe.personas else 0.0
