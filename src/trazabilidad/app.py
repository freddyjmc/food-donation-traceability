"""Pantalla de revisión (Streamlit): escanear -> comprobar -> guardar.

Ejecutar desde la carpeta del proyecto:   streamlit run src\\trazabilidad\\app.py
"""

import datetime as dt
import os
import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from trazabilidad.archivo import archivar_pdf
from trazabilidad.controles import (
    ALMACENABLES,
    cargar_controles,
    cargar_recuentos,
    guardar_control,
    guardar_recuento,
)
from trazabilidad.graficos import destino, recibido_por_categoria
from trazabilidad.informe_pdf import (
    escribir_anexo,
    escribir_pdf,
    escribir_pdf_semanal,
    ruta_anexo,
    ruta_pdf,
    ruta_semanal,
)
from trazabilidad.informes import (
    calcular_balance,
    calcular_informe,
    cargar_inicio_registro,
    cargar_lineas,
    cargar_personas,
    cargar_recapitulativo,
    comparar_albaranes,
    guardar_inicio_registro,
    guardar_personas,
    guardar_recapitulativo,
    limites_del_mes,
)
from trazabilidad.lectura import paginas_a_imagenes
from trazabilidad.limpiar import (
    BorradoNoPermitido,
    apartar_pdf,
    borrar_albaran,
    borrar_albaran_con_movimientos,
    borrar_control,
    copia_de_seguridad,
)
from trazabilidad.ocr import TesseractNoEncontrado
from trazabilidad.ocr import leer_albaran as ocr_albaran
from trazabilidad.parser import leer_albaran
from trazabilidad.productos import CambioNoPermitido, buscar_productos, cambiar_categoria
from trazabilidad.registro import (
    AlbaranInvalido,
    CodigosSinCategoria,
    abrir_base,
    guardar_albaran,
)
from trazabilidad.revision import (
    aplicar_categoria,
    categorias_disponibles,
    contar_lineas,
    mover_fila,
    preparar_revision,
    sin_categoria,
    validar_tabla,
)
from trazabilidad.saldos import (
    Salida,
    SalidaExcedeExistencias,
    asignar_fifo,
    avisos_antiguos,
    cargar_entradas,
    cargar_pospuestos,
    cargar_salidas,
    cargar_vida_util,
    existencias_a_fecha,
    guardar_vida_util,
    posponer,
    registrar_salida,
    registrar_salidas,
    resumen_existencias,
)
from trazabilidad.servidor import (
    cargar_carpeta,
    copia_diaria_pendiente,
    copiar_al_servidor,
    guardar_carpeta,
    marcar_copia_hecha,
)

DATOS = Path(os.environ.get("TRAZABILIDAD_DATOS", Path(__file__).resolve().parents[2] / "datos"))
ANCHO_VISTA = 900  # píxeles de las imágenes que se muestran (el OCR usa la resolución completa)


def vista_previa(imagen):
    proporcion = ANCHO_VISTA / imagen.width
    return imagen.resize((ANCHO_VISTA, int(imagen.height * proporcion)))


def leer_archivo_subido(archivo, con) -> dict:
    temporal = Path(tempfile.mkdtemp()) / f"subido{Path(archivo.name).suffix.lower()}"
    temporal.write_bytes(archivo.getvalue())
    imagenes = paginas_a_imagenes(temporal)
    albaran = leer_albaran(ocr_albaran(imagenes))
    tabla = preparar_revision(albaran, con)
    tabla.index = range(1, len(tabla) + 1)  # número de fila visible, para poder moverlas
    return {
        "temporal": str(temporal),
        "vistas": [vista_previa(i) for i in imagenes],
        "albaran": albaran,
        "tabla": tabla,
        "version": 0,
    }


def guardar(con, lectura, fecha, numero, tabla) -> str | None:
    """Guarda el albarán y archiva su PDF. Devuelve el mensaje de éxito, o None si hubo errores."""
    lineas, categorias, errores = validar_tabla(tabla)
    if errores:
        for error in errores:
            st.error(error)
        return None
    try:
        destino = archivar_pdf(lectura["temporal"], DATOS / "pdf_archivo", fecha, numero)
        try:
            guardar_albaran(
                con, fecha, numero, lineas,
                enlace_pdf=destino.relative_to(DATOS).as_posix(),
                categorias_elegidas=categorias,
            )
        except Exception:
            destino.unlink(missing_ok=True)  # si no se pudo guardar, no dejamos el PDF suelto
            raise
    except (AlbaranInvalido, CodigosSinCategoria, FileExistsError) as error:
        st.error(str(error))
        return None
    return f"Guardadas {len(lineas)} líneas del albarán {numero}. PDF archivado en {destino.name}."


st.set_page_config(
    page_title="Registro de donaciones", layout="wide", initial_sidebar_state="collapsed"
)
st.title("Registro de trazabilidad de donaciones")
DATOS.mkdir(parents=True, exist_ok=True)
con = abrir_base(DATOS / "registro.db")

