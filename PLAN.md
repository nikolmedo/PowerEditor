# AutoCut — Plan de desarrollo

App local para Windows que edita videos casi 100% en automático: elige la mejor toma cuando hay repeticiones, elimina silencios, aplica transiciones, genera subtítulos y permite retoques simples desde una interfaz gráfica.

## Convenciones para el desarrollo

- Todo el código, nombres de variables, funciones, tipos, commits y comentarios: **100% en inglés**.
- La UI puede tener textos en español (vía archivo de strings, no hardcodeados).
- Python: `uv`, Python 3.11+, type hints estrictos, `pydantic` para modelos, `ruff` + `mypy`.
- TypeScript: `strict: true`, `pnpm` workspaces, ESLint + Prettier.
- Cada etapa del pipeline escribe su salida en JSON cacheado; nunca recalcular una etapa si sus entradas no cambiaron (hash de inputs + params).
- Llamadas a FFmpeg siempre con `subprocess` y lista de argumentos (nunca string con shell) por paths con espacios/acentos en Windows.
- No avanzar de fase sin cumplir los criterios de aceptación de la fase actual.

## Objetivos y no-objetivos

**Objetivos**
- Procesamiento automático: tomas, silencios, transiciones, subtítulos, audio y color con defaults buenos.
- UI simple de 3 pasos: Cargar → Revisar/Ajustar → Exportar.
- Consumo mínimo de modelos pagos: heurísticas deterministas primero; Jev solo para juicios semánticos; Whisper local por defecto.
- Preview = render (WYSIWYG).

**No-objetivos (v1)**
- Multicámara / sincronización por audio.
- Keyframes, máscaras, chroma key, LUTs (.cube).
- Más de una pista de video.
- Arrastre libre de clips en el timeline.
- Empaquetado como instalador (v1 corre con scripts locales).

## Stack

| Capa | Tecnología |
|---|---|
| Backend / análisis | Python 3.11+, FastAPI, uvicorn, pydantic, typer (CLI) |
| Transcripción | `faster-whisper` (local) o OpenAI `whisper-1` (API) |
| VAD | Silero VAD + umbral de dB |
| Similitud de tomas | `rapidfuzz` + embeddings locales (`intfloat/multilingual-e5-small` vía `sentence-transformers`) |
| Features visuales | OpenCV + MediaPipe (rostro, nitidez) |
| Decisiones | Motor heurístico (default) o Jev de TypeSafe AI |
| Media | FFmpeg / ffprobe (build con NVENC si hay NVIDIA) |
| Preview y render | Remotion (`@remotion/player` en la UI, Remotion CLI para render) |
| Frontend | React + Vite + TypeScript, zustand + zundo (undo/redo) |
| Export para NLE (opcional) | OpenTimelineIO → FCPXML |

**Licencia Remotion:** gratis para individuos y empresas de hasta 3 personas. Revisar si alguna vez se distribuye/vende la app.

## Arquitectura

```
web/ (React UI + @remotion/player)
   │  REST + WebSocket (job progress)
backend/ (FastAPI): ingest, transcription, VAD, clustering, decisions, file serving
   │  subprocess
packages/composition (Remotion) → render MP4 → FFmpeg final pass (loudnorm)
```

- **Fuente de verdad:** `projects/<project_id>/project.json`. Python genera el borrador automático, la UI lo edita, Remotion lo renderiza.
- La composición de Remotion vive en un paquete compartido: la UI la importa para el Player y el backend la usa para renderizar con la CLI (`--props` apuntando al `project.json`).
- **Shell v1:** app web local (FastAPI sirve el build de React). Electron solo si después se necesita como app de escritorio (ya trae Node, que Remotion necesita).

## Estructura del repo

