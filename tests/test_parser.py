import datetime as dt
import json
from pathlib import Path

import pytest

from trazabilidad.lectura import paginas_a_imagenes
from trazabilidad.ocr import leer_albaran as ocr_albaran
from trazabilidad.parser import cantidad_a_numero, leer_albaran, leer_linea

DATOS = Path(__file__).parent / "datos"
NOMBRES = ["20250920", "20250923", "20250924"]
MINIMO_CORRECTAS = 0.85  # líneas con código y cantidad bien
MINIMO_SIN_PERDER = 0.95  # líneas bien + líneas marcadas como dudosas

CABECERA = "Fecha: 23-09-2025   Nº de albarán:  DON12342025092300001"


def test_cantidades_con_coma():
    assert cantidad_a_numero("1,000") == 1
    assert cantidad_a_numero("10,000") == 10
    assert cantidad_a_numero("13") == 13


def test_linea_normal():
    linea = leer_linea("11168 MANZANILLA 1,000 UN")
    assert (linea.codigo, linea.descripcion, linea.cantidad, linea.unidad) == (
        "11168",
        "MANZANILLA",
        1,
        "UN",
    )


def test_linea_con_trazo_de_lapiz_delante():
    linea = leer_linea("x ™~ 3724 PECHUGA 2 UND 1,000 UN")
    assert linea.codigo == "3724"
    assert linea.descripcion == "PECHUGA 2 UND"


def test_descripcion_que_empieza_por_numero():
    linea = leer_linea("31310 6 HUEVOS CAMPEROS 1,000 UN")
    assert linea.codigo == "31310"
    assert linea.descripcion == "6 HUEVOS CAMPEROS"


def test_lo_que_no_es_una_linea_da_none():
    assert leer_linea("CÓDIGO DESCRIPCIÓN CANT. UNIDAD") is None
    assert leer_linea("PROVEEDOR S.A.") is None


def test_linea_sin_codigo_se_marca_como_dudosa_no_se_pierde():
    texto = f"{CABECERA}\nie SPAGHETTI 1,000 UN\n11168 MANZANILLA 1,000 UN\nRECIBI:"
    albaran = leer_albaran(texto)
    assert len(albaran.lineas) == 1
    assert albaran.dudosas == ["ie SPAGHETTI 1,000 UN"]


def test_cabecera_fecha_y_numero():
    albaran = leer_albaran(f"{CABECERA}\nRECIBI:")
    assert albaran.fecha == dt.date(2025, 9, 23)
    assert albaran.num_albaran == "DON12342025092300001"
    assert albaran.avisos == []


def test_cabecera_repetida_en_la_segunda_pagina_no_da_aviso():
    texto = f"{CABECERA}\n11168 MANZANILLA 1,000 UN\n{CABECERA}\n6331 SPAGHETTI 1,000 UN\nRECIBI:"
    albaran = leer_albaran(texto)
    assert len(albaran.lineas) == 2
    assert albaran.avisos == []


def test_numero_distinto_entre_paginas_avisa():
    otro = "Fecha: 23-09-2025   Nº de albarán:  DON12342025092300002"
    albaran = leer_albaran(f"{CABECERA}\n{otro}\nRECIBI:")
    assert any("distintos" in aviso for aviso in albaran.avisos)


def test_el_aviso_de_recibi_ya_no_existe():
    assert leer_albaran(f"{CABECERA}\n11168 MANZANILLA 1,000 UN").avisos == []


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("2635 _ RABO CERDO 4,000 UN", "RABO CERDO"),
        ("69853 CALABAZA PARTIDA | 4,000 UN", "CALABAZA PARTIDA"),
        ("69756 ENSALADA DE LA CASA & 3,000 UN", "ENSALADA DE LA CASA"),
        ("69884 ease ENSALADA JAMON 3,000 UN", "ENSALADA JAMON"),
        ('68138 " NATILLAS CHOCOLATE 1,000 UN', "NATILLAS CHOCOLATE"),
        ("83056 PAN CENTENO 51 % 16,000 UN", "PAN CENTENO 51 %"),
        ("29106 HARINA DE TRIGO 5KG. 1,000 UN", "HARINA DE TRIGO 5KG."),
        ("12049 P INTEGRAL TRIGO100% 4,000 UN", "P INTEGRAL TRIGO100%"),
        ("31310 6 HUEVOS CAMPEROS 1,000 UN", "6 HUEVOS CAMPEROS"),
    ],
)
def test_limpia_el_ruido_de_las_descripciones_sin_tocar_las_buenas(texto, esperado):
    assert leer_linea(texto).descripcion == esperado


@pytest.mark.ocr
def test_lectura_completa_de_los_albaranes_de_ejemplo():
    total = correctas = sin_perder = 0
    print()
    for nombre in NOMBRES:
        ruta = DATOS / "albaranes" / f"albaran_{nombre}.pdf"
        if not ruta.exists():
            pytest.skip(f"Falta {ruta.name}")
        esperado = json.loads((DATOS / "esperado" / f"albaran_{nombre}.json").read_text("utf-8"))
        albaran = leer_albaran(ocr_albaran(paginas_a_imagenes(ruta)))
        leidas = {(linea.codigo, linea.cantidad) for linea in albaran.lineas}
        n = len(esperado["lineas"])
        bien = sum((e["codigo"], e["cantidad"]) in leidas for e in esperado["lineas"])
        cubiertas = min(n, len(albaran.lineas) + len(albaran.dudosas))
        print(
            f"  {nombre}: {bien}/{n} bien ({bien / n:.0%}) | "
            f"{len(albaran.dudosas)} dudosas | avisos: {albaran.avisos or 'ninguno'}"
        )
        assert albaran.num_albaran == esperado["num_albaran"]
        assert albaran.fecha == dt.date.fromisoformat(esperado["fecha"])
        total += n
        correctas += bien
        sin_perder += cubiertas
    print(f"  TOTAL bien: {correctas}/{total} ({correctas / total:.0%})")
    print(f"  TOTAL sin perder líneas: {sin_perder}/{total} ({sin_perder / total:.0%})")
    assert correctas / total >= MINIMO_CORRECTAS
    assert sin_perder / total >= MINIMO_SIN_PERDER


