"""Paso 1: comprobar que el entorno funciona y que el paquete se importa."""
import sys

import trazabilidad


def test_python_311_o_superior():
    assert sys.version_info >= (3, 11)


def test_paquete_importable():
    assert trazabilidad.__version__