with st.sidebar:
    st.subheader("Copia en el servidor")
    ruta_servidor = st.text_input(
        "Carpeta del servidor", value=cargar_carpeta(con),
        placeholder=r"\\servidor\carpeta\Registro",
        help="Aquí se guardan, ordenados, los informes, los PDF de albaranes y una copia diaria "
             "de la base de datos.",
    )
    if ruta_servidor.strip() != cargar_carpeta(con):
        guardar_carpeta(con, ruta_servidor)
    hacer_copia = st.button("Copiar ahora", disabled=not ruta_servidor.strip())
    if ruta_servidor.strip() and (hacer_copia or copia_diaria_pendiente(con)):
        try:
            with st.spinner("Copiando al servidor..."):
                mensaje_copia = copiar_al_servidor(con, DATOS, Path(ruta_servidor.strip()))
            marcar_copia_hecha(con)
            st.success(mensaje_copia)
        except (OSError, ValueError) as error:
            st.error(f"No se pudo copiar al servidor ({error}). Comprueba que la unidad esté "
                     "conectada y la ruta sea correcta.")
    elif not ruta_servidor.strip():
        st.caption("Sin carpeta elegida: no se hace copia en el servidor.")

pestana_revisar, pestana_control, pestana_informes, pestana_mas = st.tabs(
    ["Subir albarán", "Control del día", "Informes", "Más opciones"]
)
with pestana_mas:
    st.caption("Opciones avanzadas: no hace falta usarlas a diario.")
    pestana_existencias, pestana_consumo, pestana_registro, pestana_productos = st.tabs(
        ["Existencias y avisos", "Anotar consumo (detalle)", "Entradas guardadas", "Productos"]
    )

with pestana_revisar:
    if mensaje := st.session_state.pop("mensaje", None):
        st.success(mensaje)

    archivo = st.file_uploader(
        "Sube el albarán (PDF o foto)", type=["pdf", "png", "jpg", "jpeg"],
        key=f"subida_{st.session_state.get('n_subida', 0)}",
    )
    if archivo and st.button("Leer albarán", type="primary"):
        try:
            with st.spinner("Leyendo el albarán..."):
                st.session_state["lectura"] = leer_archivo_subido(archivo, con)
        except TesseractNoEncontrado as error:
            st.error(str(error))

    lectura = st.session_state.get("lectura")
    if lectura:
        albaran = lectura["albaran"]
        izquierda, derecha = st.columns([2, 5])
        with izquierda:
            for numero_pagina, vista in enumerate(lectura["vistas"], start=1):
                st.image(vista, caption=f"Página {numero_pagina}")
        with derecha:
            for aviso in albaran.avisos:
                st.warning(aviso)
            columna_fecha, columna_numero = st.columns(2)
            fecha = columna_fecha.date_input(
                "Fecha del albarán", value=albaran.fecha or dt.date.today(), format="DD/MM/YYYY"
            )
            numero = columna_numero.text_input("Nº de albarán", value=albaran.num_albaran or "")
            if con.execute(
                "SELECT 1 FROM entradas WHERE num_albaran = ? LIMIT 1", (numero.strip(),)
            ).fetchone():
                st.warning(
                    "Este albarán YA está guardado, así que no se puede guardar otra vez. Para "
                    "cambiar la categoría de un producto usa la pestaña «Productos»."
                )
            st.caption(
                "Corrige lo que el OCR haya leído mal. «OK»: ya conocido, no hace falta mirarla. "
                "«Sugerida»: categoría puesta por la app, confírmala o cámbiala. «Nuevo»: "
                "elige tú la categoría. «Revisar»: lee la nota."
            )
            conteo = lectura["tabla"]["Estado"].value_counts()
            st.markdown(
                f"✅ **{conteo.get('OK', 0)}** conocidas · 🟡 **{conteo.get('Sugerida', 0)}** "
                f"sugeridas (confírmalas) · 🔴 **{conteo.get('Nuevo', 0)}** sin categoría · "
                f"🔴 **{conteo.get('Revisar', 0)}** a revisar"
            )
            tabla = st.data_editor(
                lectura["tabla"],
                num_rows="dynamic",
                hide_index=False,
                key=f"editor_{lectura['version']}",
                column_config={
                    "Estado": st.column_config.TextColumn(disabled=True, width="small"),
                    "Código": st.column_config.TextColumn(width="small"),
                    "Descripción": st.column_config.TextColumn(width="medium"),
                    "Cantidad": st.column_config.NumberColumn(min_value=0, width="small"),
                    "Unidad": st.column_config.TextColumn(width="small"),
                    "Categoría": st.column_config.SelectboxColumn(
                        options=categorias_disponibles(con), width="medium"
                    ),
                    "Nota": st.column_config.TextColumn(disabled=True, width="large"),
                },
            )
            tabla = pd.DataFrame(tabla)
            if len(tabla) > 1:
                st.caption("Para cambiar el orden de las líneas: indica qué fila mover y dónde.")
                c1, c2, c3 = st.columns([2, 2, 2], vertical_alignment="bottom")
                origen = c1.number_input("Mover la fila nº", 1, len(tabla), value=1, step=1)
                destino_fila = c2.number_input("a la posición nº", 1, len(tabla), value=1, step=1)
                if c3.button("Mover fila") and origen != destino_fila:
                    lectura["tabla"] = mover_fila(tabla, int(origen), int(destino_fila))
                    lectura["version"] += 1
                    st.rerun()
            if sin_categoria(tabla).any():
                columna_categoria, columna_boton = st.columns([3, 1], vertical_alignment="bottom")
                elegida = columna_categoria.selectbox(
                    "Poner la misma categoría a todas las filas que no la tienen",
                    categorias_disponibles(con),
                    index=None,
                    placeholder="Elige una categoría",
                )
                if columna_boton.button("Aplicar") and elegida:
                    lectura["tabla"] = aplicar_categoria(tabla, elegida)
                    lectura["version"] += 1  # reinicia la tabla con los cambios
                    st.rerun()
            filas = contar_lineas(tabla)
            st.info(
                f"**{filas} líneas con código en la tabla.** Cuenta las líneas del albarán en "
                "papel: si no coinciden, falta alguna por añadir (botón + al final de la tabla)."
            )
            if st.button("Guardar albarán", type="primary"):
                resultado = guardar(con, lectura, fecha, numero.strip(), tabla)
                if resultado:
                    st.session_state.pop("lectura", None)
                    st.session_state["n_subida"] = st.session_state.get("n_subida", 0) + 1
                    st.session_state["mensaje"] = resultado
                    st.rerun()

