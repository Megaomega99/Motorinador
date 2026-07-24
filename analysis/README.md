# Análisis de encoder y electrodos (GUI TkInter)

Herramienta de escritorio para inspeccionar **offline** las grabaciones de banco:
reconstruye el **ángulo** y la **velocidad angular** del motor a partir de las dos
señales digitales de cuadratura del encoder (grabadas junto a los electrodos) y
permite revisarlas junto a la actividad de los electrodos, sin saturar la RAM.

Reutiliza la geometría del encoder del firmware ([../src/main.cpp](../src/main.cpp)):
`ENC_PPR = 600`, decodificación X4 → `COUNTS_PER_REV = 2400`.

## Instalación

Requiere Python 3.13 (probado en el `base` de miniforge). Solo `neo` suele faltar:

```bash
pip install -r analysis/requirements.txt
```

## Uso

```bash
python -m analysis.app
```

1. **Abrir archivo** `.txt` (export tabular de Intan) o `.rhs` (binario Intan).
   Se procesa por segmentos a un caché HDF5 temporal (barra de progreso).
2. **Elegir unidades**: ángulo (rad / grados), velocidad (rad/s, grad/s, RPM) y
   la ventana de suavizado de la velocidad (ms).
3. **Seleccionar ≥ 3 electrodos** (Ctrl/Shift en la lista).
4. **Navegar** por segmentos (longitud de ventana + deslizador + ◀/▶). Las tres
   gráficas (electrodos, ángulo, velocidad) comparten el eje de tiempo.
5. **Estadísticos**: velocidad media de la sesión, tabla de la sesión y tabla de
   la ventana visible (se actualiza al navegar).
6. **Exportar** con columnas de ángulo y velocidad añadidas a CSV/TXT o HDF5.

## Formatos de entrada

| Formato | Soporte | Notas |
|---------|---------|-------|
| `.txt`  | ✅ | Export tabular de Intan. Las columnas `DIGITAL-IN` son **pulsos de flanco**; el lector reconstruye el nivel por paridad (ver abajo). |
| `.rhs`  | ✅ | Binario Intan monolítico, leído con `neo.rawio.IntanRawIO` (memmap, RAM plana). |
| `.smrx` / `.s2rx` | ❌ | Spike2. `sonpy` no tiene wheel para Python 3.13 en Linux. Convertir a `.txt`/`.rhs` si hace falta. |

### Detalle importante: codificación de las señales digitales en `.txt`

En el `textform.txt` de este proyecto, `DIGITAL-IN-01`/`02` **no** son el nivel del
canal sino un pulso de una muestra en cada flanco. El nivel real es la paridad
acumulada (`nivel[i] = Σ pulsos[0..i] mod 2`). El `.rhs` sí da niveles directos.
Verificado: ambas vías dan el **mismo** conteo del encoder (X4). El lector `.txt`
normaliza esto por defecto (`digital_mode="toggle"`).

## Diseño (RAM plana)

Una única pasada por segmentos vuelca conteo del encoder + electrodos a un HDF5
chunked. Después, `SessionCache` sirve tramos (ventana visible), la vista general
decimada (envolvente min/max) y los estadísticos leyendo del HDF5. El conteo del
encoder (~8 MB/millón de muestras) se mantiene en RAM; ángulo y velocidad se
derivan de él al vuelo. Los 32 electrodos nunca se cargan enteros a la vez.

## Módulos

| Archivo | Responsabilidad |
|---------|-----------------|
| `units.py` | Unidades y conversiones (cuentas ↔ ángulo ↔ velocidad). |
| `encoder.py` | Decodificación X4 vectorizada (stateful) + ángulo + velocidad. |
| `readers/` | `base` (Protocol), `txt_reader`, `rhs_reader`, `factory`. |
| `processing.py` | Construcción del caché HDF5 + `SessionCache` + decimación. |
| `stats.py` | Estadísticos de velocidad (sesión y ventana). |
| `exporter.py` | Exportación por segmentos a CSV/TXT/HDF5 con columnas nuevas. |
| `ui/` | `controls`, `plot_panel`, `stats_panel`, `main_window`. |
| `app.py` | Punto de entrada. |

## Tests

```bash
pytest analysis/tests/ --cov=analysis
```

Incluye una validación cruzada sobre los datos reales de `intento_260724_104300`
(se salta si no están presentes) que comprueba que el ángulo del `.txt` y el del
`.rhs` coinciden. Los tests de GUI se saltan si no hay `DISPLAY`.
