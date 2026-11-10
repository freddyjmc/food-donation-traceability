"""Informe mensual en PDF de 2 hojas, pensado para leerse de un vistazo (con gráficos de
círculo y leyendas). Complementa al Excel, que queda como detalle."""

import datetime as dt
from pathlib import Path

from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    KeepInFrame,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from trazabilidad.config import CENTRO, ORIGEN
from trazabilidad.controles import ALMACENABLES
from trazabilidad.graficos import (
    Rebanada,
    consumo_por_persona_dia,
    destino,
    dias_del_mes,
    recibido_por_categoria,
)
from trazabilidad.informes import Informe

AZUL = colors.HexColor("#1F3A5F")
GRIS = colors.HexColor("#555555")
FONDO = colors.HexColor("#EAF0F7")
MESES = ("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre "
         "diciembre").split()
DIAS_SEMANA = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def numero(valor: float, decimales: int | None = None) -> str:
    """2739 -> '2.739' · 1001.64 -> '1.001,64' (formato español)."""
    if decimales is None:
        decimales = 0 if abs(valor - round(valor)) < 0.0005 else 2
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def ruta_pdf(base: Path, anio: int, mes: int) -> Path:
    """datos/informes/2026/2026-01/informe_2026-01.pdf (todo el mes en una carpeta)"""
    return base / str(anio) / f"{anio}-{mes:02d}" / f"informe_{anio}-{mes:02d}.pdf"


def _estilos() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "titulo": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=20,
                                 textColor=AZUL, leading=24),
        "sub": ParagraphStyle("s", parent=base, fontSize=10, textColor=GRIS, leading=13),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=13,
                             textColor=AZUL, leading=16, spaceBefore=4, spaceAfter=4),
        "texto": ParagraphStyle("p", parent=base, fontSize=9.5, leading=12.5),
        "nota": ParagraphStyle("n", parent=base, fontSize=8, textColor=GRIS, leading=10.5),
        "leyenda": ParagraphStyle("l", parent=base, fontSize=9, leading=11),
        "cifra": ParagraphStyle("c", parent=base, fontName="Helvetica-Bold", fontSize=22,
                                textColor=AZUL, leading=26, alignment=1),
        "cifra_t": ParagraphStyle("ct", parent=base, fontSize=8.5, textColor=GRIS, leading=10,
                                  alignment=1),
        "grande": ParagraphStyle("g", parent=base, fontName="Helvetica-Bold", fontSize=34,
                                 textColor=AZUL, leading=38),
    }


def _anillo(rebanadas: list[Rebanada], centro: str, tamano: float = 5.0 * cm) -> Drawing:
    dibujo = Drawing(tamano, tamano)
    tarta = Pie()
    tarta.x = tarta.y = tamano * 0.04
    tarta.width = tarta.height = tamano * 0.92
    tarta.sideLabels = False
    tarta.innerRadiusFraction = 0.58
    tarta.startAngle = 90
    tarta.direction = "clockwise"
    if rebanadas:
        tarta.data = [r[1] for r in rebanadas]
        for n, r in enumerate(rebanadas):
            tarta.slices[n].fillColor = colors.HexColor(r[2])
            tarta.slices[n].strokeColor = colors.white
            tarta.slices[n].strokeWidth = 1.5
    else:
        tarta.data = [1]
        tarta.slices[0].fillColor = colors.HexColor("#E3E6EA")
        tarta.slices[0].strokeColor = colors.white
    dibujo.add(tarta)
    dibujo.add(String(tamano / 2, tamano / 2 - 4, centro, textAnchor="middle",
                      fontName="Helvetica-Bold", fontSize=14, fillColor=AZUL))
    return dibujo


def _porcentaje(valor: float, total: float) -> str:
    pct = 100 * valor / total
    return "<1 %" if 0 < pct < 1 else f"{pct:.0f} %"


