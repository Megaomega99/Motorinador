"""Coherencia entre capas: firmware ↔ backend ↔ frontend.

Estos tests no prueban lógica sino **contratos**. Son los que fallan cuando se
cambia un nombre en un sitio y se olvida en otro, que es justo el error que no
se ve hasta que la interfaz muestra "undefined" en producción.

Se leen los archivos reales de las otras capas (src/main.cpp, frontend/*.js) y se
comparan con los modelos de Pydantic.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.models import GEAR_RATIO, RPM_MAX, RPM_MIN, CmdMessage, Params, StatusFrame
from app.serial_link import _parse_line

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "src" / "main.cpp"
APP_JS = ROOT / "frontend" / "app.js"
INDEX_HTML = ROOT / "frontend" / "index.html"

pytestmark = pytest.mark.skipif(
    not (FIRMWARE.is_file() and APP_JS.is_file()),
    reason="Se ejecuta desde el repo completo",
)


def _firmware() -> str:
    return FIRMWARE.read_text(encoding="utf-8")


def _app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


# ── firmware ↔ backend ───────────────────────────────────────────


def test_status_format_string_of_the_firmware_is_parseable() -> None:
    """La cadena de formato real del firmware debe encajar con el regex del backend.

    Se extrae el snprintf de formatStatusLine() y se rellena con valores para
    comprobar que _parse_line lo entiende. Si alguien cambia una etiqueta en el
    firmware, este test lo caza sin necesidad de hardware.
    """
    src = _firmware()
    m = re.search(r'"(Tgt:%s[^"]*)\\r\\n"', src)
    assert m, "no se encontró la cadena de estado en el firmware"

    # Rellenar cada %s, en orden, con lo que pondría el firmware.
    line = m.group(1)
    for value in ("30.0", "-29.8", "-59.2", "185.4", "REV", "PARADO"):
        line = line.replace("%s", value, 1)

    frame = _parse_line(line)
    assert frame is not None, f"el backend no supo parsear: {line!r}"
    assert frame.target_rpm == 30.0
    assert frame.motor_rpm == -29.8
    assert frame.enc_rpm == -59.2
    assert frame.dir == "REV"
    assert frame.running is False


def test_rpm_limits_mirror_the_firmware() -> None:
    src = _firmware()
    fw_min = float(re.search(r"RPM_MIN\s*=\s*([\d.]+)f", src).group(1))
    fw_max = float(re.search(r"RPM_MAX\s*=\s*([\d.]+)f", src).group(1))
    assert (fw_min, fw_max) == (RPM_MIN, RPM_MAX)


def test_gear_ratio_mirrors_the_firmware() -> None:
    src = _firmware()
    fw_ratio = float(re.search(r"GEAR_RATIO\s*=\s*([\d.]+)f", src).group(1))
    assert fw_ratio == pytest.approx(GEAR_RATIO, abs=1e-3)


def test_firmware_has_no_pi_controller_left() -> None:
    """El PI se retiró: ni gains, ni integrador, ni comandos de modo."""
    src = _firmware()
    for token in ("PI_KP", "PI_KI", "piIntegral", "usePID", "updateControl", "controlRPM"):
        assert token not in src, f"resto del PI en el firmware: {token}"


def test_backend_commands_exist_in_the_firmware_dispatcher() -> None:
    """Cada carácter que emite el backend debe tener su `case` en handleCommand."""
    from app.serial_link import VALID_CMDS

    src = _firmware()
    dispatch = src[src.index("void handleCommand"):src.index("void setup")]
    cases = set(re.findall(r"case '(.)':", dispatch))
    # 'v' se gestiona en loop() (lleva argumento), no en handleCommand.
    assert (VALID_CMDS - {"v"}) <= cases, f"faltan en firmware: {VALID_CMDS - cases - {'v'}}"


# ── backend ↔ frontend ───────────────────────────────────────────


def test_frontend_reads_only_fields_that_the_status_frame_has() -> None:
    js = _app_js()
    block = js[js.index("case 'status'"):js.index("case 'log'")]
    used = set(re.findall(r"\bd\.([a-z_0-9]+)", block))
    known = set(StatusFrame.model_fields)
    assert used <= known, f"el frontend lee campos inexistentes: {sorted(used - known)}"


def test_frontend_reads_only_params_that_exist() -> None:
    js = _app_js()
    block = js[js.index("case 'params'"):js.index("case 'ready'")]
    used = set(re.findall(r"\bp\.([a-z_0-9]+)", block))
    known = set(Params.model_fields)
    assert used <= known, f"el frontend lee params inexistentes: {sorted(used - known)}"


def test_frontend_sends_only_params_that_exist() -> None:
    js = _app_js()
    block = js[js.index("function sendParams"):js.index("/* ===== UI bindings")]
    # Solo el interior del objeto `data:` — `type`/`data` son el sobre del mensaje.
    inner = block[block.index("data: {"):]
    sent = set(re.findall(r"^\s+([a-z_0-9]+):", inner, re.MULTILINE))
    known = set(Params.model_fields)
    assert sent, "no se detectó ningún campo enviado (¿cambió sendParams?)"
    assert sent <= known, f"el frontend envía params inexistentes: {sorted(sent - known)}"


def test_frontend_sends_only_known_commands() -> None:
    """Recoge tanto `cmd: 'x'` como `cmd: cond ? 'a' : 'b'`."""
    js = _app_js()
    sent = set(re.findall(r"cmd:\s*'([a-z_]+)'", js))
    for a, b in re.findall(r"cmd:\s*[^'\n]*\?\s*'([a-z_]+)'\s*:\s*'([a-z_]+)'", js):
        sent |= {a, b}
    from typing import get_args
    known = set(get_args(CmdMessage.model_fields["cmd"].annotation))
    assert sent, "no se detectó ningún comando enviado"
    assert sent <= known, f"el frontend envía comandos desconocidos: {sorted(sent - known)}"


def test_frontend_has_no_pi_leftovers() -> None:
    """Nada de modo PI en la interfaz: ni estado, ni comandos, ni tarjeta."""
    js = _app_js()
    html = INDEX_HTML.read_text(encoding="utf-8")
    for token in ("use_pid", "usePid", "mode_pi", "mode_libre", "pi_error",
                  "control_rpm", "measured_rpm", "pidControls", "modeSeg"):
        assert token not in js, f"resto del PI en app.js: {token}"
        assert token not in html, f"resto del PI en index.html: {token}"


# ── documentación ────────────────────────────────────────────────

README = ROOT / "README.md"
ANALYSIS_README = ROOT / "analysis" / "README.md"


def test_readme_does_not_document_the_retired_pi_commands() -> None:
    """El README no debe seguir listando 'p'/'l' como comandos válidos."""
    text = README.read_text(encoding="utf-8")
    assert "Modo PI / LIBRE" not in text
    assert "| `p` / `l` |" not in text
    # El toggle legado 'c' (alternar PI) también se fue.
    assert "`s` / `r` / `c`" not in text


def _firmware_pins() -> dict[str, int]:
    """Todas las constantes `PIN_* = n` del firmware."""
    return {
        name: int(value)
        for name, value in re.findall(r"const uint8_t (PIN_\w+)\s*=\s*(\d+);", _firmware())
    }


def test_readme_documents_the_actual_encoder_pins() -> None:
    """Los pines del encoder del README deben ser los del firmware.

    Los pines están compilados en el firmware, así que un README desactualizado
    hace que alguien cablee mal la placa. Pasó de verdad: el encoder se movió de
    D7/D8 a D2/D3 al dañarse esos pines.
    """
    pins = _firmware_pins()
    readme = README.read_text(encoding="utf-8")
    a, b = pins["PIN_ENC_A"], pins["PIN_ENC_B"]

    # La tabla de conexiones debe emparejar color de cable con el pin correcto.
    assert re.search(rf"Blanco\s+\(canal A\)\s+D{a}\b", readme), (
        f"el README no documenta el canal A en D{a}"
    )
    assert re.search(rf"Verde\s+\(canal B\)\s+D{b}\b", readme), (
        f"el README no documenta el canal B en D{b}"
    )
    # Y las salidas espejo deben citar el pin del que son espejo.
    assert f"espejo de D{a}" in readme and f"espejo de D{b}" in readme


def test_readme_has_no_stale_encoder_pins() -> None:
    """Ningún pin que el firmware NO usa debe aparecer como pin de señal."""
    pins = set(_firmware_pins().values())
    readme = README.read_text(encoding="utf-8")
    # Solo en el diagrama de conexiones, donde los pines llevan una flecha.
    wired = {int(n) for n in re.findall(r"^ │  D(\d+) ", readme, re.MULTILINE)}
    assert wired, "no se localizó el diagrama de conexiones"
    assert wired <= pins, f"el diagrama cita pines que el firmware no usa: {sorted(wired - pins)}"


def test_readme_explains_the_gearing() -> None:
    """El dato que cambia la interpretación de todo debe estar escrito."""
    text = README.read_text(encoding="utf-8")
    assert "engranaje" in text.lower()
    assert "lazo" in text.lower(), "debe decir que el control es en lazo abierto"


def test_readme_gear_ratio_matches_the_code() -> None:
    """La relación que documenta el README debe ser la que usa el código."""
    text = README.read_text(encoding="utf-8") + ANALYSIS_README.read_text(encoding="utf-8")
    documented = set(re.findall(r"1\.9\d\d?", text))
    assert documented, "el README no cita ninguna relación medida"
    for value in documented:
        assert abs(float(value) - GEAR_RATIO) < 0.02, (
            f"el README dice {value} pero el código usa {GEAR_RATIO}"
        )


def test_analysis_readme_documents_the_export_columns() -> None:
    """Las columnas nuevas del export deben estar documentadas con su nombre real."""
    text = ANALYSIS_README.read_text(encoding="utf-8")
    for column in ("analog_in_2_V", "step_count", "motor_rpm", "slip"):
        assert column in text, f"columna sin documentar: {column}"


# ── vista de análisis: contrato frontend ↔ API ───────────────────

ANALYSIS_JS = ROOT / "frontend" / "analysis.js"
CHART_JS = ROOT / "frontend" / "chart.js"


def _js_globals(text: str) -> set[str]:
    return set(re.findall(r"^(?:const|let|var|function|async function)\s+([A-Za-z_$][\w$]*)",
                          text, re.MULTILINE))


def test_analysis_view_dom_ids_all_exist() -> None:
    """Todo id que busca analysis.js debe existir en el HTML.

    Es el fallo típico al partir una interfaz en dos vistas: un `anEl('...')`
    apuntando a un id que se renombró, que solo se ve al usarla.
    """
    js = ANALYSIS_JS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    used = set(re.findall(r"anEl\('([^']+)'\)", js))
    used |= set(re.findall(r"getElementById\('([^']+)'\)", js))
    assert used, "no se detectó ningún acceso al DOM"
    assert used <= ids, f"ids inexistentes en el HTML: {sorted(used - ids)}"
    # Los canvas de los cuatro paneles se referencian por plantilla.
    for key in ("elec", "angle", "vel", "motor"):
        assert f'id="anCanvas_{key}"' in html, key


def test_analysis_scripts_do_not_collide_with_the_control_view() -> None:
    """app.js y analysis.js comparten el ámbito global de la página."""
    control = _js_globals(APP_JS.read_text(encoding="utf-8"))
    analysis = _js_globals(ANALYSIS_JS.read_text(encoding="utf-8"))
    chart = _js_globals(CHART_JS.read_text(encoding="utf-8"))
    assert not (control & analysis), f"colisión app/analysis: {sorted(control & analysis)}"
    assert not (control & chart), f"colisión app/chart: {sorted(control & chart)}"
    assert not (analysis & chart), f"colisión analysis/chart: {sorted(analysis & chart)}"


def test_analysis_view_sends_only_known_window_fields() -> None:
    from app.routes.analysis import ExportPayload, WindowPayload

    js = ANALYSIS_JS.read_text(encoding="utf-8")
    known = set(WindowPayload.model_fields) | set(ExportPayload.model_fields)
    # Cada objeto `body` que se manda a la API.
    for block in re.findall(r"const body = \{(.*?)\n  \};", js, re.DOTALL):
        sent = set(re.findall(r"^\s{4}([a-z_0-9]+):", block, re.MULTILINE))
        assert sent, "no se detectaron campos en el cuerpo de la petición"
        assert sent <= known, f"campos que la API no acepta: {sorted(sent - known)}"


def test_analysis_view_reads_fields_the_api_returns() -> None:
    """Los campos de metadatos/gearing que pinta la UI deben existir en la API."""
    js = ANALYSIS_JS.read_text(encoding="utf-8")
    meta_fields = set(re.findall(r"\bm\.([a-z_0-9]+)", js))
    known_meta = {"path", "n_samples", "duration_s", "sample_rate_hz", "n_parts",
                  "electrodes", "has_motor", "motor_channel", "gearing"}
    assert meta_fields <= known_meta, f"campos de meta inexistentes: {sorted(meta_fields - known_meta)}"

    gear_fields = set(re.findall(r"\bg\.([a-z_0-9]+)", js))
    known_gear = {"ratio", "median_ratio", "n_steady", "n_stall", "stall_pct",
                  "motor_revs", "enc_revs"}
    assert gear_fields <= known_gear, f"campos de gearing inexistentes: {sorted(gear_fields - known_gear)}"


def test_analysis_endpoints_used_by_the_view_exist() -> None:
    """Cada ruta que llama el frontend debe estar registrada en el router."""
    from app.routes.analysis import router

    js = ANALYSIS_JS.read_text(encoding="utf-8")
    called = set(re.findall(r"anApi\('(/[a-z/]+)", js))
    called |= {m.split("?")[0] for m in re.findall(r"anApi\(`(/[a-z/]+)", js)}
    called |= {"/browse"}      # se construye con concatenación de query
    registered = {r.path.replace("/api/analysis", "") for r in router.routes}
    assert called, "no se detectó ninguna llamada a la API"
    assert called <= registered, f"rutas inexistentes: {sorted(called - registered)}"


def test_every_status_field_the_ui_needs_is_actually_populated() -> None:
    """Los campos que pinta la UI deben venir rellenos en un frame real."""
    line = "Tgt:5.0RPM  Mot:4.9RPM  Enc:9.7RPM  Ang:12.3deg  Dir:FWD  CORRIENDO"
    frame = _parse_line(line)
    assert frame is not None
    data = frame.model_dump()
    for field in ("target_rpm", "motor_rpm", "enc_rpm", "angle_deg", "dir", "running"):
        assert data[field] is not None, field
