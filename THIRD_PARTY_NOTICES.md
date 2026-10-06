# Third-party notices

PowerEditor is licensed under the terms in [LICENSE](LICENSE). The components below are not covered by that license. Each one keeps its own license.

The list has three groups: what the Windows installer ships, what the app downloads at first run, and optional extras a developer can install. Versions are the ones pinned in this repository (`pnpm-lock.yaml`, `backend/uv.lock`, `backend/powereditor/runtime/manifest.py`) when this file was written.

**How each license was checked.** For npm packages: the `license` field and license file of the installed package in `node_modules`. For Python packages: the `License-Expression` or license classifier in the installed distribution's metadata (`.venv`). For native libraries: the license string the library itself reports (`ffmpeg -L`, `avcodec_license()`) and its build configuration. For downloads and models: the project's own page or repository, cited per entry.

## Shipped in the installer

### Desktop shell

| Component | Version | License                                                                                                                                           | Source                                 |
| --------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| Electron  | 44.5.1  | MIT; Electron bundles Chromium and other components; their licenses ship in the app folder as `LICENSE.electron.txt` and `LICENSES.chromium.html` | <https://github.com/electron/electron> |

### Web app and video composition

| Component                                                                                               | Version | License                      | Source                              |
| ------------------------------------------------------------------------------------------------------- | ------- | ---------------------------- | ----------------------------------- |
| Remotion (`remotion`, `@remotion/player`, `@remotion/renderer`, `@remotion/bundler`, `@remotion/fonts`) | 4.0.533 | Remotion License (see below) | <https://www.remotion.dev/license>  |
| React, React DOM                                                                                        | 19.3.0  | MIT                          | <https://react.dev>                 |
| Zustand                                                                                                 | 5.0.15  | MIT                          | <https://github.com/pmndrs/zustand> |
| zundo                                                                                                   | 2.3.0   | MIT                          | <https://github.com/charkour/zundo> |
| Inter (via `@fontsource/inter`)                                                                         | 5.3.0   | SIL Open Font License 1.1    | <https://github.com/rsms/inter>     |
| IBM Plex Sans and IBM Plex Mono (via `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono`)          | 5.3.0   | SIL Open Font License 1.1    | <https://github.com/IBM/plex>       |

**Remotion License.** Remotion is free for individuals, for-profit organizations with up to 3 employees, non-profit organizations, and for evaluation. For-profit organizations with more than 3 employees need a Remotion company license to use it, and that applies to their use of PowerEditor too. Read the exact terms at <https://www.remotion.dev/license> (the same text ships as `LICENSE.md` in each Remotion package).

**Remotion's compositor brings its own FFmpeg.** `@remotion/compositor-win32-x64-msvc` 4.0.533, which the installer includes so the renderer can run, contains `ffmpeg.exe`, `ffprobe.exe` and FFmpeg shared libraries. That FFmpeg build reports itself as **GPL version 2 or later** (`ffmpeg -L`) and is configured with `--enable-gpl --enable-libx264`. It is used only inside Remotion's render step. FFmpeg source: <https://ffmpeg.org/download.html>.

### Engine (Python backend)

| Component                                                             | Version                   | License                                                                                       | Source                                                               |
| --------------------------------------------------------------------- | ------------------------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Python runtime                                                        | 3.12                      | Python Software Foundation License 2.0                                                        | <https://www.python.org>                                             |
| faster-whisper                                                        | 1.2.1                     | MIT                                                                                           | <https://github.com/SYSTRAN/faster-whisper>                          |
| CTranslate2                                                           | 4.8.2                     | MIT                                                                                           | <https://github.com/OpenNMT/CTranslate2>                             |
| Intel OpenMP runtime (`libiomp5md.dll`, inside the CTranslate2 wheel) | as shipped by CTranslate2 | Not verified: the CTranslate2 wheel ships no license file for it (Intel OpenMP runtime)       | <https://github.com/OpenNMT/CTranslate2>                             |
| Silero VAD model (`silero_vad_v6.onnx`, inside faster-whisper)        | v6                        | MIT                                                                                           | <https://github.com/snakers4/silero-vad>                             |
| ONNX Runtime                                                          | 1.30.0                    | MIT                                                                                           | <https://github.com/microsoft/onnxruntime>                           |
| PyAV                                                                  | 19.0.1                    | BSD-3-Clause (bindings); see the FFmpeg note below                                            | <https://github.com/PyAV-Org/PyAV>                                   |
| NumPy                                                                 | 2.5.3                     | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; the wheel bundles OpenBLAS (BSD-3-Clause) | <https://numpy.org>                                                  |
| FastAPI                                                               | 0.142.2                   | MIT                                                                                           | <https://github.com/fastapi/fastapi>                                 |
| Starlette                                                             | 1.7.0                     | BSD-3-Clause                                                                                  | <https://github.com/encode/starlette>                                |
| Uvicorn                                                               | 0.54.0                    | BSD-3-Clause                                                                                  | <https://github.com/encode/uvicorn>                                  |
| Pydantic, pydantic-core, pydantic-settings                            | 2.13.5, 2.46.5, 2.15.0    | MIT                                                                                           | <https://github.com/pydantic/pydantic>                               |
| httpx                                                                 | 0.28.1                    | BSD-3-Clause                                                                                  | <https://github.com/encode/httpx>                                    |
| keyring                                                               | 25.7.0                    | MIT                                                                                           | <https://github.com/jaraco/keyring>                                  |
| platformdirs                                                          | 4.12.3                    | MIT                                                                                           | <https://github.com/tox-dev/platformdirs>                            |
| RapidFuzz                                                             | 3.14.6                    | MIT                                                                                           | <https://github.com/rapidfuzz/RapidFuzz>                             |
| Typer                                                                 | 0.27.2                    | MIT                                                                                           | <https://github.com/fastapi/typer>                                   |
| Rich                                                                  | 15.0.0                    | MIT                                                                                           | <https://github.com/Textualize/rich>                                 |
| jsonschema                                                            | 4.26.0                    | MIT                                                                                           | <https://github.com/python-jsonschema/jsonschema>                    |
| python-multipart                                                      | 0.0.32                    | Apache-2.0                                                                                    | <https://github.com/Kludex/python-multipart>                         |
| websockets                                                            | 17.2                      | BSD-3-Clause                                                                                  | <https://github.com/python-websockets/websockets>                    |
| huggingface_hub                                                       | 1.33.0                    | Apache-2.0                                                                                    | <https://github.com/huggingface/huggingface_hub>                     |
| tokenizers                                                            | 0.23.2                    | Apache-2.0                                                                                    | <https://github.com/huggingface/tokenizers>                          |
| Microsoft Visual C++ runtime (`msvcp140.dll`)                         | as shipped by the wheels  | Microsoft Visual C++ Redistributable license                                                  | <https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist> |