with pestana_control:
    if mensaje := st.session_state.pop("mensaje_control", None):
        st.success(mensaje)
    st.caption(
        "Cuando la cocina tenga la comida organizada, responde una sola pregunta: "
        "¿se ha tirado algo hoy? Queda guardado con la fecha y quién lo comprobó."
    )
    dia_c = st.date_input("Día", value=dt.date.today(), format="DD/MM/YYYY", key="dia_control")
    previo_c = cargar_controles(con).get(dia_c)
    if previo_c:
        st.info(
            f"Este día ya tiene control ({'se tiró algo' if previo_c.hubo_desecho else 'todo apto'}"
            f"{', ' + previo_c.responsable if previo_c.responsable else ''}). "
            "Puedes añadir más desechos o cambiar la nota."
        )
    ultimo = con.execute(
        "SELECT responsable FROM controles WHERE responsable <> '' ORDER BY fecha DESC LIMIT 1"
    ).fetchone()
    responsable = st.text_input("Quién lo ha comprobado", value=ultimo[0] if ultimo else "")
    respuesta = st.radio(
        "¿Se ha tirado algo hoy?", ["No, todo apto", "Sí, se ha tirado algo"], horizontal=True
    )
    desechos_tabla = None
    if respuesta.startswith("Sí"):
        st.caption("Añade una fila por cada categoría (botón + al final) con lo que se tiró.")
        desechos_tabla = st.data_editor(
            pd.DataFrame({"Categoría": pd.Series(dtype=str), "Unidad": pd.Series(dtype=str),
                          "Cantidad": pd.Series(dtype=float)}),
            num_rows="dynamic",
            hide_index=True,
            key=f"desechos_{dia_c}",
            column_config={
                "Categoría": st.column_config.SelectboxColumn(
                    options=categorias_disponibles(con), required=True
                ),
                "Unidad": st.column_config.SelectboxColumn(options=["UN", "KG"], default="UN"),
                "Cantidad": st.column_config.NumberColumn(min_value=0, step=0.001, format="%g"),
            },
        )
    nota_c = st.text_input("Nota (opcional)", placeholder="Ej.: fruta con golpes, pan duro")
    if st.button("Guardar control del día", type="primary"):
        desechos = []
        if desechos_tabla is not None:
            for fila in pd.DataFrame(desechos_tabla).to_dict("records"):
                cantidad = fila.get("Cantidad")
                if fila.get("Categoría") and cantidad and cantidad > 0:
                    desechos.append(
                        Salida(dia_c, fila["Categoría"], float(cantidad), "caducado o desechado",
                               unidad=fila.get("Unidad") or "UN")
                    )
            if not desechos:
                st.warning("Has marcado que se tiró algo, pero no has puesto categoría y cantidad.")
        if desechos_tabla is None or desechos:
            try:
                guardar_control(con, dia_c, desechos, responsable, nota_c)
            except SalidaExcedeExistencias as error:
                st.error(str(error))
            else:
                st.session_state["mensaje_control"] = (
                    f"Control del {dia_c:%d/%m/%Y} guardado."
                )
                st.rerun()
    ultimos = pd.DataFrame(
        [{"Fecha": c.fecha, "¿Se tiró algo?": "Sí" if c.hubo_desecho else "No",
          "Comprobó": c.responsable, "Nota": c.nota}
         for c in sorted(cargar_controles(con).values(), key=lambda c: c.fecha, reverse=True)[:30]]
    )
    if len(ultimos):
        st.subheader("Últimos controles")
        st.dataframe(ultimos, hide_index=True)
        with st.expander("Borrar un control equivocado"):
            st.caption(
                "Borra el control de ese día y los desechos anotados ese día. "
                "Después puedes volver a hacerlo bien."
            )
            dia_b = st.selectbox(
                "Día", list(ultimos["Fecha"]), format_func=lambda d: f"{d:%d/%m/%Y}"
            )
            seguro_c = st.checkbox("Quiero borrar este control", key="seguro_control")
            if st.button("Borrar control", disabled=not seguro_c):
                copia_de_seguridad(DATOS / "registro.db")
                borrados = borrar_control(con, dia_b)
                st.session_state["mensaje_control"] = (
                    f"Control del {dia_b:%d/%m/%Y} borrado ({borrados} desechos)."
                )
                st.rerun()