```
autocut/
  backend/
    pyproject.toml
    autocut/
      config.py              # pydantic-settings, reads .env
      models.py              # Word, Segment, Take, TakeCluster, Project, Clip...
      api/
        app.py               # FastAPI app, static web build
        routes_projects.py
        routes_jobs.py       # WebSocket progress
        routes_media.py      # range-request file serving for proxies
      pipeline/
        runner.py            # stage orchestration + cache
        ingest.py            # ffprobe, CFR mezzanine, proxy, audio extraction
        vad.py
        segmentation.py
        clustering.py
        features.py          # deterministic take features
        color_stats.py       # per-source luma/balance stats
        loudness.py          # LUFS measurement
        draft_builder.py     # builds initial project.json
      transcribe/
        base.py              # Transcriber protocol
        local_whisper.py     # faster-whisper
        openai_whisper.py    # whisper-1, verbose_json, word granularity
      decide/
        base.py              # DecisionEngine protocol
        heuristic.py
        jev.py               # TypeSafe SDK + confidence gating
      render/
        remotion_render.py   # calls Remotion CLI
        final_pass.py        # ffmpeg loudnorm, container
      export/
        subtitles.py         # SRT/ASS export + timeline remap
        otio_export.py
      cli.py                 # typer: ingest, analyze, render (no UI)
    tests/
  packages/
    composition/             # Remotion compositions (shared)
      src/
        Root.tsx
        ProjectVideo.tsx
        clips/
        transitions/
        subtitles/
        overlays/            # LowerThird, Title, Cta, Logo, ProgressBar, ImageOverlay
        color/               # CSS/SVG filter builders
        types.ts             # mirrors backend Project schema
  web/
    src/
      steps/                 # LoadStep, ReviewStep, ExportStep
      timeline/
      panels/                # Clip, Transitions, Subtitles, Audio, Color, Graphics
      store/                 # zustand + zundo
      i18n/es.json
  projects/                  # runtime data (gitignored)
  pnpm-workspace.yaml
  .env.example
```

## Configuración (`.env.example`)

```env
TRANSCRIBER=local            # local | openai
WHISPER_MODEL=large-v3-turbo # use medium/small on CPU
WHISPER_DEVICE=auto          # auto | cuda | cpu
WHISPER_LANGUAGE=es
OPENAI_API_KEY=

DECISION_ENGINE=heuristic    # heuristic | jev
TYPESAFE_API_KEY=            # verify the env var name the SDK expects
JEV_MODEL=jev-1.13
JEV_MIN_CONFIDENCE=0.8

SILENCE_PADDING_MS=120
AUDIO_CROSSFADE_MS=15
TARGET_LUFS=-14
PUNCH_IN_SCALE=1.1
```

## Pipeline

Cada etapa: input → output JSON en `projects/<id>/cache/<stage>.json`.

1. **Ingest**
   - `ffprobe` de cada archivo.
   - Generar **mezzanine** H.264 CFR alta calidad (para render) y **proxy** H.264 540p (para preview). Motivo: los celulares graban VFR, y HEVC/ProRes no se reproducen bien en el navegador.
   - Extraer audio WAV mono 16 kHz.
2. **Transcribe** → `Word{text, start, end, prob | None}` normalizado para ambos proveedores.
   - Prompt inicial con muletillas ("Eh, este, mmm...") para que Whisper no las omita.
3. **VAD** → rangos de habla, padding configurable.
4. **Segmentation** → frases por pausas largas + puntuación.
5. **Clustering** de tomas repetidas:
   - Similitud ≥ 0.8 → misma parte.
   - 0.5–0.8 → zona gris: Jev decide (o heurística con umbral 0.7).
6. **Features deterministas por toma** (todo en código):
   - Completitud vs guion (si hay) o vs toma más larga del grupo.
   - Conteo de muletillas, repeticiones, frase cortada (regex/heurística).
   - Velocidad de habla, confianza media de Whisper (si existe).
   - Loudness, clipping.
   - Rostro centrado, nitidez (sample de frames).
   - Bonus por ser la última toma.
7. **Decisiones** (`DecisionEngine`): ver sección Jev.
8. **Color stats y loudness** por archivo de origen → valores iniciales para igualar.
9. **Draft builder** → `project.json` con clips, transiciones, subtítulos remapeados al timeline, pistas de audio y color inicial.