The backend is frozen with PyInstaller, whose bootloader is GPL-2.0-or-later with an exception that allows distributing the bundled program under its own terms (<https://pyinstaller.org/en/stable/license.html>).

**FFmpeg inside PyAV.** The PyAV 19.0.1 wheel bundles FFmpeg 9.0.2 shared libraries (`av.libs/`). Those libraries report **LGPL version 3 or later** (`avcodec_license()`, built with `--enable-version3`). The same folder also contains `libx264` and `libx265` DLLs, and both x264 and x265 are licensed **GPL-2.0-or-later**. The frozen backend currently includes all of these files. FFmpeg source: <https://ffmpeg.org/download.html>; x264: <https://www.videolan.org/developers/x264.html>; x265: <https://bitbucket.org/multicoreware/x265_git>.

## Downloaded at first run

These are not in the installer. The app downloads pinned versions, checks their SHA-256 and keeps each one's license file next to it in `<data dir>/bin/`.

| Component                                                                                      | Version                                  | License                                                                                                                           | Source                                                                                     |
| ---------------------------------------------------------------------------------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| FFmpeg, BtbN `win64-lgpl` build                                                                | 8.1.3 (autobuild 2026-09-30)             | LGPL-3.0-or-later: BtbN's LGPL variant configures FFmpeg with `--enable-version3` and ships `COPYING.LGPLv3` as its `LICENSE.txt` | <https://github.com/BtbN/FFmpeg-Builds>                                                    |
| OpenH264 (compiled into that FFmpeg build)                                                     | as built by BtbN                         | BSD-2-Clause                                                                                                                      | <https://github.com/cisco/openh264>                                                        |
| Node.js (Windows x64)                                                                          | 24.21.0                                  | MIT; Node bundles third-party components listed in its `LICENSE` file, which the app keeps                                        | <https://nodejs.org>                                                                       |
| Chrome Headless Shell (installed by Remotion for rendering)                                    | 149.0.7790.0 (Remotion's tested version) | Chromium is BSD-3-Clause and bundles third-party components under their own licenses                                              | <https://chromium.googlesource.com/chromium/src/+/HEAD/LICENSE>                            |
| Whisper model weights, CTranslate2 conversion (`Systran/faster-whisper-*`, `small` by default) | per model                                | MIT (model card on Hugging Face; the original OpenAI Whisper weights are MIT too)                                                 | <https://huggingface.co/Systran/faster-whisper-small>, <https://github.com/openai/whisper> |

**OpenH264 and patents.** BtbN builds OpenH264 from Cisco's source (`scripts.d/50-openh264.sh` clones `cisco/openh264` for every variant). Cisco pays the MPEG LA H.264 royalties only for the binary module Cisco itself distributes; for builds compiled from source, the OpenH264 FAQ (<https://www.openh264.org/faq.html>) says whoever distributes the product is responsible. The copyright license is BSD-2-Clause either way. The installer does not contain this build; the app downloads it from BtbN's GitHub releases at first run.

## Optional extras (not in the installer)

A developer can install these with `uv sync --extra <name>`. The frozen build excludes them.

| Extra        | Component                                     | License                           | Source                                                        |
| ------------ | --------------------------------------------- | --------------------------------- | ------------------------------------------------------------- |
| `vision`     | OpenCV (`opencv-python-headless` < 5)         | Apache-2.0 (OpenCV 4.5 and later) | <https://github.com/opencv/opencv-python>                     |
| `embeddings` | sentence-transformers                         | Apache-2.0                        | <https://github.com/huggingface/sentence-transformers>        |
| `embeddings` | PyTorch (dependency of sentence-transformers) | BSD-3-Clause                      | <https://github.com/pytorch/pytorch>                          |
| `nle`        | OpenTimelineIO                                | Apache-2.0                        | <https://github.com/AcademySoftwareFoundation/OpenTimelineIO> |
| `nle`        | otio-fcpx-xml-adapter                         | Apache-2.0                        | <https://github.com/OpenTimelineIO/otio-fcpx-xml-adapter>     |

These extras are not installed in the development environment this file was checked against, so their licenses come from each project's repository rather than installed metadata.

## Design references

PowerEditor's overlay and caption looks, export quality presets and render concurrency took ideas from [HyperFrames](https://github.com/heygen-com/hyperframes) (Apache-2.0). No HyperFrames code was copied.