def _leyenda(rebanadas: list[Rebanada], estilos: dict, unidad: str = "") -> Table:
    total = sum(r[1] for r in rebanadas) or 1
    filas = [["", Paragraph(r[0], estilos["leyenda"]),
              Paragraph(f"<b>{numero(r[1])}</b>{unidad}", estilos["leyenda"]),
              Paragraph(_porcentaje(r[1], total), estilos["leyenda"])] for r in rebanadas]
    if not filas:
        filas = [["", Paragraph("Sin datos", estilos["leyenda"]), "", ""]]
    tabla = Table(filas, colWidths=[0.45 * cm, 4.6 * cm, 1.7 * cm, 1.2 * cm])
    estilo = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (2, 0), (3, -1), "RIGHT"),
              ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
              ("LEFTPADDING", (1, 0), (1, -1), 6)]
    for n, r in enumerate(rebanadas):
        estilo.append(("BACKGROUND", (0, n), (0, n), colors.HexColor(r[2])))
        estilo.append(("LINEBELOW", (0, n), (0, n), 2, colors.white))
    tabla.setStyle(TableStyle(estilo))
    return tabla


def _bloque_grafico(titulo: str, pregunta: str, rebanadas: list[Rebanada], centro: str,
                    estilos: dict, unidad: str = "", ancho: float = 8.8 * cm) -> Table:
    contenido = [
        [Paragraph(titulo, estilos["h2"])],
        [Paragraph(pregunta, estilos["nota"])],
        [_anillo(rebanadas, centro)],
        [_leyenda(rebanadas, estilos, unidad)],
    ]
    tabla = Table(contenido, colWidths=[ancho])
    tabla.setStyle(TableStyle([("ALIGN", (0, 2), (0, 2), "CENTER"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 2),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return tabla


def _cifras(informe: Informe, estilos: dict) -> Table:
    un = [f for f in informe.balance if f.unidad == "UN"]
    recibido = sum(f.entradas for f in un)
    consumido = sum(f.consumo for f in un)
    almacenado = sum(f.final for f in un)
    if informe.sin_registro:
        kilos = sum(f.entradas for f in informe.balance if f.unidad == "KG")
        datos = [("Albaranes recibidos", informe.albaranes),
                 ("Líneas de producto", informe.lineas), ("Unidades recibidas", recibido),
                 ("Kilos recibidos (líneas en kg)", kilos)]
    else:
        datos = [("Albaranes recibidos", informe.albaranes), ("Unidades recibidas", recibido),
                 ("Unidades consumidas", consumido), ("Guardadas en almacén", almacenado)]
    tabla = Table(
        [[Paragraph(numero(v, 2 if isinstance(v, float) and v % 1 else 0), estilos["cifra"])
          for _, v in datos],
         [Paragraph(t, estilos["cifra_t"]) for t, _ in datos]],
        colWidths=[4.4 * cm] * 4,
    )
    tabla.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FONDO),
                               ("LINEAFTER", (0, 0), (-2, -1), 1, colors.white),
                               ("TOPPADDING", (0, 0), (-1, 0), 8),
                               ("BOTTOMPADDING", (0, 1), (-1, 1), 8)]))
    return tabla


def _balance(informe: Informe, estilos: dict) -> Table:
    if informe.sin_registro:
        filas = [["Categoría", "Ud.", "Recibido"]]
        for f in informe.balance:
            filas.append([Paragraph(f.categoria, estilos["leyenda"]), f.unidad, numero(f.entradas)])
        anchos = [11.0 * cm, 2.4 * cm, 4.0 * cm]
    else:
        filas = [["Categoría", "Ud.", "Recibido", "Tirado", "Consumido", "Almacenado"]]
        for f in informe.balance:
            filas.append([Paragraph(f.categoria, estilos["leyenda"]), f.unidad,
                          numero(f.entradas), numero(f.desechado + f.otros), numero(f.consumo),
                          numero(f.final)])
        anchos = [6.2 * cm, 1.2 * cm, 2.5 * cm, 2.3 * cm, 2.6 * cm, 2.6 * cm]
    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FB")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#D5DCE6")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tabla


def _hoja2_sin_registro(informe: Informe, estilos: dict) -> list:
    return [
        Paragraph("Recibido por categoría", estilos["h2"]),
        Paragraph("Mes anterior al inicio del registro diario: solo se documenta lo recibido.",
                  estilos["nota"]),
        Spacer(1, 0.2 * cm),
    ]