### Subtítulos
- No re-transcribir el video final: remapear timestamps de palabras source → timeline usando los clips (considerando `speed`).
- Edición de texto en la UI conserva los tiempos de cada palabra.
- Export adicional opcional: SRT/ASS.

### Transiciones por defecto
- Entre frases del mismo bloque: `punch_in` (alternar escala 1.0 / `PUNCH_IN_SCALE`).
- Entre bloques con cambio de tema: `fade` o `slide`.
- Crossfade de audio de `AUDIO_CROSSFADE_MS` en cada corte.

## Transcripción: proveedores

```python
class Transcriber(Protocol):
    def transcribe(self, audio_path: Path, language: str | None) -> Transcript: ...
```

| Proveedor | Timestamps por palabra | Notas |
|---|---|---|
| `local` (faster-whisper) | Sí | Default. Requiere CUDA 12 + cuDNN 9 en PATH para GPU (verificar en README). |
| `openai` (`whisper-1`) | Sí, `response_format=verbose_json` + `timestamp_granularities=["word"]` | Para PCs sin GPU. Whisper V2: no es mejora de calidad sobre `large-v3-turbo`. |
| `gpt-4o-transcribe` / `mini` | No (solo `json`) | Fuera de v1. Opción futura: texto + alineación forzada local. |

- API: verificar límite de tamaño de archivo (probablemente 25 MB). Enviar audio mono 16 kHz comprimido (Opus/MP3) y partir en silencios si excede.
- `whisper-1` no da probabilidad por palabra: esa feature queda `None` y el scoring debe tolerarlo.

## Motor de decisiones (Jev)

```python
class DecisionEngine(Protocol):
    def decide_cluster(self, cluster: TakeCluster, features: list[TakeFeatures]) -> ClusterDecision: ...
    def classify_segment(self, segment: Segment) -> SegmentFlags: ...
    def transition_between(self, prev: Segment, next: Segment) -> TransitionDecision: ...
```

Implementaciones: `HeuristicEngine` (default, fallback siempre disponible) y `JevEngine`.

**Docs Jev:** https://docs.typesafe.ai/llms.txt (índice) y https://docs.typesafe.ai/agent-skill.md (skill para agentes). Leer antes de implementar `jev.py`; no adivinar firmas de `Choice` y `Score`.

Ejemplo verificado en docs (Noul):

```python
from typesafe_sdk import Noul, TypeSafeClient

client = TypeSafeClient(model="jev-1.13")
result = client.system_one(
    {"segment_text": text},
    {"is_audience_content": Noul(instructions="...")},
)
probability = result.nouls["is_audience_content"].noul
```

### Preguntas a Jev

| Decisión | Primitiva | State mínimo |
|---|---|---|
| ¿Contenido para la audiencia o comentario fuera de toma ("corta", "otra vez", "¿está grabando?")? | Noul | Texto del segmento |
| ¿La toma termina con la idea completa? | Noul | Texto de la toma |
| ¿A y B son intentos de la misma parte? (solo zona gris) | Noul | Dos textos |
| Fluidez/naturalidad | Score (niveles descriptos) | Texto de la toma |
| Mejor toma del grupo | Choice, **2 veces con orden invertido** | Textos del grupo |
| ¿Cambio de tema entre A y B? | Noul | Dos segmentos consecutivos |
| ¿El segmento contiene una llamada a la acción? (CTA automático) | Noul | Texto del segmento |

### Reglas (por limitaciones documentadas de jev-1.13)
- Nada de aritmética, conteos, fechas ni comparación numérica en Jev: todo en código.
- State mínimo: solo lo que la pregunta necesita.
- Una llamada por cluster con todas las preguntas juntas (se evalúan en paralelo).
- Instrucciones literales y precisas; criterios alineados con la instrucción.
- Choice sesgado a la primera opción → preguntar con orden invertido y exigir coincidencia.