with pestana_consumo:
    if mensaje := st.session_state.pop("mensaje_consumo", None):
        st.success(mensaje)
    st.caption(
        "Anota lo que ha usado cocina cada día, por categoría, y lo que se ha tirado. "
        "Puedes elegir un día anterior para ponerte al día."
    )
    dia = st.date_input("Día", value=dt.date.today(), format="DD/MM/YYYY", key="dia_consumo")
    entradas_todas, salidas_todas = cargar_entradas(con), cargar_salidas(con)
    disponible = existencias_a_fecha(entradas_todas, salidas_todas, dia)
    # Una fila por categoría en UN, más una fila por cada categoría que también tenga KG.
    bolsas = {(c, "UN") for c in categorias_disponibles(con)}
    bolsas |= {(e.categoria, e.unidad) for e in entradas_todas}
    bolsas = sorted(bolsas, key=lambda b: (categorias_disponibles(con).index(b[0]), b[1]))
    tabla_consumo = pd.DataFrame(
        {
            "Categoría": [b[0] for b in bolsas],
            "Unidad": [b[1] for b in bolsas],
            "Disponible ese día": [disponible.get(b, 0.0) for b in bolsas],
            "Consumido": 0.0,
            "Tirado": 0.0,
        }
    )
    editada = st.data_editor(
        tabla_consumo,
        hide_index=True,
        num_rows="fixed",
        key=f"consumo_{dia}_{len(salidas_todas)}",
        column_config={
            "Categoría": st.column_config.TextColumn(disabled=True),
            "Unidad": st.column_config.TextColumn(disabled=True, width="small"),
            "Disponible ese día": st.column_config.NumberColumn(disabled=True),
            "Consumido": st.column_config.NumberColumn(min_value=0, step=0.001, format="%g"),
            "Tirado": st.column_config.NumberColumn(
                min_value=0, step=0.001, format="%g", help="Caducado, en mal estado o desechado"
            ),
        },
    )
    if st.button("Guardar consumo del día", type="primary"):
        nuevas = []
        for fila in editada.to_dict("records"):
            if fila["Consumido"] and fila["Consumido"] > 0:
                nuevas.append(
                    Salida(dia, fila["Categoría"], float(fila["Consumido"]), "consumo",
                           unidad=fila["Unidad"])
                )
            if fila["Tirado"] and fila["Tirado"] > 0:
                nuevas.append(
                    Salida(dia, fila["Categoría"], float(fila["Tirado"]),
                           "caducado o desechado", unidad=fila["Unidad"])
                )
        if not nuevas:
            st.warning("No has anotado ninguna cantidad.")
        else:
            try:
                registrar_salidas(con, nuevas)
            except SalidaExcedeExistencias as error:
                st.error(str(error))
            else:
                st.session_state["mensaje_consumo"] = (
                    f"Guardadas {len(nuevas)} salidas del {dia:%d/%m/%Y}."
                )
                st.rerun()

    st.subheader("Últimas salidas")
    ultimas = pd.read_sql_query(
        "SELECT fecha, categoria, unidades, unidad, motivo FROM salidas"
        " ORDER BY fecha DESC, id DESC LIMIT 60",
        con,
    )
    st.dataframe(ultimas, hide_index=True)

