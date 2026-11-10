import datetime as dt

import pandas as pd
import pytest

from trazabilidad.archivo import archivar_pdf
from trazabilidad.parser import Albaran
from trazabilidad.registro import Linea, abrir_base, guardar_albaran
from trazabilidad.revision import (
    aplicar_categoria,
    categorias_disponibles,
    contar_lineas,
    preparar_revision,
    sin_categoria,
    validar_tabla,
)

FECHA = dt.date(2025, 9, 23)


@pytest.fixture
def con(tmp_path):
    con = abrir_base(tmp_path / "p.db")
    con.execute(
        "INSERT INTO catalogo VALUES ('60251', 'PAN HAM INTEGRAL RUS', 'Panadería y bollería')"
    )
    con.execute("INSERT INTO catalogo VALUES ('11168', 'MANZANILLA', 'Despensa')")
    return con


def albaran(*lineas, dudosas=()):
    return Albaran(lineas=[Linea(**linea) for linea in lineas], dudosas=list(dudosas))


def linea(codigo, descripcion, cantidad=1):
    return {"codigo": codigo, "descripcion": descripcion, "cantidad": cantidad, "unidad": "UN"}


def test_codigo_conocido_sale_ok_con_su_categoria(con):
    tabla = preparar_revision(albaran(linea("11168", "MANZANILLA")), con)
    assert tabla.loc[0, "Estado"] == "OK"
    assert tabla.loc[0, "Categoría"] == "Despensa"


def test_codigo_nuevo_pide_categoria(con):
    tabla = preparar_revision(albaran(linea("99999", "PRODUCTO RARO")), con)
    assert tabla.loc[0, "Estado"] == "Nuevo"
    assert pd.isna(tabla.loc[0, "Categoría"])


def test_codigo_mal_leido_se_detecta_por_la_descripcion(con):
    # el OCR leyó 50781 en vez de 60251, pero la descripción es la del catálogo
    tabla = preparar_revision(albaran(linea("50781", "PAN HAM INTEGRAL RUS", 4)), con)
    assert tabla.loc[0, "Estado"] == "Revisar"
    assert "60251" in tabla.loc[0, "Nota"]
    assert tabla.loc[0, "Categoría"] == "Panadería y bollería"


def test_codigo_conocido_con_otra_descripcion_se_marca_para_revisar(con):
    tabla = preparar_revision(albaran(linea("11168", "CROISSANT CACAO")), con)
    assert tabla.loc[0, "Estado"] == "Revisar"


def test_linea_dudosa_conserva_descripcion_y_cantidad(con):
    tabla = preparar_revision(albaran(dudosas=["ie SPAGHETTI 1,000 UN"]), con)
    fila = tabla.loc[0]
    assert (fila["Estado"], fila["Código"], fila["Cantidad"]) == ("Revisar", "", 1)
    assert "SPAGHETTI" in fila["Descripción"]


def test_categorias_incluyen_las_9_de_siempre_y_las_nuevas(con):
    con.execute("INSERT INTO catalogo VALUES ('1', 'X', 'Categoría nueva')")
    categorias = categorias_disponibles(con)
    assert categorias[0] == "Panadería y bollería"
    assert "Categoría nueva" in categorias
    assert len(categorias) == 10


def tabla_con(*filas):
    return pd.DataFrame(filas, columns=["Código", "Descripción", "Cantidad", "Unidad", "Categoría"])


def test_validar_tabla_correcta():
    lineas, categorias, errores = validar_tabla(
        tabla_con(("11168", "MANZANILLA", 1.0, "UN", "Despensa"))
    )
    assert errores == []
    assert lineas[0].codigo == "11168"
    assert categorias == {"11168": "Despensa"}


def test_validar_tabla_pide_categoria_y_codigo():
    _, _, errores = validar_tabla(
        tabla_con(
            ("11168", "MANZANILLA", 1.0, "UN", None),
            ("", "SPAGHETTI", 1.0, "UN", "Despensa"),
        )
    )
    assert any("falta la categoría" in e for e in errores)
    assert any("Fila 2" in e and "Código" in e for e in errores)


def test_validar_tabla_ignora_filas_en_blanco_y_rechaza_tabla_vacia():
    assert validar_tabla(tabla_con((None, None, None, None, None)))[2] == [
        "No hay ninguna línea que guardar"
    ]


def test_mismo_codigo_con_dos_categorias_es_error():
    _, _, errores = validar_tabla(
        tabla_con(
            ("1234", "A", 1.0, "UN", "Despensa"),
            ("1234", "A", 2.0, "UN", "Lacteos y Huevos"),
        )
    )
    assert any("dos categorías" in e for e in errores)


def test_archivar_pdf_por_mes_con_el_numero_de_albaran(tmp_path):
    origen = tmp_path / "subido.PDF"
    origen.write_bytes(b"%PDF")
    destino = archivar_pdf(origen, tmp_path / "archivo", FECHA, "DON12342025092300001")
    assert destino == tmp_path / "archivo" / "2025-09" / "DON12342025092300001.pdf"
    assert destino.read_bytes() == b"%PDF"
    with pytest.raises(FileExistsError):
        archivar_pdf(origen, tmp_path / "archivo", FECHA, "DON12342025092300001")


