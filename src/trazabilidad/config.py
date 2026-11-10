"""Ajustes que identifican al centro y al donante en los informes.

Se pueden cambiar sin tocar el código con variables de entorno:
    TRAZABILIDAD_CENTRO   nombre del centro que figura en los informes
    TRAZABILIDAD_ORIGEN   nombre del donante (supermercado, banco de alimentos...)
"""

import os

CENTRO = os.environ.get("TRAZABILIDAD_CENTRO", "Centro de ejemplo · Ciudad")
ORIGEN = os.environ.get("TRAZABILIDAD_ORIGEN", "Donante de ejemplo")
