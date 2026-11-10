"""Informe mensual: balance global, consumo calculado e incidencias. Paso 8.

Modelo simplificado: todo lo que llega se da por consumido en la residencia salvo lo que se
anota como desechado y lo que queda almacenado (despensa y no comestibles, por recuento de fin
de mes). El consumo, por tanto, se CALCULA:

    consumido = al empezar el mes + recibido - desechado - otros - al cerrar el mes

Lo perecedero empieza y cierra el mes a 0 (se consume o se tira dentro del mes).
Todo son funciones puras, para poder probarlas con pytest sin base de datos.
"""

import calendar
import datetime as dt
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from trazabilidad.controles import ALMACENABLES, Control, clave_mes
from trazabilidad.saldos import VIDA_UTIL_POR_DEFECTO, Salida

PERSONAS_POR_DEFECTO = 50
DECIMALES = 3
TOLERANCIA = 0.0005


@dataclass(frozen=True)
class LineaEntrada:
    """Una línea de albarán tal como se guardó."""

    fecha: dt.date
    num_albaran: str
    codigo: str
    descripcion: str
    categoria: str
    cantidad: float
    unidad: str


@dataclass(frozen=True)
class FilaBalance:
    categoria: str
    unidad: str
    inicial: float
    entradas: float
    consumo: float  # calculado
    desechado: float
    otros: float
    final: float
    estimado: bool  # True si lo almacenado al cierre no se contó y se estimó
    diferencia: float  # 0 si todo cuadra; si no, el consumo negativo que no tiene sentido


@dataclass(frozen=True)
class FilaConsumo:
    categoria: str
    unidad: str
    total: float
    media_diaria: float
    por_persona_dia: float
    mes_anterior: float
    media_3_meses: float


@dataclass
class Informe:
    desde: dt.date
    hasta: dt.date
    personas: int
    dias: int
    balance: list[FilaBalance]
    consumo: list[FilaConsumo]
    albaranes: int
    lineas: int
    dias_sin_albaran: list[dt.date]
    controles_hechos: int
    dias_con_desecho: int
    dias_sin_control: list[dt.date]  # días con albarán y sin control de aptitud
    top_productos: list[dict]
    semanas: list[dict]
    detalle_albaranes: list[dict]
    incidencias: list[str]
    comentarios: str = ""
    entradas_mes: list[LineaEntrada] = field(default_factory=list)
    salidas_mes: list[Salida] = field(default_factory=list)
    controles_mes: list[Control] = field(default_factory=list)
    recap_kg: float | None = None  # total en kilos del albarán recapitulativo del donante
    recap_euros: float | None = None  # y su valor en euros
    fecha_elaboracion: dt.date | None = None  # fecha que figura como elaboración del informe
    sin_registro: bool = False  # mes anterior al inicio del registro diario: solo hay entradas
    albaranes_faltantes: list[str] = field(default_factory=list)  # en el recapitulativo, no aquí

    @property
    def cuadra(self) -> bool:
        return all(abs(f.diferencia) < TOLERANCIA for f in self.balance)


def limites_del_mes(anio: int, mes: int) -> tuple[dt.date, dt.date]:
    return dt.date(anio, mes, 1), dt.date(anio, mes, calendar.monthrange(anio, mes)[1])


def _redondear(valor: float) -> float:
    return round(valor + 0.0, DECIMALES)  # +0.0 evita el -0.0


def _mes_anterior(desde: dt.date) -> tuple[dt.date, dt.date]:
    fin = desde - dt.timedelta(days=1)
    return fin.replace(day=1), fin