with pestana_existencias:
    hoy = dt.date.today()
    entradas_todas, salidas_todas = cargar_entradas(con), cargar_salidas(con)
    reparto = asignar_fifo(entradas_todas, salidas_todas)
    st.subheader("Existencias ahora mismo")
    resumen = resumen_existencias(entradas_todas, reparto, hoy)
    if resumen:
        st.dataframe(
            pd.DataFrame(resumen).rename(
                columns={
                    "categoria": "Categoría",
                    "unidades": "Cantidad",
                    "unidad": "Unidad",
                    "albaran": "Albarán más antiguo con unidades",
                    "fecha": "Del día",
                    "dias": "Días",
                }
            ),
            hide_index=True,
        )
    else:
        st.info("No hay existencias: todavía no se han guardado albaranes.")

    st.subheader("Avisos")
    avisos = avisos_antiguos(
        entradas_todas, reparto, hoy, cargar_vida_util(con), cargar_pospuestos(con)
    )
    # Solo se resuelve el más antiguo de cada categoría: el reparto empieza siempre por él.
    primeros = list({(a.categoria, a.unidad): a for a in reversed(avisos)}.values())
    if mensaje := st.session_state.pop("mensaje_aviso", None):
        st.success(mensaje)
    if not primeros:
        st.success("No hay avisos: nada lleva más días de los esperados.")
    for aviso in sorted(primeros, key=lambda a: -a.dias):
        with st.container(border=True):
            st.markdown(
                f"**{aviso.categoria}**: quedan **{aviso.unidades:g} {aviso.unidad}** del albarán "
                f"{aviso.num_albaran} (llegó el {aviso.fecha_entrada:%d/%m/%Y}, hace "
                f"{aviso.dias} días; se espera usarlo en {aviso.limite})."
            )
            consumido, tirado, sigue = st.columns(3)
            clave = f"{aviso.num_albaran}_{aviso.categoria}_{aviso.unidad}"
            if consumido.button("Ya se consumió", key=f"c_{clave}"):
                registrar_salida(
                    con, hoy, aviso.categoria, aviso.unidades, "consumo", aviso.unidad
                )
                st.session_state["mensaje_aviso"] = "Anotado como consumido."
                st.rerun()
            if tirado.button("Se tiró", key=f"t_{clave}"):
                registrar_salida(
                    con, hoy, aviso.categoria, aviso.unidades, "caducado o desechado",
                    aviso.unidad,
                )
                st.session_state["mensaje_aviso"] = "Anotado como caducado o desechado."
                st.rerun()
            dias_mas = sigue.number_input(
                "Sigue bien: avisar en (días)", min_value=1, value=7, key=f"d_{clave}"
            )
            if sigue.button("Sigue en buen estado", key=f"s_{clave}"):
                posponer(con, aviso.num_albaran, aviso.categoria, hoy + dt.timedelta(days=dias_mas))
                st.session_state["mensaje_aviso"] = f"No se avisará de nuevo en {dias_mas} días."
                st.rerun()

    with st.expander("Días de aviso por categoría"):
        st.caption("Pasados estos días con unidades en existencias, salta un aviso.")
        vida = cargar_vida_util(con)
        editada_vida = st.data_editor(
            pd.DataFrame({"Categoría": list(vida), "Días": list(vida.values())}),
            hide_index=True,
            num_rows="fixed",
            key="vida_util",
            column_config={
                "Categoría": st.column_config.TextColumn(disabled=True),
                "Días": st.column_config.NumberColumn(min_value=1, step=1),
            },
        )
        if st.button("Guardar días de aviso"):
            pares = zip(editada_vida["Categoría"], editada_vida["Días"], strict=True)
            guardar_vida_util(con, dict(pares))
            st.success("Guardado.")

with pestana_registro:
    if mensaje := st.session_state.pop("mensaje_borrado", None):
        st.success(mensaje)
    with st.expander("Corregir o borrar un albarán"):
        st.caption(
            "Si te equivocaste en un albarán, bórralo y vuelve a subirlo bien. Antes de borrar "
            "se guarda una copia de seguridad y el PDF se aparta, no se destruye."
        )
        lista = con.execute(
            "SELECT num_albaran, MIN(fecha), COUNT(*) FROM entradas GROUP BY num_albaran "
            "ORDER BY MIN(fecha) DESC, num_albaran DESC"
        ).fetchall()
        if not lista:
            st.info("Todavía no hay albaranes guardados.")
        else:
            elegido = st.selectbox(
                "Albarán", [f[0] for f in lista],
                format_func=lambda n: next(
                    f"{dt.date.fromisoformat(f[1]):%d/%m/%Y} · {f[0]} ({f[2]} líneas)"
                    for f in lista if f[0] == n
                ),
            )
            st.dataframe(
                pd.read_sql_query(
                    "SELECT codigo, descripcion, categoria, cantidad, unidad FROM entradas "
                    "WHERE num_albaran = ?", con, params=(elegido,),
                ),
                hide_index=True,
            )
            seguro = st.checkbox("Quiero borrar este albarán completo", key="seguro_borrar")
            if st.button("Borrar albarán", disabled=not seguro):
                try:
                    copia_de_seguridad(DATOS / "registro.db")
                    borradas, pdf = borrar_albaran(con, elegido)
                except BorradoNoPermitido as error:
                    st.session_state["forzar_albaran"] = elegido
                    st.error(str(error))
                else:
                    apartar_pdf(DATOS, pdf)
                    st.session_state["mensaje_borrado"] = (
                        f"Albarán {elegido} borrado ({borradas} líneas). Ya puedes volver a "
                        "subirlo corregido."
                    )
                    st.rerun()
            if st.session_state.get("forzar_albaran") == elegido:
                st.warning(
                    "Este albarán no se puede borrar solo porque hay desechos o consumos anotados "
                    "que dependen de él (por ejemplo, de pruebas). Si son de prueba, puedes borrar "
                    "el albarán Y esos movimientos."
                )
                seguro_todo = st.checkbox(
                    "Borrar también esos desechos y consumos", key="seguro_forzar"
                )
                if st.button("Borrar albarán y sus movimientos", disabled=not seguro_todo):
                    copia_de_seguridad(DATOS / "registro.db")
                    borradas, pdf, salidas_b = borrar_albaran_con_movimientos(con, elegido)
                    apartar_pdf(DATOS, pdf)
                    st.session_state.pop("forzar_albaran", None)
                    st.session_state["mensaje_borrado"] = (
                        f"Albarán {elegido} borrado ({borradas} líneas y {salidas_b} movimientos)."
                    )
                    st.rerun()
    entradas = pd.read_sql_query(
        "SELECT fecha, num_albaran, codigo, descripcion, categoria, cantidad, unidad, enlace_pdf"
        " FROM entradas ORDER BY fecha DESC, id DESC LIMIT 1000",
        con,
    )
    st.caption(f"{len(entradas)} líneas (se muestran las últimas 1000)")
    st.dataframe(entradas, hide_index=True)