def test_comilla_pegada_a_la_cantidad_no_rompe_la_linea():
    from trazabilidad.parser import leer_linea

    for texto in ('83230 BAGUETTE “8,000 UN', '83230 BAGUETTE “ 8,000UN', '83230 BAGUETTE “8 UN'):
        linea = leer_linea(texto)
        assert linea and linea.codigo == "83230" and linea.cantidad == 8
        assert linea.descripcion.startswith("BAGUETTE")


def test_albaran_resumen_de_donaciones_diarias_sin_palabra_fecha():
    from trazabilidad.parser import leer_albaran

    texto = (
        "RESUMEN DE DONACIONES DIARIAS 12-05-2026 DON12342026051200001\n"
        "19897 AZUCAR 1 UN\n11931 ESPRESSO INTENSO 1 UN\n"
    )
    albaran = leer_albaran(texto)
    assert albaran.fecha == dt.date(2026, 5, 12)
    assert albaran.num_albaran == "DON12342026051200001" and len(albaran.lineas) == 2
    assert not albaran.avisos


def test_fecha_se_toma_del_numero_si_no_aparece():
    from trazabilidad.parser import leer_albaran

    albaran = leer_albaran("DON12342026051200001\n19897 AZUCAR 1 UN\n")
    assert albaran.fecha == dt.date(2026, 5, 12) and albaran.avisos


def test_numero_leido_distinto_por_una_cifra_en_otra_pagina_es_el_mismo_albaran():
    texto = (
        "RESUMEN DE DONACIONES DIARIAS 03-08-2026 DON12342626080300001\n"
        "1001 ARROZ 2 UN\n"
        "Fecha: 03-08-2026 DON12342026080300001\n"
        "1002 LECHE 1 UN\n"
    )
    albaran = leer_albaran(texto)
    assert albaran.num_albaran == "DON12342026080300001"
    assert not albaran.avisos


def test_numero_unico_mal_leido_se_corrige_con_la_fecha_y_avisa():
    albaran = leer_albaran("Fecha: 03-08-2026 DON12342626080300001\n1001 ARROZ 2 UN\n")
    assert albaran.num_albaran == "DON12342026080300001"
    assert any("corregido" in a for a in albaran.avisos)


def test_dos_albaranes_distintos_si_avisan():
    texto = "Fecha: 03-08-2026 DON12342026080300001\nFecha: 03-08-2026 DON12342026080300002\n"
    albaran = leer_albaran(texto)
    assert any("distintos" in a for a in albaran.avisos)
    albaran = leer_albaran("Fecha: 03-08-2026 DON12342026080400001\n"
                           "Fecha: 03-08-2026 DON12342026080300001\n")
    assert albaran.num_albaran == "DON12342026080300001"  # el que cuadra con la fecha
    assert any("distintos" in a for a in albaran.avisos)  # otro día: puede ser otro albarán


@pytest.mark.parametrize(
    ("texto", "cantidad", "unidad"),
    [
        ("8177 MANZ. ROJA DULCE 6,75 KG", 6.75, "KG"),
        ("5001 CIRUELA 0,834 KG", 0.834, "KG"),
        ("5002 PLATANO 12,5 KG", 12.5, "KG"),
        ("5003 NARANJA 1,000 UN", 1.0, "UN"),
        ("5004 UVA BLANCA 0,5 KG", 0.5, "KG"),
        ("5005 PERA 2 KG", 2.0, "KG"),
        ("5006 SANDIA “1,25 KG", 1.25, "KG"),
    ],
)
def test_cantidades_con_uno_dos_o_tres_decimales(texto, cantidad, unidad):
    linea = leer_linea(texto)
    assert linea and linea.cantidad == cantidad and linea.unidad == unidad


@pytest.mark.parametrize(("texto", "cantidad"), [
    ("83908 MOLLETE 3 UD 4000 UN", 4.0), ("83908 MOLLETE 3 UD 12000 UN", 12.0),
    ("83908 MOLLETE 3 UD 1000 UN", 1.0), ("83908 MOLLETE 3 UD 4,000 UN", 4.0),
    ("83908 MOLLETE 3 UD 4.000 UN", 4.0),
])
def test_coma_perdida_en_cantidad_con_tres_ceros(texto, cantidad):
    linea = leer_linea(texto)
    assert linea and linea.cantidad == cantidad and linea.descripcion == "MOLLETE 3 UD"


@pytest.mark.parametrize("digito", list("0123456789"))
def test_todos_los_digitos_como_cantidad(digito):
    linea = leer_linea(f"2807 TACOS ANOJO {digito} UN".replace(" 0 UN", " 7 UN"))
    assert linea and linea.cantidad == float(digito if digito != "0" else "7")