### Confidence gating
- Aplicar automático si: confianza ≥ `JEV_MIN_CONFIDENCE` **y** ambos órdenes del Choice coinciden.
- Si no: aplicar la mejor heurística y marcar `decisionConfidence` bajo → resaltado en la UI para revisión.
- Score final de toma = pesos en código × (features deterministas + scores de Jev). Pesos en config, no en prompts.

### Incertidumbres
- Soporte de español de Jev: no documentado. Medir contra benchmark antes de habilitarlo por defecto.
- Jev está en early access: mantener `heuristic` como default.

## Modelo de datos (`project.json`)

Definir en Pydantic (backend) y espejar en `packages/composition/src/types.ts`. Generar los tipos TS desde el JSON Schema de Pydantic para evitar desincronización.

```ts
interface Project {
  version: 1;
  preset: "reel_9x16" | "landscape_16x9";
  fps: number;
  sources: Source[];
  clips: Clip[];                 // ordered single video track
  audioTracks: AudioTrack[];
  subtitles: { style: SubtitleStyle; words: TimelineWord[] };
  overlays: Overlay[];
  colorGrade: ColorGrade;        // global; clips can override
}

interface Source {
  id: string;
  originalPath: string;
  mezzaninePath: string;
  proxyPath: string;
  displayColor: string;          // timeline color to show which source is used when
  loudnessLufs: number;
  colorStats: { meanLuma: number; meanR: number; meanG: number; meanB: number };
}

interface Clip {
  id: string;
  sourceId: string;
  inSec: number;
  outSec: number;
  speed: number;                 // 0.5 - 2.0
  volume: number;                // 0 - 2
  transitionIn: { type: "cut" | "punch_in" | "fade" | "slide"; durationFrames: number };
  takeGroupId?: string;
  alternativeTakeIds: string[];
  decisionConfidence?: number;
  colorOverride?: Partial<ColorGrade>;
  removed: boolean;              // soft delete, restorable
}

interface AudioTrack {
  id: string;
  kind: "voice" | "music" | "sfx";
  sourcePath?: string;           // music/sfx file
  volume: number;
  duckingEnabled: boolean;       // music ducks under voice (computed from VAD)
}

interface TimelineWord { text: string; startFrame: number; endFrame: number; clipId: string }

interface SubtitleStyle {
  preset: "karaoke_highlight" | "clean" | "bold_pop" | "minimal";
  fontSize: number;
  position: "bottom" | "center" | "top";
  highlightColor: string;
  maxWordsPerLine: number;
}

interface Overlay {
  id: string;
  templateId: "title" | "lower_third" | "cta" | "logo" | "progress_bar" | "image";
  startFrame: number;
  endFrame: number;
  props: Record<string, unknown>;
  autoGenerated: boolean;
}

interface ColorGrade {
  preset: "natural" | "warm" | "cool" | "bw";
  brightness: number;
  contrast: number;
  saturation: number;
  temperature: number;           // via SVG feColorMatrix
}
```

## Interfaz (3 pasos)

### 1. Cargar
- Drag & drop de videos; preset (Reel 9:16 / YouTube 16:9); idioma; guion opcional (textarea).
- Botón "Procesar" → progreso por etapa vía WebSocket.

### 2. Revisar y ajustar
- **Player** (`@remotion/player`) arriba + **panel lateral contextual**.
- **Timeline** abajo, pistas: Video · Subtítulos · Gráficos · Música.
  - Clips con el color de su archivo de origen + leyenda (qué archivo se usa cuándo).
  - Badge "N tomas" en clips con alternativas → clic para cambiar.
  - Borde amarillo si `decisionConfidence` < umbral.
  - Clips eliminados (silencios/fuera de toma) visibles atenuados y restaurables.
- **Interacciones permitidas:** seleccionar, cambiar toma, recortar ±0.1 s, borrar/restaurar, arrastrar overlays. Nada más.
- **Paneles:**