def calcular_balance(
    lineas: list[LineaEntrada],
    salidas: list[Salida],
    desde: dt.date,
    hasta: dt.date,
    recuentos: dict[tuple[str, str, str], float] | None = None,
    inicio_registro: dt.date | None = None,
) -> list[FilaBalance]:
    """Balance del periodo por (categoría, unidad), con el consumo calculado."""
    recuentos = recuentos or {}
    mes, mes_previo = clave_mes(desde), clave_mes(_mes_anterior(desde)[0])
    recibido: dict[tuple[str, str], float] = defaultdict(float)
    antes: dict[tuple[str, str], float] = defaultdict(float)
    for x in lineas:
        if desde <= x.fecha <= hasta:
            recibido[(x.categoria, x.unidad)] += x.cantidad
        elif x.fecha < desde and (inicio_registro is None or x.fecha >= inicio_registro):
            antes[(x.categoria, x.unidad)] += x.cantidad
    quitado: dict[tuple[str, str, str], float] = defaultdict(float)  # (cat, unidad, tipo)
    for s in salidas:
        tipo = "consumo" if s.motivo == "consumo" else (
            "desechado" if s.motivo == "caducado o desechado" else "otros"
        )
        if desde <= s.fecha <= hasta:
            quitado[(s.categoria, s.unidad, tipo)] += s.unidades
        elif s.fecha < desde and (inicio_registro is None or s.fecha >= inicio_registro):
            antes[(s.categoria, s.unidad)] -= s.unidades

    claves = set(recibido) | {(c, u) for c, u, _ in quitado}
    claves |= {(c, u) for (m, c, u) in recuentos if m in (mes, mes_previo) and c in ALMACENABLES}
    balance = []
    for categoria, unidad in sorted(claves):
        almacenable = categoria in ALMACENABLES
        entradas = recibido.get((categoria, unidad), 0.0)
        desechado = quitado.get((categoria, unidad, "desechado"), 0.0)
        otros = quitado.get((categoria, unidad, "otros"), 0.0)
        anotado = quitado.get((categoria, unidad, "consumo"), 0.0)
        inicial = final = 0.0
        estimado = False
        if almacenable:
            previo = recuentos.get((mes_previo, categoria, unidad))
            inicial = previo if previo is not None else max(antes.get((categoria, unidad), 0.0), 0)
            contado = recuentos.get((mes, categoria, unidad))
            if contado is not None:
                final = contado
            else:  # sin recuento: se estima con el consumo anotado (si lo hubo)
                final = max(inicial + entradas - desechado - otros - anotado, 0.0)
                estimado = True
        consumo = inicial + entradas - desechado - otros - final
        diferencia = consumo if consumo < -TOLERANCIA else 0.0
        if any(abs(v) > TOLERANCIA for v in (inicial, entradas, desechado, otros, final)):
            balance.append(
                FilaBalance(
                    categoria, unidad, _redondear(inicial), _redondear(entradas),
                    _redondear(consumo),
                    _redondear(desechado), _redondear(otros), _redondear(final), estimado,
                    _redondear(diferencia),
                )
            )
    return balance


def _consumos(balance: list[FilaBalance]) -> dict[tuple[str, str], float]:
    return {(f.categoria, f.unidad): f.consumo for f in balance}