with pestana_productos:
    if mensaje := st.session_state.pop("mensaje_productos", None):
        st.success(mensaje)
    st.caption(
        "Corrige la categoría de un producto ya guardado. El cambio afecta al catálogo y a "
        "todas sus entradas anteriores. Busca por código o por nombre."
    )
    busqueda = st.text_input("Buscar producto", placeholder="Ej.: GOURMET o 69741")
    encontrados = buscar_productos(con, busqueda)
    if not encontrados:
        st.info("No hay productos con ese texto.")
    else:
        original = pd.DataFrame(encontrados).rename(
            columns={"codigo": "Código", "descripcion": "Descripción", "categoria": "Categoría",
                     "entradas": "Entradas"}
        )
        editado = st.data_editor(
            original,
            hide_index=True,
            num_rows="fixed",
            key=f"productos_{busqueda}",
            column_config={
                "Código": st.column_config.TextColumn(disabled=True),
                "Descripción": st.column_config.TextColumn(disabled=True),
                "Entradas": st.column_config.NumberColumn(disabled=True),
                "Categoría": st.column_config.SelectboxColumn(options=categorias_disponibles(con)),
            },
        )
        if st.button("Guardar cambios de categoría"):
            cambios = editado[editado["Categoría"] != original["Categoría"]]
            try:
                for _, fila in cambios.iterrows():
                    cambiar_categoria(con, fila["Código"], fila["Categoría"])
            except CambioNoPermitido as error:
                st.error(str(error))
            else:
                st.session_state["mensaje_productos"] = f"{len(cambios)} producto(s) cambiados."
                st.rerun()

def anillo(rebanadas, alto: int = 260):
    """Gráfico de círculo con leyenda (Altair, ya viene con Streamlit)."""
    if not rebanadas:
        st.info("Sin datos este mes.")
        return
    datos = pd.DataFrame(rebanadas, columns=["Concepto", "Cantidad", "Color"])
    st.altair_chart(
        alt.Chart(datos).mark_arc(innerRadius=60).encode(
            theta=alt.Theta("Cantidad:Q"),
            color=alt.Color(
                "Concepto:N",
                scale=alt.Scale(domain=list(datos["Concepto"]), range=list(datos["Color"])),
                legend=alt.Legend(title=None, orient="bottom", columns=1),
            ),
            tooltip=["Concepto", "Cantidad"],
        ).properties(height=alto),
        width="stretch",
    )