| Panel | Automático | Manual |
|---|---|---|
| Clip | — | Velocidad, volumen, recorte, toma |
| Transiciones | Punch-in / fade según tema | Tipo y duración por corte o preset global |
| Subtítulos | Generados, karaoke | Preset de estilo, tamaño, posición, edición de texto |
| Audio | -14 LUFS, ducking | Volumen por pista y por clip, cargar música |
| Color | Igualado entre fuentes | Preset + 4 sliders, "aplicar a todos" |
| Gráficos | CTA automático (opcional, Jev) | Plantillas con props editables |

- Undo/redo global (zustand + zundo). Autosave del `project.json` con debounce.

### 3. Exportar
- Resolución y calidad → render Remotion → pasada final FFmpeg (loudnorm) → "Abrir carpeta".
- Opcionales: SRT, FCPXML (OTIO).

## Fases y criterios de aceptación

### Fase 0 — Setup
- Monorepo (uv + pnpm), lint, typecheck, tests corriendo, `.env.example`.
- Script que verifica dependencias: FFmpeg, ffprobe, Node, CUDA (opcional).
- **Aceptación:** `uv run autocut doctor` reporta estado de cada dependencia.

### Fase 1 — Ingest y transcripción
- Ingest (mezzanine, proxy, WAV) + ambos transcriptores.
- **Aceptación:** mismo audio con `local` y `openai` produce `Transcript` válido con el mismo esquema; test que compara ambas salidas (WER aproximado, conteo de palabras con timestamps).

### Fase 2 — Silencios y render mínimo
- VAD, segmentación, corte de silencios, draft `project.json`.
- Composición Remotion mínima: clips en secuencia + crossfade de audio.
- **Aceptación:** CLI `autocut render <project>` produce MP4 sin silencios, sin clicks en cortes, A/V sincronizado. **Medir velocidad de render** (si es inaceptable, evaluar plan B: Remotion solo preview + render FFmpeg).

### Fase 3 — Tomas (heurística)
- Clustering + features + `HeuristicEngine`.
- Benchmark: 20–30 clusters etiquetados a mano (`backend/tests/fixtures/takes_benchmark.json`).
- **Aceptación:** script de evaluación reporta % de acierto en elección de toma.

### Fase 4 — Jev
- `JevEngine` con confidence gating y Choice en doble orden.
- **Aceptación:** sobre el benchmark, reporte de acierto vs % de decisiones automáticas; comparación contra heurística; costo en tokens por video.

### Fase 5 — Subtítulos y transiciones
- Remap de palabras al timeline, presets de estilo, transiciones por tema.
- **Aceptación:** subtítulos sincronizados después de cambiar velocidad de un clip y de cambiar de toma.

### Fase 6 — UI básica
- Pasos 1 y 3 + paso 2 con player y timeline de solo lectura (colores por fuente, badges).
- **Aceptación:** flujo completo cargar → procesar → ver → exportar sin usar la CLI.

### Fase 7 — Edición
- Cambio de toma, recorte, borrar/restaurar, transiciones, edición de subtítulos, undo/redo.

### Fase 8 — Audio y color
- Volúmenes por pista/clip, ducking, normalización, igualado de color, presets y sliders.

### Fase 9 — Gráficos
- Plantillas de overlays + CTA automático.

### Fase 10 (opcional) — Empaquetado
- Electron con backend Python como sidecar.

## Riesgos y puntos a verificar

- [ ] GPU disponible → define modelo Whisper y viabilidad de render rápido.
- [ ] Velocidad de render de Remotion en esta PC (Fase 2).
- [ ] `playbackRate` en Remotion: ¿preserva el tono de voz?
- [ ] API de volumen por frame en Remotion para ducking.
- [ ] Límite de tamaño de archivo de la API de transcripción de OpenAI.
- [ ] Nombre de variable de entorno y firmas de `Choice`/`Score` en el SDK de TypeSafe.
- [ ] Calidad de Jev en español.
- [ ] Setup CUDA/cuDNN para faster-whisper en Windows.
- [ ] Reproducción de proxies en el navegador (servir con range requests).