def test_de_la_revision_al_registro(con):
    tabla = preparar_revision(albaran(linea("11168", "MANZANILLA", 3)), con)
    lineas, categorias, errores = validar_tabla(tabla)
    assert errores == []
    assert guardar_albaran(
        con, FECHA, "DON12342025092300001", lineas, categorias_elegidas=categorias
    ) == 1


def test_linea_dudosa_sugiere_el_codigo_si_la_descripcion_esta_en_el_catalogo(con):
    tabla = preparar_revision(albaran(dudosas=["ease PAN HAM INTEGRAL RUS 4,000 UN"]), con)
    fila = tabla.loc[0]
    assert (fila["Código"], fila["Cantidad"]) == ("60251", 4)
    assert fila["Categoría"] == "Panadería y bollería"
    assert "60251" in fila["Nota"]


def test_descripcion_de_linea_dudosa_sin_ruido(con):
    tabla = preparar_revision(albaran(dudosas=["ease ENSALADA JAMON 3,000 UN"]), con)
    assert tabla.loc[0, "Descripción"] == "ENSALADA JAMON"


def test_poner_categoria_a_las_filas_que_no_la_tienen(con):
    tabla = preparar_revision(
        albaran(linea("11168", "MANZANILLA"), linea("99999", "RARO"), linea("88888", "OTRO")), con
    )
    assert sin_categoria(tabla).tolist() == [False, True, True]
    nueva = aplicar_categoria(tabla, "Lacteos y Huevos")
    assert nueva["Categoría"].tolist() == ["Despensa", "Lacteos y Huevos", "Lacteos y Huevos"]
    assert not sin_categoria(nueva).any()
    assert tabla["Categoría"].isna().sum() == 2  # la tabla original no se modifica


def test_aplicar_categoria_no_toca_filas_en_blanco():
    tabla = pd.DataFrame(
        [
            {"Estado": "Nuevo", "Código": "1", "Descripción": "X", "Cantidad": 1,
             "Unidad": "UN", "Categoría": None, "Nota": ""},
            {"Estado": None, "Código": None, "Descripción": None, "Cantidad": None,
             "Unidad": None, "Categoría": None, "Nota": None},
        ]
    )
    nueva = aplicar_categoria(tabla, "Despensa")
    assert nueva.loc[0, "Categoría"] == "Despensa"
    assert pd.isna(nueva.loc[1, "Categoría"])
    assert contar_lineas(nueva) == 1


def test_validar_ignora_filas_en_blanco_con_categoria():
    tabla = pd.DataFrame(
        [
            {"Código": "1", "Descripción": "X", "Cantidad": 1, "Unidad": "UN",
             "Categoría": "Despensa"},
            {"Código": None, "Descripción": None, "Cantidad": None, "Unidad": None,
             "Categoría": "Despensa"},
        ]
    )
    lineas, _, errores = validar_tabla(tabla)
    assert len(lineas) == 1
    assert errores == []


def test_linea_dudosa_con_codigo_en_el_texto_separa_codigo_y_descripcion(con):
    albaran = Albaran(fecha=FECHA, num_albaran="X", dudosas=["83230 BAGUETTE “ 8,000 UN"])
    fila = preparar_revision(albaran, con).iloc[0]
    assert fila["Código"] == "83230" and fila["Descripción"].startswith("BAGUETTE")
    assert fila["Cantidad"] == 8 and fila["Estado"] == "Revisar"


def test_linea_con_cantidad_leida_como_simbolo_no_se_descarta(con):
    from trazabilidad.parser import leer_albaran

    texto = "Fecha: 05-05-2026 DON12342026050500001\n27326 COLA { UN\n8492 RESERVA LONCHAS | UN\n"
    albaran = leer_albaran(texto)
    assert len(albaran.dudosas) == 2 and not albaran.lineas
    tabla = preparar_revision(albaran, con)
    assert list(tabla["Código"]) == ["27326", "8492"]
    assert list(tabla["Descripción"]) == ["COLA", "RESERVA LONCHAS"]
    assert tabla["Cantidad"].isna().all() and set(tabla["Estado"]) == {"Revisar"}


def test_linea_sin_ninguna_cantidad_tampoco_se_pierde(con):
    from trazabilidad.parser import leer_albaran

    albaran = leer_albaran("DON12342026050500001\n67563 PAN QUESO 18% UN\n")
    assert albaran.dudosas == ["67563 PAN QUESO 18% UN"]
    fila = preparar_revision(albaran, con).iloc[0]
    assert fila["Código"] == "67563" and fila["Descripción"] == "PAN QUESO 18%"
    assert pd.isna(fila["Cantidad"]) and fila["Estado"] == "Revisar"


@pytest.mark.parametrize(("texto", "marcada"), [
    ("8177 MANZ. ROJA DULCE 675 KG", True),
    ("8177 MANZ. ROJA DULCE 6,75 KG", False),
    ("1002 LECHE ENTERA 120 UN", True),
    ("1002 LECHE ENTERA 20 UN", False),
])
def test_cantidad_imposible_se_marca_para_revisar(con, texto, marcada):
    from trazabilidad.parser import leer_albaran

    fila = preparar_revision(leer_albaran("DON12342026050500001\n" + texto + "\n"), con).iloc[0]
    assert (fila["Estado"] == "Revisar" and "Cantidad muy alta" in fila["Nota"]) == marcada
