import sqlite3

from trazabilidad.registro import abrir_base
from trazabilidad.servidor import (
    cargar_carpeta,
    copia_diaria_pendiente,
    copiar_al_servidor,
    guardar_carpeta,
    marcar_copia_hecha,
)


def test_copia_al_servidor(tmp_path):
    datos = tmp_path / "datos"
    (datos / "informes" / "2026" / "2026-01").mkdir(parents=True)
    (datos / "informes" / "2026" / "2026-01" / "informe.pdf").write_bytes(b"x")
    (datos / "pdf_archivo").mkdir()
    (datos / "pdf_archivo" / "a.pdf").write_bytes(b"y")
    con = abrir_base(datos / "registro.db")
    destino = tmp_path / "servidor" / "Registro"
    texto = copiar_al_servidor(con, datos, destino)
    assert "1 archivo(s) de informes" in texto
    assert (destino / "informes" / "2026" / "2026-01" / "informe.pdf").exists()
    assert (destino / "albaranes_pdf" / "a.pdf").exists()
    copia = next((destino / "copias_seguridad").glob("registro_*.db"))
    assert sqlite3.connect(copia).execute("SELECT count(*) FROM entradas").fetchone()[0] == 0
    assert "0 archivo(s) de informes" in copiar_al_servidor(con, datos, destino)  # nada nuevo


def test_ajustes_de_la_copia(tmp_path):
    con = abrir_base(tmp_path / "r.db")
    assert cargar_carpeta(con) == "" and copia_diaria_pendiente(con)
    guardar_carpeta(con, r"\\servidor\carpeta\Registro")
    marcar_copia_hecha(con)
    assert cargar_carpeta(con) == r"\\servidor\carpeta\Registro" and not copia_diaria_pendiente(con)