def _almacen(informe: Informe, estilos: dict) -> list:
    """Despensa y no comestibles: de dónde viene lo almacenado y a dónde va, mes a mes."""
    filas = [f for f in informe.balance if f.categoria in ALMACENABLES]
    if not filas:
        return []
    datos = [["Almacén", "Ud.", "Había al empezar", "+ Recibido", "- Usado", "= Queda"]]
    for f in filas:
        datos.append([Paragraph(f.categoria + (" (estimado)" if f.estimado else ""),
                                estilos["leyenda"]), f.unidad, numero(f.inicial),
                      numero(f.entradas), numero(f.consumo + f.desechado + f.otros),
                      numero(f.final)])
    tabla = Table(datos, colWidths=[5.0 * cm, 1.2 * cm, 3.2 * cm, 2.6 * cm, 2.6 * cm, 3.2 * cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#FFF6E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [
        Paragraph("Lo que se guarda en el almacén", estilos["h2"]),
        Paragraph("Lo que queda al cerrar el mes se cuenta físicamente y es lo que había al "
                  "empezar el mes siguiente. Así se sigue la despensa de un mes a otro hasta "
                  "usarla.", estilos["nota"]),
        Spacer(1, 0.15 * cm), tabla, Spacer(1, 0.3 * cm),
    ]


class _LienzoNumerado(canvas.Canvas):
    """Pone «Página X de N» y el pie en cada hoja."""

    titulo_pie = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas: list[dict] = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for pagina in self._paginas:
            self.__dict__.update(pagina)
            self.setFont("Helvetica", 8)
            self.setFillColor(GRIS)
            self.drawString(1.6 * cm, 1.0 * cm, self.titulo_pie)
            self.drawRightString(A4[0] - 1.6 * cm, 1.0 * cm,
                                 f"Página {self._pageNumber} de {total}")
            super().showPage()
        super().save()


def escribir_pdf(informe: Informe, ruta: Path, inicio_registro: dt.date | None = None) -> Path:
    """Guarda el informe en PDF (2 hojas A4) en `ruta` y la devuelve."""
    estilos = _estilos()
    elaboracion = informe.fecha_elaboracion or dt.date.today()
    inicio = inicio_registro or dt.date.today()
    mes_nombre = f"{MESES[informe.desde.month - 1].capitalize()} de {informe.desde.year}"
    historia = [
        Paragraph("Registro de donaciones de alimentos", estilos["titulo"]),
        Paragraph(f"{CENTRO} · Origen: {ORIGEN} · Ley 1/2025", estilos["sub"]),
        Paragraph(f"<b>Informe de {mes_nombre}</b> · del {informe.desde:%d/%m/%Y} al "
                  f"{informe.hasta:%d/%m/%Y} · {informe.personas} personas · elaborado el "
                  f"{elaboracion:%d/%m/%Y}", estilos["sub"]),
        Spacer(1, 0.4 * cm),
        _cifras(informe, estilos),
        Spacer(1, 0.25 * cm),
    ]
    if informe.recap_kg or informe.recap_euros:
        partes = []
        if informe.recap_kg:
            partes.append(f"<b>{numero(informe.recap_kg, 2)} kg</b> donados")
        if informe.recap_euros:
            partes.append(f"valorados en <b>{numero(informe.recap_euros, 2)} €</b>")
        historia += [
            Paragraph("Según el albarán recapitulativo del donante: " + " · ".join(partes) + ". "
                      "El donante cuenta kilos y este registro cuenta unidades de cada línea del "
                      "albarán, por eso las dos cifras no se pueden comparar directamente.",
                      estilos["nota"]),
            Spacer(1, 0.2 * cm),
        ]
    if informe.albaranes_faltantes:
        historia += [Paragraph(
            f"<b>Pendiente de comprobar:</b> {len(informe.albaranes_faltantes)} albarán(es) del "
            "recapitulativo del donante no constan en este registro.", estilos["nota"]),
            Spacer(1, 0.2 * cm)]
    total_recibido = sum(r[1] for r in recibido_por_categoria(informe))
    total_destino = sum(r[1] for r in destino(informe))
    if informe.sin_registro:
        derecha = [
            Paragraph("¿Qué ha pasado con ello?", estilos["h2"]),
            Paragraph(
                "Este mes es anterior al inicio del registro diario de consumo y de lo tirado "
                f"({inicio:%d/%m/%Y}). Por eso <b>no se indican</b> cifras de consumo, de "
                "alimentos tirados ni de almacén: no se registraron y no se estiman. Este informe "
                "documenta lo recibido del donante.", estilos["texto"])]
    else:
        derecha = _bloque_grafico(
            "¿Qué ha pasado con ello?",
            "Lo recibido se da por consumido, salvo lo tirado y lo que se guarda.",
            destino(informe), numero(total_destino), estilos, " uds")
    graficos = Table(
        [[_bloque_grafico("¿Qué hemos recibido?", "Unidades recibidas, por tipo de alimento.",
                          recibido_por_categoria(informe), numero(total_recibido), estilos,
                          " uds"),
          derecha]],
        colWidths=[9.2 * cm, 8.6 * cm],
    )
    graficos.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    historia.append(graficos)
    historia += [Spacer(1, 0.15 * cm), Paragraph(
        "El gráfico cuenta unidades de cada línea del albarán, sin tener en cuenta su peso o "
        "tamaño: una unidad puede ser una pieza pequeña o un envase grande.", estilos["nota"])]
    if informe.controles_hechos == 0 and not informe.sin_registro:
        historia += [Spacer(1, 0.2 * cm), Paragraph(
            "Este mes no hay controles diarios de aptitud registrados: el control empezó después, "
            "por lo que no consta lo tirado.", estilos["nota"])]
    historia.append(PageBreak())

    # ----- hoja 2 -----
    if informe.sin_registro:
        historia += _hoja2_sin_registro(informe, estilos)
    else:
        por_persona = consumo_por_persona_dia(informe)
        consumido = sum(f.consumo for f in informe.balance if f.unidad == "UN")
        historia += [
            Paragraph("Consumo por persona y día", estilos["h2"]),
            Table([[Paragraph(numero(por_persona, 2), estilos["grande"]),
                    Paragraph(f"unidades por persona y día. Se calcula dividiendo las "
                              f"{numero(consumido)} unidades consumidas entre {informe.personas} "
                              f"personas y {informe.dias} días. Sirve para comprobar que la cifra "
                              "es razonable.", estilos["texto"])]],
                  colWidths=[4.2 * cm, 13.6 * cm]),
            Spacer(1, 0.3 * cm),
        ]
        dias = Table(
            [[_bloque_grafico("Control diario",
                               "Días del mes con albarán y con control de aptitud.",
                              dias_del_mes(informe), f"{informe.controles_hechos}/{informe.dias}",
                              estilos, " días", 6.8 * cm),
              [Paragraph("Balance por categoría", estilos["h2"]),
               Paragraph("Consumido = lo que había + lo recibido - lo tirado - lo que queda "
                         "almacenado (despensa y no comestibles, por recuento).",
                         estilos["nota"])]]],
            colWidths=[9.2 * cm, 8.6 * cm],
        )
        dias.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        historia.append(dias)
    if not informe.sin_registro:
        historia += _almacen(informe, estilos)
    historia += [Spacer(1, 0.2 * cm), _balance(informe, estilos), Spacer(1, 0.4 * cm),
                 Paragraph("Observaciones del mes", estilos["h2"])]
    texto = (informe.comentarios or "—").replace("\n", "<br/>")
    historia.append(KeepInFrame(17.8 * cm, 3.0 * cm, [Paragraph(texto, estilos["texto"])],
                                mode="shrink"))
    historia += [
        Spacer(1, 0.4 * cm),
        Paragraph(
            "Declaración de la Dirección: los alimentos recibidos en este mes constan en los "
            "albaranes archivados. El registro diario de consumo y de lo tirado comenzó el "
            f"{inicio:%d/%m/%Y}." if informe.sin_registro else
            "Declaración de la Dirección: los alimentos recibidos en el mes y no "
            "desechados se han destinado al consumo de las personas atendidas en la "
            "residencia, y el control diario de aptitud queda registrado en este informe.",
            estilos["nota"]),
        Spacer(1, 0.6 * cm),
        Table([["Elaborado por: ____________________", "Vº Bº Dirección: ____________________"],
               ["Fecha: ___ / ___ / ______", "Fecha: ___ / ___ / ______"]],
              colWidths=[8.9 * cm, 8.9 * cm], rowHeights=[0.6 * cm, 0.6 * cm]),
    ]

    ruta.parent.mkdir(parents=True, exist_ok=True)
    pie = f"{CENTRO} · Informe de {mes_nombre} · elaborado el {elaboracion:%d/%m/%Y}"
    lienzo = type("Lienzo", (_LienzoNumerado,), {"titulo_pie": pie})
    documento = SimpleDocTemplate(
        str(ruta), pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm,
        bottomMargin=1.6 * cm, title=f"Informe de donaciones - {mes_nombre}",
        author=CENTRO,
    )
    documento.build(historia, canvasmaker=lienzo)
    return ruta


def ruta_anexo(base: Path, anio: int, mes: int) -> Path:
    return base / str(anio) / f"{anio}-{mes:02d}" / f"anexo_albaranes_{anio}-{mes:02d}.pdf"


def escribir_anexo(informe: Informe, ruta: Path) -> Path:
    """Anexo en PDF: cada albarán del mes con todas sus líneas, y los puntos a revisar."""
    estilos = _estilos()
    mes_nombre = f"{MESES[informe.desde.month - 1].capitalize()} de {informe.desde.year}"
    historia = [
        Paragraph("Anexo: albaranes recibidos con todo su detalle", estilos["titulo"]),
        Paragraph(f"{CENTRO} · {mes_nombre} · {informe.albaranes} albaranes · "
                  f"{informe.lineas} líneas", estilos["sub"]), Spacer(1, 0.3 * cm),
    ]
    por_albaran: dict[str, list] = {}
    for x in informe.entradas_mes:
        por_albaran.setdefault(x.num_albaran, []).append(x)
    resumen = {d["num_albaran"]: d for d in informe.detalle_albaranes}
    for numero_alb, items in sorted(por_albaran.items(), key=lambda p: (p[1][0].fecha, p[0])):
        d = resumen.get(numero_alb, {})
        limite = d.get("consumir_antes")
        cabecera = (f"<b>{items[0].fecha:%d/%m/%Y}</b> · Albarán {numero_alb} · "
                    f"{len(items)} líneas"
                    + (f" · consumir antes de {limite:%d/%m/%Y}" if limite else ""))
        filas = [["Código", "Descripción", "Cantidad", "Ud.", "Categoría"]]
        for x in items:
            filas.append([x.codigo, Paragraph(x.descripcion, estilos["leyenda"]),
                          numero(x.cantidad, 3 if x.unidad == "KG" else 0), x.unidad,
                          Paragraph(x.categoria, estilos["leyenda"])])
        tabla = Table(filas, repeatRows=1,
                      colWidths=[1.9 * cm, 7.6 * cm, 1.9 * cm, 1.1 * cm, 5.3 * cm])
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FB")]),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]))
        historia += [KeepTogether([Paragraph(cabecera, estilos["texto"]), Spacer(1, 0.1 * cm),
                                   tabla]), Spacer(1, 0.35 * cm)]
    if informe.incidencias:
        historia.append(Paragraph("Puntos a revisar", estilos["h2"]))
        historia += [Paragraph("• " + t, estilos["texto"]) for t in informe.incidencias]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    lienzo = type("Lienzo", (_LienzoNumerado,), {"titulo_pie": f"{CENTRO} · Anexo de {mes_nombre}"})
    SimpleDocTemplate(str(ruta), pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.6 * cm,
                      title=f"Anexo - {mes_nombre}", author=CENTRO).build(
        historia, canvasmaker=lienzo)
    return ruta


def ruta_semanal(base: Path, lunes: dt.date) -> Path:
    return base / str(lunes.year) / "semanales" / f"semana_{lunes:%Y-%m-%d}.pdf"


def escribir_pdf_semanal(informe: Informe, ruta: Path, inicio_registro: dt.date | None = None
                         ) -> Path:
    """Informe de una semana (1 hoja): lo recibido, lo tirado y el control de cada día."""
    estilos = _estilos()
    elaboracion = informe.fecha_elaboracion or dt.date.today()
    sin_reg = informe.sin_registro
    un = [x for x in informe.entradas_mes if x.unidad == "UN"]
    tirado = sum(s.unidades for s in informe.salidas_mes
                 if s.motivo == "caducado o desechado" and s.unidad == "UN")
    datos = [("Albaranes", informe.albaranes), ("Líneas de producto", informe.lineas),
             ("Unidades recibidas", sum(x.cantidad for x in un)),
             ("Controles hechos", "—" if sin_reg else f"{informe.controles_hechos}/{informe.dias}")]
    cifras = Table([[Paragraph(numero(v) if not isinstance(v, str) else v, estilos["cifra"])
                     for _, v in datos], [Paragraph(t, estilos["cifra_t"]) for t, _ in datos]],
                   colWidths=[4.4 * cm] * 4)
    cifras.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FONDO),
                                ("LINEAFTER", (0, 0), (-2, -1), 1, colors.white),
                                ("TOPPADDING", (0, 0), (-1, 0), 8),
                                ("BOTTOMPADDING", (0, 1), (-1, 1), 8)]))
    controles = {c.fecha: c for c in informe.controles_mes}
    filas = [["Día", "Albaranes", "Unidades", "Control de aptitud", "Tirado (uds)"]]
    for n in range(informe.dias):
        dia = informe.desde + dt.timedelta(days=n)
        albs = {x.num_albaran for x in informe.entradas_mes if x.fecha == dia}
        uds = sum(x.cantidad for x in un if x.fecha == dia)
        if sin_reg:
            control, tir = "sin registro", "—"
        else:
            c = controles.get(dia)
            control = "hecho" + (" · se tiró algo" if c and c.hubo_desecho else "") if c else (
                "sin control" if albs else "—")
            tir = numero(sum(s.unidades for s in informe.salidas_mes
                             if s.fecha == dia and s.motivo == "caducado o desechado"
                             and s.unidad == "UN"))
        filas.append([f"{DIAS_SEMANA[dia.weekday()]} {dia:%d/%m}", str(len(albs)) if albs else "—",
                      numero(uds) if uds else "—", control, tir])
    tabla = Table(filas, colWidths=[3.2 * cm, 2.6 * cm, 2.6 * cm, 5.8 * cm, 3.6 * cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (2, -1), "RIGHT"), ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FB")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    historia = [
        Paragraph("Registro semanal de donaciones de alimentos", estilos["titulo"]),
        Paragraph(f"{CENTRO} · Origen: {ORIGEN}", estilos["sub"]),
        Paragraph(f"<b>Semana del {informe.desde:%d/%m/%Y} al {informe.hasta:%d/%m/%Y}</b> · "
                  f"elaborado el {elaboracion:%d/%m/%Y}", estilos["sub"]),
        Spacer(1, 0.4 * cm), cifras, Spacer(1, 0.4 * cm),
        _bloque_grafico("¿Qué hemos recibido esta semana?",
                        "Unidades recibidas, por tipo de alimento.",
                        recibido_por_categoria(informe),
                        numero(sum(r[1] for r in recibido_por_categoria(informe))), estilos,
                        " uds", 17.8 * cm),
        Spacer(1, 0.3 * cm), Paragraph("Día a día", estilos["h2"]), tabla,
        Spacer(1, 0.3 * cm),
    ]
    if sin_reg:
        historia.append(Paragraph(
            "Semana anterior al inicio del registro diario"
            + (f" ({inicio_registro:%d/%m/%Y})" if inicio_registro else "")
            + ": solo se documenta lo recibido. No se estiman consumo ni alimentos tirados.",
            estilos["nota"]))
    elif tirado:
        historia.append(Paragraph(f"Unidades tiradas esta semana: <b>{numero(tirado)}</b>.",
                                  estilos["texto"]))
    if informe.comentarios:
        historia += [Paragraph("Observaciones", estilos["h2"]),
                     Paragraph(informe.comentarios.replace("\n", "<br/>"), estilos["texto"])]
    historia += [Spacer(1, 0.8 * cm),
                 Table([["Elaborado por: ____________________",
                         "Vº Bº Dirección: ____________________"]],
                       colWidths=[8.9 * cm, 8.9 * cm])]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    titulo = f"Semana {informe.desde:%d/%m/%Y}"
    lienzo = type("Lienzo", (_LienzoNumerado,), {"titulo_pie": f"{CENTRO} · {titulo}"})
    SimpleDocTemplate(str(ruta), pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.6 * cm, title=titulo,
                      author=CENTRO).build(historia, canvasmaker=lienzo)
    return ruta
