"""Escribe el informe mensual en Excel: una hoja de resumen para imprimir en A4 y hojas de
detalle (consumo, entradas, salidas, incidencias). Paso 8."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from trazabilidad.config import CENTRO, ORIGEN
from trazabilidad.informes import Informe
from trazabilidad.revision import CATEGORIAS_BASE

AZUL, VERDE, ROJO = "2F5D8A", "3E8E6B", "C0504D"
CABECERA = PatternFill("solid", fgColor="1F3A5F")
SUAVE = PatternFill("solid", fgColor="EAF0F7")
ALERTA = PatternFill("solid", fgColor="FBE5E4")
BUENO = PatternFill("solid", fgColor="E3F2EA")
FINO = Side(style="thin", color="B8C4D2")
BORDE = Border(left=FINO, right=FINO, top=FINO, bottom=FINO)
MESES = ("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre "
         "diciembre").split()


def ruta_informe(base: Path, anio: int, mes: int) -> Path:
    """datos/informes/2026/2026-10.xlsx"""
    return base / str(anio) / f"{anio}-{mes:02d}.xlsx"


def _cabecera(ws, fila: int, textos: list[str], columna: int = 1) -> None:
    for n, texto in enumerate(textos):
        c = ws.cell(row=fila, column=columna + n, value=texto)
        c.fill, c.font, c.border = CABECERA, Font(bold=True, color="FFFFFF"), BORDE
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _celda(ws, fila: int, columna: int, valor, negrita: bool = False, relleno=None, formato=None):
    c = ws.cell(row=fila, column=columna, value=valor)
    c.border, c.font = BORDE, Font(bold=negrita)
    if relleno:
        c.fill = relleno
    if formato:
        c.number_format = formato
    if isinstance(valor, int | float):
        c.alignment = Alignment(horizontal="right")
    return c


def _subtitulo(ws, fila: int, texto: str) -> None:
    ws.cell(row=fila, column=1, value=texto).font = Font(bold=True)


def _anchos(ws, anchos: list[float]) -> None:
    for n, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(n)].width = ancho


def _imprimir_a4(ws, vertical: bool = True, una_hoja: bool = False) -> None:
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "portrait" if vertical else "landscape"
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1 if una_hoja else 0
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top = ws.page_margins.bottom = 0.5
    ws.oddFooter.center.text = "Página &P de &N"
    ws.oddFooter.left.text = CENTRO


def _titulo(informe: Informe) -> str:
    nombre = f"{MESES[informe.desde.month - 1].capitalize()} de {informe.desde.year}"
    return f"Informe mensual de donaciones — {nombre}"


def _suma(filas, atributo: str, unidad: str) -> float:
    return round(sum(getattr(f, atributo) for f in filas if f.unidad == unidad), 3)


def _hoja_resumen(wb: Workbook, informe: Informe, filas_semana: tuple[int, int],
                  filas_cat: tuple[int, int]) -> None:
    ws = wb.active
    ws.title = "Resumen"
    _anchos(ws, [30, 7, 13, 13, 13, 13, 11, 13, 15])
    ws.merge_cells("A1:I1")
    ws["A1"] = "Registro de trazabilidad de donaciones de alimentos"
    ws["A1"].font = Font(bold=True, size=15, color="1F3A5F")
    ws.merge_cells("A2:I2")
    ws["A2"] = f"{CENTRO} · Origen: {ORIGEN} · Ley 1/2025"
    ws["A2"].font = Font(color="555555")
    ws.merge_cells("A3:I3")
    ws["A3"] = (f"{_titulo(informe)} · Periodo {informe.desde:%d/%m/%Y} – {informe.hasta:%d/%m/%Y}"
                f" · {informe.personas} personas · {informe.dias} días")
    ws["A3"].font = Font(bold=True, size=11)

    balance = informe.balance
    recibido, consumido = _suma(balance, "entradas", "UN"), _suma(balance, "consumo", "UN")
    desechado = _suma(balance, "desechado", "UN") + _suma(balance, "otros", "UN")
    cuadros = [
        ("Albaranes recibidos", informe.albaranes),
        ("Unidades recibidas", recibido),
        ("Unidades desechadas u otras", desechado),
        ("Unidades consumidas (calculado)", consumido),
    ]
    for n, (texto, valor) in enumerate(cuadros):
        ini = [1, 3, 5, 7][n]
        fin = [2, 4, 6, 9][n]
        ws.merge_cells(start_row=5, start_column=ini, end_row=5, end_column=fin)
        ws.merge_cells(start_row=6, start_column=ini, end_row=6, end_column=fin)
        c = ws.cell(row=5, column=ini, value=texto)
        c.font, c.fill = Font(size=9, color="555555"), SUAVE
        c.alignment = Alignment(horizontal="center")
        v = ws.cell(row=6, column=ini, value=valor)
        v.font, v.fill = Font(bold=True, size=18, color="1F3A5F"), SUAVE
        v.alignment = Alignment(horizontal="center")
    ws.merge_cells("A7:I7")
    ws["A7"] = (
        f"Control diario de aptitud: anotado en {informe.controles_hechos} de "
        f"{informe.dias} días del mes; días en los que se tiró algo: {informe.dias_con_desecho}."
    )
    ws["A7"].font = Font(size=9, bold=True, color="1F3A5F")
    kg = [f for f in balance if f.unidad != "UN"]
    if kg:
        ws.merge_cells("A8:I8")
        unidades = sorted({f.unidad for f in kg})
        partes = [
            f"{u}: recibidos {_suma(kg, 'entradas', u):g}, consumidos {_suma(kg, 'consumo', u):g}, "
            f"desechados {_suma(kg, 'desechado', u) + _suma(kg, 'otros', u):g}"
            for u in unidades
        ]
        ws["A8"] = "Otras unidades — " + " · ".join(partes)
        ws["A8"].font = Font(size=9, italic=True, color="555555")

    fila = 9
    ws.cell(row=fila, column=1, value="Balance del mes por categoría").font = Font(
        bold=True, size=12, color="1F3A5F"
    )
    fila += 1
    _cabecera(ws, fila, ["Categoría", "Ud.", "Al empezar el mes", "Recibido",
                         "Consumido (calculado)", "Desechado", "Otros",
                         "Almacenado al cerrar", "Comprobación"])
    ws.row_dimensions[fila].height = 30
    for f in balance:
        fila += 1
        cuadra = abs(f.diferencia) < 0.0005
        etiqueta = "Cuadra" if cuadra else "Revisar"
        if cuadra and f.estimado:
            etiqueta = "Estimado"
        _celda(ws, fila, 1, f.categoria)
        _celda(ws, fila, 2, f.unidad)
        for col, valor in enumerate(
            [f.inicial, f.entradas, f.consumo, f.desechado, f.otros, f.final], start=3
        ):
            _celda(ws, fila, col, valor, negrita=col == 8)
        _celda(ws, fila, 9, etiqueta, relleno=BUENO if etiqueta == "Cuadra" else ALERTA)
    for unidad in sorted({f.unidad for f in balance}, key=lambda u: (u != "UN", u)):
        fila += 1
        _celda(ws, fila, 1, f"TOTAL {unidad}", negrita=True, relleno=SUAVE)
        _celda(ws, fila, 2, unidad, relleno=SUAVE)
        for col, atributo in enumerate(
            ["inicial", "entradas", "consumo", "desechado", "otros", "final"], start=3
        ):
            _celda(ws, fila, col, _suma(balance, atributo, unidad), negrita=True, relleno=SUAVE)
        _celda(ws, fila, 9, "", relleno=SUAVE)
    fila += 1
    ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=9)
    c = ws.cell(row=fila, column=1)
    if informe.cuadra:
        c.value = ("✔ Balance: consumido = lo que había + lo recibido − lo desechado − lo que "
                   "queda almacenado (despensa y no comestibles, por recuento).")
        c.fill = BUENO
    else:
        c.value = "⚠ Hay categorías que no cuadran: revisa la hoja Incidencias antes de imprimir."
        c.fill = ALERTA
    c.font = Font(bold=True, size=10)
    c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[fila].height = 30

    fila += 2
    comienzo_graficas = fila
    consumo_ws = wb["Consumo"]
    grafica = BarChart()
    grafica.type, grafica.title = "bar", "Unidades por categoría (UN)"
    grafica.add_data(
        Reference(consumo_ws, min_col=2, max_col=4, min_row=filas_cat[0] - 1, max_row=filas_cat[1]),
        titles_from_data=True,
    )
    grafica.set_categories(
        Reference(consumo_ws, min_col=1, min_row=filas_cat[0], max_row=filas_cat[1])
    )
    for serie, color in zip(grafica.series, (AZUL, VERDE, ROJO), strict=True):
        serie.graphicalProperties.solidFill = color
    grafica.height, grafica.width = 7.5, 12.5
    ws.add_chart(grafica, f"A{comienzo_graficas}")

    semanal = BarChart()
    semanal.type, semanal.title = "col", "Evolución por semanas (UN)"
    semanal.add_data(
        Reference(consumo_ws, min_col=2, max_col=4, min_row=filas_semana[0] - 1,
                  max_row=filas_semana[1]),
        titles_from_data=True,
    )
    semanal.set_categories(
        Reference(consumo_ws, min_col=1, min_row=filas_semana[0], max_row=filas_semana[1])
    )
    for serie, color in zip(semanal.series, (AZUL, VERDE, ROJO), strict=True):
        serie.graphicalProperties.solidFill = color
    semanal.height, semanal.width = 7.5, 11.5
    ws.add_chart(semanal, f"E{comienzo_graficas}")

    fila = comienzo_graficas + 16
    ws.cell(row=fila, column=1, value="Observaciones del mes").font = Font(
        bold=True, size=12, color="1F3A5F"
    )
    fila += 1
    ws.merge_cells(start_row=fila, start_column=1, end_row=fila + 3, end_column=9)
    c = ws.cell(row=fila, column=1, value=informe.comentarios or None)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    for f in range(fila, fila + 4):
        for col in range(1, 10):
            ws.cell(row=f, column=col).border = BORDE
    fila += 5
    ws.merge_cells(start_row=fila, start_column=1, end_row=fila + 1, end_column=9)
    c = ws.cell(
        row=fila, column=1,
        value=("Declaración de la dirección: los alimentos recibidos en el mes y no desechados "
               "se han destinado al consumo de las personas atendidas en la residencia, y el "
               "control diario de aptitud queda registrado en este informe."),
    )
    c.font = Font(size=9, italic=True)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    fila += 3
    ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=4)
    ws.merge_cells(start_row=fila, start_column=5, end_row=fila, end_column=9)
    ws.cell(row=fila, column=1, value="Elaborado por: ________________  Fecha: ___/___/______")
    ws.cell(row=fila, column=5, value="Vº Bº Dirección: ________________  Fecha: ___/___/______")
    ws.print_area = f"A1:I{fila}"
    _imprimir_a4(ws, vertical=True, una_hoja=True)


def _hoja_consumo(wb: Workbook, informe: Informe) -> tuple[tuple[int, int], tuple[int, int]]:
    ws = wb.create_sheet("Consumo")
    _anchos(ws, [30, 14, 14, 14, 16, 16, 16, 16])
    ws["A1"] = "Consumo del mes y comparación"
    ws["A1"].font = Font(bold=True, size=13, color="1F3A5F")
    ws["A2"] = ("El consumo se calcula: lo recibido menos lo desechado y lo almacenado. "
                f"«Por persona y día» se calcula con {informe.personas} personas.")
    ws["A2"].font = Font(size=9, italic=True, color="555555")

    fila = 4
    _cabecera(ws, fila, ["Categoría", "Unidad", "Consumido (calculado)", "Media diaria",
                         "Por persona y día", "Mes anterior", "Media 3 meses previos",
                         "Cambio vs mes anterior"])
    ws.row_dimensions[fila].height = 32
    for f in informe.consumo:
        fila += 1
        cambio = (f.total - f.mes_anterior) / f.mes_anterior if f.mes_anterior else None
        _celda(ws, fila, 1, f.categoria)
        _celda(ws, fila, 2, f.unidad)
        for col, valor in enumerate(
            [f.total, f.media_diaria, f.por_persona_dia, f.mes_anterior, f.media_3_meses],
            start=3,
        ):
            _celda(ws, fila, col, valor)
        _celda(ws, fila, 8, cambio if cambio is not None else "—", formato="+0%;-0%;0%")

    fila += 3
    _subtitulo(ws, fila - 1, "Unidades (UN) por categoría — datos de la gráfica")
    _cabecera(ws, fila, ["Categoría", "Recibido", "Consumido", "Desechado"])
    inicio = fila + 1
    en_un = {f.categoria: f for f in informe.balance if f.unidad == "UN"}
    categorias = list(CATEGORIAS_BASE) + [c for c in en_un if c not in CATEGORIAS_BASE]
    for categoria in categorias:
        fila += 1
        f = en_un.get(categoria)
        _celda(ws, fila, 1, categoria)
        _celda(ws, fila, 2, f.entradas if f else 0)
        _celda(ws, fila, 3, f.consumo if f else 0)
        _celda(ws, fila, 4, (f.desechado + f.otros) if f else 0)
    filas_cat = (inicio, fila)

    fila += 3
    _subtitulo(ws, fila - 1, "Por semanas (UN) — datos de la gráfica")
    _cabecera(ws, fila, ["Semana", "Recibido", "Consumido", "Desechado"])
    inicio = fila + 1
    for semana in informe.semanas:
        fila += 1
        _celda(ws, fila, 1, semana["semana"])
        _celda(ws, fila, 2, semana["entradas"])
        _celda(ws, fila, 3, semana["consumo"])
        _celda(ws, fila, 4, semana["desechado"])
    filas_semana = (inicio, fila)

    fila += 3
    _subtitulo(ws, fila - 1, "10 productos más recibidos del mes")
    _cabecera(ws, fila, ["Descripción", "Código", "Categoría", "Cantidad", "Unidad"])
    for p in informe.top_productos:
        fila += 1
        _celda(ws, fila, 1, p["descripcion"])
        _celda(ws, fila, 2, p["codigo"])
        _celda(ws, fila, 3, p["categoria"])
        _celda(ws, fila, 4, p["cantidad"])
        _celda(ws, fila, 5, p["unidad"])
    _imprimir_a4(ws, vertical=False)
    return filas_cat, filas_semana


def _hoja_listado(wb: Workbook, nombre: str, titulos: list[str], filas: list[list],
                  anchos: list[float]) -> None:
    ws = wb.create_sheet(nombre)
    _anchos(ws, anchos)
    _cabecera(ws, 1, titulos)
    for n, fila in enumerate(filas, start=2):
        for col, valor in enumerate(fila, start=1):
            c = ws.cell(row=n, column=col, value=valor)
            c.border = BORDE
            if hasattr(valor, "year"):
                c.number_format = "DD/MM/YYYY"
    ws.freeze_panes = "A2"
    if filas:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(titulos))}{len(filas) + 1}"
    ws.print_title_rows = "1:1"
    _imprimir_a4(ws, vertical=False)


def _hoja_incidencias(wb: Workbook, informe: Informe) -> None:
    ws = wb.create_sheet("Incidencias")
    _anchos(ws, [4, 110])
    ws["A1"] = "Incidencias y puntos a revisar"
    ws["A1"].font = Font(bold=True, size=13, color="1F3A5F")
    if not informe.incidencias:
        ws["A3"] = "Sin incidencias."
    for n, texto in enumerate(informe.incidencias, start=3):
        ws.cell(row=n, column=1, value=n - 2)
        c = ws.cell(row=n, column=2, value=texto)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    _imprimir_a4(ws, vertical=False)


def escribir_excel(informe: Informe, ruta: Path) -> Path:
    """Guarda el informe en `ruta` (crea las carpetas que falten) y la devuelve."""
    wb = Workbook()
    wb.active.title = "Resumen"
    # Consumo se crea antes que el resumen termine para que las gráficas puedan apuntar a él.
    filas_cat, filas_semana = _hoja_consumo(wb, informe)
    _hoja_resumen(wb, informe, filas_semana, filas_cat)
    _hoja_listado(
        wb, "Albaranes",
        ["Fecha", "Nº albarán", "Origen", "Líneas", "Unidades (UN)", "Kilos (KG)", "Categorías",
         "Consumir antes de (aprox.)", "Incluye despensa / almacenable"],
        [[a["fecha"], a["num_albaran"], ORIGEN, a["lineas"], a["unidades"],
          a["kilos"], a["categorias"], a["consumir_antes"],
          "Sí: según envase" if a["almacenable"] else "No"]
         for a in informe.detalle_albaranes],
        [12, 24, 24, 8, 14, 12, 60, 18, 24],
    )
    _hoja_listado(
        wb, "Entradas",
        ["Fecha", "Nº albarán", "Código", "Descripción", "Categoría", "Cantidad", "Unidad"],
        [[x.fecha, x.num_albaran, x.codigo, x.descripcion, x.categoria, x.cantidad, x.unidad]
         for x in informe.entradas_mes],
        [12, 24, 10, 38, 30, 10, 8],
    )
    _hoja_listado(
        wb, "Salidas",
        ["Fecha", "Categoría", "Cantidad", "Unidad", "Motivo"],
        [[x.fecha, x.categoria, x.unidades, x.unidad, x.motivo]
         for x in sorted(informe.salidas_mes, key=lambda s: (s.fecha, s.id or 0))],
        [12, 32, 10, 8, 24],
    )
    _hoja_listado(
        wb, "Control diario",
        ["Fecha", "¿Se tiró algo?", "Responsable", "Nota"],
        [[c.fecha, "Sí" if c.hubo_desecho else "No, todo apto", c.responsable, c.nota]
         for c in informe.controles_mes],
        [12, 18, 24, 60],
    )
    _hoja_incidencias(wb, informe)
    wb.move_sheet("Resumen", offset=-wb.index(wb["Resumen"]))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta)
    return ruta