with pestana_informes:
    pestana_mensual, pestana_semanal = st.tabs(
        ["Informe del mes", "Informe de la semana"]
    )
    with pestana_mensual:
        st.caption("Al terminar el mes, crea aquí el informe: PDF de 2 hojas para imprimir.")
        hoy_i = dt.date.today()
        anterior = (hoy_i.replace(day=1) - dt.timedelta(days=1))
        ultimo_albaran = con.execute("SELECT MAX(fecha) FROM entradas").fetchone()[0]
        hay_en_anterior = con.execute(
            "SELECT 1 FROM entradas WHERE fecha BETWEEN ? AND ? LIMIT 1",
            (anterior.replace(day=1).isoformat(), anterior.isoformat()),
        ).fetchone()
        if ultimo_albaran and not hay_en_anterior:
            anterior = dt.date.fromisoformat(ultimo_albaran)  # el último mes con datos
        columna_anio, columna_mes = st.columns(2)
        anio = columna_anio.number_input("Año", 2020, 2100, value=anterior.year, step=1)
        mes = columna_mes.selectbox(
            "Mes", list(range(1, 13)), index=anterior.month - 1,
            format_func=lambda m: ("enero febrero marzo abril mayo junio julio agosto septiembre "
                                   "octubre noviembre diciembre").split()[m - 1].capitalize(),
        )
        desde, hasta = limites_del_mes(int(anio), int(mes))
        lineas_i, salidas_i = cargar_lineas(con), cargar_salidas(con)

        st.markdown("**Datos del albarán recapitulativo del donante** (opcional)")
        guardado_kg, guardado_eur = cargar_recapitulativo(con, desde)
        col_kg, col_eur = st.columns(2)
        recap_kg = col_kg.number_input(
            "Kilos totales", min_value=0.0, value=guardado_kg or 0.0, step=0.01, format="%.2f",
            key=f"recap_kg_{anio}_{mes}",
        )
        recap_eur = col_eur.number_input(
            "Valor en euros", min_value=0.0, value=guardado_eur or 0.0, step=0.01, format="%.2f",
            key=f"recap_eur_{anio}_{mes}",
        )

        recap_pdf = st.file_uploader(
            "Guardar el PDF del recapitulativo del donante en la carpeta del mes (opcional)",
            type=["pdf", "png", "jpg", "jpeg"], key=f"recap_pdf_{anio}_{mes}",
        )
        st.markdown("**Albaranes del recapitulativo** (opcional)")
        pegado = st.text_area(
            "Pega aquí los números de albarán que figuran en el recapitulativo",
            height=80, key=f"recap_lista_{anio}_{mes}",
            help="Así la app te dice cuáles faltan en tu registro.",
        )
        propios = {x.num_albaran for x in lineas_i if desde <= x.fecha <= hasta}
        faltan, sobran = comparar_albaranes(propios, pegado) if pegado.strip() else ([], [])
        if pegado.strip():
            if faltan:
                st.error(f"Faltan {len(faltan)} albarán(es) en tu registro: " + ", ".join(faltan))
            else:
                st.success("Todos los albaranes del recapitulativo están en tu registro.")
            if sobran:
                st.warning("Tienes guardados y no salen en el recapitulativo: " + ", ".join(sobran))

        inicio = cargar_inicio_registro(con)
        almacenado = [
            f for f in calcular_balance(lineas_i, salidas_i, desde, hasta, cargar_recuentos(con),
                                        inicio)
            if f.categoria in ALMACENABLES
        ]
        tabla_recuento = None
        contado = False
        if almacenado:
            st.markdown("**Lo que queda guardado en el almacén** (despensa y no comestibles)")
            st.caption(
                "Cuenta lo que queda al cerrar el mes y corrige la última columna. Hasta que lo "
                "hagas, el informe usa una estimación y lo avisa."
            )
            tabla_recuento = st.data_editor(
                pd.DataFrame({
                    "Categoría": [f.categoria for f in almacenado],
                    "Unidad": [f.unidad for f in almacenado],
                    "Al empezar el mes": [f.inicial for f in almacenado],
                    "Recibido": [f.entradas for f in almacenado],
                    "Queda almacenado": [f.final for f in almacenado],
                }),
                hide_index=True, num_rows="fixed", key=f"recuento_{anio}_{mes}",
                column_config={
                    "Categoría": st.column_config.TextColumn(disabled=True),
                    "Unidad": st.column_config.TextColumn(disabled=True, width="small"),
                    "Al empezar el mes": st.column_config.NumberColumn(disabled=True),
                    "Recibido": st.column_config.NumberColumn(disabled=True),
                    "Queda almacenado": st.column_config.NumberColumn(min_value=0, step=0.001,
                                                                       format="%g"),
                },
            )
            contado = st.checkbox("He contado lo almacenado y las cifras son correctas")
        comentarios = st.text_area(
            "Observaciones del mes (salen en el informe)", height=110,
            placeholder="Ej.: En enero no se registraba lo tirado. Semana sin albaranes.",
        )
        fecha_informe = st.date_input("Fecha de elaboración del informe", value=hoy_i,
                                      format="DD/MM/YYYY")
        with st.expander("Ajustes"):
            usar_inicio = st.checkbox(
                "El registro diario empieza en una fecha concreta (los meses anteriores solo "
                "documentan lo recibido)", value=inicio is not None,
            )
            nuevo_inicio = st.date_input(
                "Primer día del registro diario", value=inicio or dt.date(2026, 11, 1),
                format="DD/MM/YYYY", disabled=not usar_inicio,
            )
            personas = st.number_input(
                "Personas atendidas en el centro", 1, 1000,
                value=cargar_personas(con), step=1,
            )

        if st.button("Crear informe", type="primary"):
            guardar_personas(con, int(personas))
            inicio = nuevo_inicio if usar_inicio else None
            guardar_inicio_registro(con, inicio)
            guardar_recapitulativo(con, desde, recap_kg or None, recap_eur or None)
            if contado and tabla_recuento is not None:
                for fila in pd.DataFrame(tabla_recuento).to_dict("records"):
                    guardar_recuento(con, desde, fila["Categoría"], fila["Unidad"],
                                     float(fila["Queda almacenado"]))
            informe = calcular_informe(
                lineas_i, salidas_i, desde, hasta, int(personas), cargar_vida_util(con),
                comentarios.strip(), cargar_controles(con), cargar_recuentos(con),
                (recap_kg or None, recap_eur or None), fecha_informe, inicio, faltan,
            )
            carpeta = DATOS / "informes"
            ruta_x = escribir_anexo(informe, ruta_anexo(carpeta, int(anio), int(mes)))
            ruta_p = escribir_pdf(informe, ruta_pdf(carpeta, int(anio), int(mes)), inicio)
            if recap_pdf is not None:
                sufijo = Path(recap_pdf.name).suffix.lower()
                (ruta_p.parent / f"recapitulativo_{int(anio)}-{int(mes):02d}{sufijo}").write_bytes(
                    recap_pdf.getvalue())
            st.session_state["informe"] = (informe, ruta_x, ruta_p)
            if cargar_carpeta(con):
                try:
                    copiar_al_servidor(con, DATOS, Path(cargar_carpeta(con)))
                    st.success("Informe copiado también al servidor.")
                except (OSError, ValueError) as error:
                    st.warning(f"El informe se creó, pero no se pudo copiar al servidor: {error}")

        if "informe" in st.session_state:
            informe, ruta_x, ruta_p = st.session_state["informe"]
            st.divider()
            if informe.albaranes == 0:
                ultimo = con.execute("SELECT MAX(fecha) FROM entradas").fetchone()[0]
                st.warning(
                    "Este mes no tiene ningún albarán guardado, por eso las cifras salen a cero. "
                    + (f"El último albarán es del {dt.date.fromisoformat(ultimo):%d/%m/%Y}: "
                       "elige ese mes y año arriba." if ultimo else "Todavía no hay albaranes.")
                )
            st.download_button(
                "Descargar el informe en PDF (2 hojas)", ruta_p.read_bytes(),
                file_name=ruta_p.name, mime="application/pdf", type="primary",
            )
            a, b, c, d = st.columns(4)
            un = [f for f in informe.balance if f.unidad == "UN"]
            a.metric("Albaranes", informe.albaranes)
            b.metric("Unidades recibidas", f"{sum(f.entradas for f in un):g}")
            if informe.sin_registro:
                c.metric("Consumo y lo tirado", "Sin registro")
                d.metric("Líneas recibidas", informe.lineas)
            else:
                c.metric("Unidades consumidas", f"{sum(f.consumo for f in un):g}")
                d.metric("Controles diarios", f"{informe.controles_hechos} de {informe.dias}")
            if informe.recap_kg or informe.recap_euros:
                st.caption(
                    f"Según el donante (recapitulativo): {informe.recap_kg or 0:g} kg · "
                    f"{informe.recap_euros or 0:g} €"
                )
            izquierda_g, derecha_g = st.columns(2)
            with izquierda_g:
                st.markdown("**¿Qué hemos recibido?**")
                anillo(recibido_por_categoria(informe))
            with derecha_g:
                st.markdown("**¿Qué ha pasado con ello?**")
                if informe.sin_registro:
                    st.info("Mes anterior al inicio del registro diario: solo se documenta lo "
                            "recibido. No se estima lo consumido ni lo tirado.")
                else:
                    anillo(destino(informe))
            if informe.incidencias:
                with st.expander(f"Puntos a revisar ({len(informe.incidencias)})"):
                    for texto in informe.incidencias:
                        st.write(f"- {texto}")
            st.caption(f"Guardado también en: {ruta_p.parent}")
            st.download_button(
                "Descargar el anexo en PDF (todos los albaranes)", ruta_x.read_bytes(),
                file_name=ruta_x.name, mime="application/pdf",
            )
    with pestana_semanal:
        st.caption("Resumen de una semana (lunes a domingo): 1 hoja para imprimir.")
        ref = st.date_input("Cualquier día de la semana",
                            value=dt.date.today() - dt.timedelta(days=7), format="DD/MM/YYYY",
                            key="semana_ref")
        lunes = ref - dt.timedelta(days=ref.weekday())
        domingo = lunes + dt.timedelta(days=6)
        st.write(f"Semana del **{lunes:%d/%m/%Y}** al **{domingo:%d/%m/%Y}**")
        obs_sem = st.text_area("Observaciones de la semana (opcional)", height=80,
                               key="obs_semana")
        if st.button("Crear informe semanal", type="primary"):
            inicio_s = cargar_inicio_registro(con)
            informe_s = calcular_informe(
                cargar_lineas(con), cargar_salidas(con), lunes, domingo,
                cargar_personas(con), cargar_vida_util(con), obs_sem.strip(),
                cargar_controles(con), cargar_recuentos(con), (None, None), dt.date.today(),
                inicio_s,
            )
            ruta_s = escribir_pdf_semanal(informe_s, ruta_semanal(DATOS / "informes", lunes),
                                          inicio_s)
            st.session_state["informe_semanal"] = (informe_s, ruta_s)
        if "informe_semanal" in st.session_state:
            informe_s, ruta_s = st.session_state["informe_semanal"]
            if informe_s.albaranes == 0:
                st.warning("Esa semana no tiene albaranes guardados.")
            st.download_button("Descargar el informe semanal en PDF", ruta_s.read_bytes(),
                               file_name=ruta_s.name, mime="application/pdf", type="primary")
            x1, x2, x3 = st.columns(3)
            x1.metric("Albaranes", informe_s.albaranes)
            x2.metric("Líneas recibidas", informe_s.lineas)
            x3.metric("Controles hechos",
                      "Sin registro" if informe_s.sin_registro
                      else f"{informe_s.controles_hechos} de {informe_s.dias}")
            anillo(recibido_por_categoria(informe_s))
            st.caption(f"Guardado también en: {ruta_s.parent}")