def calcular_informe(
    lineas: list[LineaEntrada],
    salidas: list[Salida],
    desde: dt.date,
    hasta: dt.date,
    personas: int = PERSONAS_POR_DEFECTO,
    vida_util: dict[str, int] | None = None,
    comentarios: str = "",
    controles: dict[dt.date, Control] | None = None,
    recuentos: dict[tuple[str, str, str], float] | None = None,
    recapitulativo: tuple[float | None, float | None] = (None, None),
    fecha_elaboracion: dt.date | None = None,
    inicio_registro: dt.date | None = None,
    albaranes_faltantes: list[str] | None = None,
) -> Informe:
    """Balance, consumo e incidencias del periodo [desde, hasta] (ambos incluidos)."""
    controles = controles or {}
    vida = VIDA_UTIL_POR_DEFECTO if vida_util is None else vida_util
    dias = (hasta - desde).days + 1
    entradas_mes = [x for x in lineas if desde <= x.fecha <= hasta]
    salidas_mes = [x for x in salidas if desde <= x.fecha <= hasta]

    sin_registro = inicio_registro is not None and hasta < inicio_registro

    def balance_de(d: dt.date, h: dt.date) -> list[FilaBalance]:
        if inicio_registro is not None and h < inicio_registro:
            return []  # antes del inicio no hay consumo registrado (no se inventa)
        return calcular_balance(lineas, salidas, d, h, recuentos, inicio_registro)

    balance = balance_de(desde, hasta)
    if sin_registro:  # solo lo recibido: sin consumo, tirado ni almacén
        recibido: dict[tuple[str, str], float] = defaultdict(float)
        for x in lineas:
            if desde <= x.fecha <= hasta:
                recibido[(x.categoria, x.unidad)] += x.cantidad
        balance = [
            FilaBalance(c, u, 0.0, _redondear(q), 0.0, 0.0, 0.0, 0.0, False, 0.0)
            for (c, u), q in sorted(recibido.items())
        ]

    # ----- consumo y comparación (calculado mes a mes con el mismo método) -----
    este = _consumos(balance)
    ant_desde, ant_hasta = _mes_anterior(desde)
    anterior = _consumos(balance_de(ant_desde, ant_hasta))
    previos: dict[tuple[str, str], float] = defaultdict(float)
    tres_desde = desde
    for _ in range(3):
        tres_desde, tres_hasta = _mes_anterior(tres_desde)
        for clave, valor in _consumos(
            balance_de(tres_desde, tres_hasta)
        ).items():
            previos[clave] += valor
    consumo = [
        FilaConsumo(
            c, u, _redondear(total), _redondear(total / dias),
            _redondear(total / dias / personas) if personas else 0.0,
            _redondear(anterior.get((c, u), 0.0)), _redondear(previos.get((c, u), 0.0) / 3),
        )
        for (c, u), total in sorted(este.items()) if total > TOLERANCIA
    ]

    # ----- albaranes, controles, productos y semanas -----
    dias_con_albaran = {x.fecha for x in entradas_mes}
    todos_los_dias = [desde + dt.timedelta(days=n) for n in range(dias)]
    dias_sin_albaran = [d for d in todos_los_dias if d not in dias_con_albaran]
    controles_mes = {d: c for d, c in controles.items() if desde <= d <= hasta}
    dias_sin_control = [
        d for d in todos_los_dias if d in dias_con_albaran and d not in controles_mes
    ]
    por_producto: dict[tuple, float] = defaultdict(float)
    nombres: dict[tuple, tuple[str, str]] = {}
    for x in entradas_mes:
        por_producto[(x.codigo, x.unidad)] += x.cantidad
        nombres[(x.codigo, x.unidad)] = (x.descripcion, x.categoria)
    top = [
        {"codigo": c, "descripcion": nombres[(c, u)][0], "categoria": nombres[(c, u)][1],
         "unidad": u, "cantidad": _redondear(q)}
        for (c, u), q in sorted(por_producto.items(), key=lambda p: -p[1])[:10]
    ]
    semanas = []
    for n in range((dias + 6) // 7):
        ini = desde + dt.timedelta(days=7 * n)
        fin = min(ini + dt.timedelta(days=6), hasta)
        semanas.append({
            "semana": f"{ini:%d/%m}–{fin:%d/%m}",
            "entradas": _redondear(sum(
                x.cantidad for x in entradas_mes if ini <= x.fecha <= fin and x.unidad == "UN"
            )),
            "desechado": _redondear(sum(
                s.unidades for s in salidas_mes
                if ini <= s.fecha <= fin and s.motivo == "caducado o desechado"
                and s.unidad == "UN"
            )),
        })
        semanas[-1]["consumo"] = _redondear(
            semanas[-1]["entradas"] - semanas[-1]["desechado"]
        )
    detalle = _detalle_albaranes(entradas_mes, vida)

    informe = Informe(
        desde=desde, hasta=hasta, personas=personas, dias=dias, balance=balance,
        consumo=consumo, albaranes=len({x.num_albaran for x in entradas_mes}),
        lineas=len(entradas_mes), dias_sin_albaran=dias_sin_albaran,
        controles_hechos=len(controles_mes),
        dias_con_desecho=sum(1 for c in controles_mes.values() if c.hubo_desecho),
        dias_sin_control=dias_sin_control, top_productos=top, semanas=semanas,
        detalle_albaranes=detalle, incidencias=[], comentarios=comentarios,
        entradas_mes=entradas_mes, salidas_mes=salidas_mes,
        controles_mes=sorted(controles_mes.values(), key=lambda c: c.fecha),
        recap_kg=recapitulativo[0], recap_euros=recapitulativo[1],
        fecha_elaboracion=fecha_elaboracion, sin_registro=sin_registro,
        albaranes_faltantes=albaranes_faltantes or [],
    )
    informe.incidencias = _incidencias(informe)
    return informe


def _detalle_albaranes(lineas: list[LineaEntrada], vida: dict[str, int]) -> list[dict]:
    """Por albarán: resumen y fecha aproximada para consumirlo (global, según lo que trae)."""
    por_albaran: dict[str, list[LineaEntrada]] = defaultdict(list)
    for x in lineas:
        por_albaran[x.num_albaran].append(x)
    filas = []
    for numero, items in sorted(por_albaran.items(), key=lambda p: (p[1][0].fecha, p[0])):
        fecha = items[0].fecha
        perecederas = {x.categoria for x in items if x.categoria not in ALMACENABLES}
        plazos = [vida[c] for c in perecederas if c in vida]
        limite = fecha + dt.timedelta(days=min(plazos)) if plazos else None
        filas.append({
            "fecha": fecha, "num_albaran": numero, "lineas": len(items),
            "unidades": _redondear(sum(x.cantidad for x in items if x.unidad == "UN")),
            "kilos": _redondear(sum(x.cantidad for x in items if x.unidad == "KG")),
            "categorias": ", ".join(sorted({x.categoria for x in items})),
            "consumir_antes": limite,
            "almacenable": any(x.categoria in ALMACENABLES for x in items),
        })
    return filas


def _incidencias(informe: Informe) -> list[str]:
    """Lo que conviene revisar o explicar antes de enseñar el informe."""
    texto = []
    for fila in informe.balance:
        if abs(fila.diferencia) >= TOLERANCIA:
            texto.append(
                f"No cuadra «{fila.categoria}» ({fila.unidad}): lo que queda almacenado "
                f"({fila.final:g}) es mayor que lo que había más lo recibido. Revisa el recuento."
            )
        if fila.estimado:
            texto.append(
                f"Falta el recuento de lo almacenado en «{fila.categoria}» ({fila.unidad}): "
                "se ha estimado. Haz el recuento de fin de mes para que sea exacto."
            )
    if informe.dias_sin_albaran:
        dias = ", ".join(f"{d:%d/%m}" for d in informe.dias_sin_albaran[:12])
        extra = "…" if len(informe.dias_sin_albaran) > 12 else ""
        texto.append(
            f"Días sin albarán: {len(informe.dias_sin_albaran)} de {informe.dias} ({dias}{extra})."
            " Comprueba que no falte ninguno por pasar."
        )
    if informe.dias_sin_control:
        texto.append(
            f"Días con albarán y sin control de aptitud: {len(informe.dias_sin_control)}. "
            "Cada día debería quedar anotado si se tiró algo o no."
        )
    for fila in informe.balance:
        if fila.desechado > 0 and fila.entradas > 0:
            porcentaje = 100 * fila.desechado / fila.entradas
            texto.append(
                f"Desechado en «{fila.categoria}»: {fila.desechado:g} {fila.unidad} "
                f"({porcentaje:.0f} % de lo recibido este mes)."
            )
    return texto


# ---------- con la base de datos ----------


def cargar_lineas(con: sqlite3.Connection) -> list[LineaEntrada]:
    filas = con.execute(
        "SELECT fecha, num_albaran, codigo, descripcion, categoria, cantidad, "
        "upper(trim(unidad)) FROM entradas ORDER BY fecha, id"
    )
    return [LineaEntrada(dt.date.fromisoformat(f[0]), *f[1:]) for f in filas]


def cargar_personas(con: sqlite3.Connection) -> int:
    fila = con.execute("SELECT valor FROM ajustes WHERE clave = 'personas'").fetchone()
    return int(fila[0]) if fila else PERSONAS_POR_DEFECTO


def guardar_personas(con: sqlite3.Connection, personas: int) -> None:
    if personas < 1:
        raise ValueError("Debe haber al menos 1 persona")
    with con:
        con.execute(
            "INSERT OR REPLACE INTO ajustes (clave, valor) VALUES ('personas', ?)",
            (str(int(personas)),),
        )


def cargar_recapitulativo(
    con: sqlite3.Connection, mes: dt.date
) -> tuple[float | None, float | None]:
    """Kilos y euros del albarán recapitulativo del donante para ese mes (o None)."""
    clave = clave_mes(mes)
    valores = dict(con.execute(
        "SELECT clave, valor FROM ajustes WHERE clave IN (?, ?)",
        (f"recap_kg_{clave}", f"recap_eur_{clave}"),
    ).fetchall())
    kg, euros = valores.get(f"recap_kg_{clave}"), valores.get(f"recap_eur_{clave}")
    return (float(kg) if kg is not None else None, float(euros) if euros is not None else None)


def guardar_recapitulativo(
    con: sqlite3.Connection, mes: dt.date, kg: float | None, euros: float | None
) -> None:
    """Guarda (o borra, si es None o 0) los totales del recapitulativo de ese mes."""
    clave = clave_mes(mes)
    with con:
        for nombre, valor in ((f"recap_kg_{clave}", kg), (f"recap_eur_{clave}", euros)):
            if valor:
                con.execute(
                    "INSERT OR REPLACE INTO ajustes (clave, valor) VALUES (?, ?)",
                    (nombre, str(float(valor))),
                )
            else:
                con.execute("DELETE FROM ajustes WHERE clave = ?", (nombre,))


def _digitos(numero: str) -> str:
    return "".join(c for c in numero if c.isdigit())


def comparar_albaranes(guardados: set[str], texto: str) -> tuple[list[str], list[str]]:
    """Compara los números del recapitulativo (texto pegado) con los guardados.

    Devuelve (faltan en el registro, están en el registro pero no en el recapitulativo).
    Un número de albarán son 17 cifras (centro de 4 + AAAAMMDD + 5); la «DON» da igual.
    """
    del_recap = set(re.findall(r"\d{17}", _digitos_de(texto)))
    propios = {_digitos(n) for n in guardados}
    return sorted(del_recap - propios), sorted(propios - del_recap)


def _digitos_de(texto: str) -> str:
    # separa por cualquier cosa que no sea cifra o letra para no pegar números contiguos
    return " ".join(re.sub(r"(?i)DON", "", t) for t in re.split(r"[\s,;]+", texto))


def cargar_inicio_registro(con: sqlite3.Connection) -> dt.date | None:
    fila = con.execute("SELECT valor FROM ajustes WHERE clave = 'inicio_registro'").fetchone()
    return dt.date.fromisoformat(fila[0]) if fila else None


def guardar_inicio_registro(con: sqlite3.Connection, fecha: dt.date | None) -> None:
    with con:
        if fecha is None:
            con.execute("DELETE FROM ajustes WHERE clave = 'inicio_registro'")
        else:
            con.execute(
                "INSERT OR REPLACE INTO ajustes (clave, valor) VALUES ('inicio_registro', ?)",
                (fecha.isoformat(),),
            )
