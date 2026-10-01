<div align="center">

<img src="docs/img/logo.png" alt="Mens Campus Assistant" width="104" height="104" />

# Mens Campus Assistant

**A local-first campus Q&A workbench**  
Electron desktop shell + Vue 3 interface + FastAPI backend, able to run offline on a single machine

<a href="https://github.com/HuanMoovo/campus-agent/actions/workflows/build-desktop.yml"><img src="https://github.com/HuanMoovo/campus-agent/actions/workflows/build-desktop.yml/badge.svg" alt="Desktop build status" /></a>
<img src="https://img.shields.io/badge/version-1.2.0-0e7c74" alt="Version 1.2.0" />
<img src="https://img.shields.io/badge/license-Apache--2.0-0e7c74" alt="Apache-2.0" />
<img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20PWA-0e7c74" alt="Platforms" />

**中文** · [English](README.en.md) · [日本語](README.ja.md)

[Download for Windows](https://github.com/HuanMoovo/campus-agent/releases/latest) ·
[Project page](https://huanmoovo.github.io/campus-agent/) ·
[Platform support](PLATFORMS.md) ·
[Verification record](VERIFICATION.md) ·
[Licence](LICENSE)

</div>

---

## What this is

Mens puts campus policy Q&A, a local knowledge base and campus data services into one desktop
application, and keeps documents, data and keys on your own machine by default. It is suited to
trying the idea out, evaluating it and building on it; deploying it as a campus production
system still needs single sign-on, auditing and data-compliance work (see
[Known limitations](#known-limitations)).

- **Local first** — knowledge base, conversations, configuration and keys live on your machine (SQLite + a user data directory); no external database is required and Q&A works without any network access.
- **Stated as it is** — campus endpoints that are not configured return clearly labelled demo data, and when no model is available the app falls back to quoting knowledge-base passages instead of inventing an answer.
- **Optional web search** — off by default; an administrator enables it in Settings (keyless Bing, or Tavily / Bocha) and it can be toggled per message. Answers cite source links and the search time.
- **Cross-platform** — the Windows installer works out of the box; macOS (Intel / Apple silicon) and Linux (AppImage / deb) are built by CI; phones and tablets use the installable web app (PWA).
- **Open source** — Apache License 2.0 ([`LICENSE`](LICENSE) and [`NOTICE`](NOTICE)); the third-party inventory is in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).

## Features

### Chat

| Feature | Notes |
| --- | --- |
| Streaming answers | Text arrives character by character and the interface updates as it is generated |
| Stop generation | Interrupt at any time; what was produced is saved with a stopped marker, so history never pretends an answer was finished |
| Multi-turn conversations | Context is kept, and conversations can be restored after a refresh or restart |
| Source passages | Answers list the knowledge-base passages they used, so the evidence can be checked |
| Conversation isolation | Desktop builds are isolated per machine, web builds per browser; individual conversations can be deleted or all cleared |
| Honest labelling | Demo data, degraded retrieval and web sources are all labelled in the interface |

### Knowledge base and retrieval

| Feature | Notes |
| --- | --- |
| Document formats | PDF, Markdown, TXT and Word (.docx), up to 5 MB per file |
| Document management | Upload, replace and delete; the document database is the source of truth |
| Keyword search | The default, with no extra dependencies — it works with the installer as shipped |
| Vector retrieval (optional) | Enabling RAG switches to semantic retrieval with BGE-M3 + Chroma; when vectors are unavailable the app falls back to keyword search and says so |
| Index consistency | The index records a version hash, so deleted or updated documents never come back as stale passages |
| Demo material | The first SQLite start loads three clearly labelled demo documents; PostgreSQL loads none |

### Web search (optional, off by default)

| Feature | Notes |
| --- | --- |
| Switch granularity | An administrator master switch plus a per-message toggle; with it off the app performs no web retrieval at all |
| Providers | `auto` (default), Bing (keyless, reachable from mainland China), Tavily or Bocha (API key required) |
| Result handling | The first one to three pages are fetched (≤ 2000 characters each, ≤ 400 KB per response) and numbered together with knowledge-base passages before being added to the prompt |
| Citations | Answers list the linked sources and the search time |
| Outbound limits | HTTPS only, pinned to a validated public address (SNI preserved against DNS rebinding), no redirects, size and timeout caps |

### Campus services and repair requests

| Feature | Notes |
| --- | --- |
| Campus endpoints | Nine configurable HTTPS JSON endpoints: grades, timetable, credits, free classrooms, repairs, announcements, library, canteens, shuttle |
| Endpoint configuration | Result paths (JSON value paths) and Bearer tokens; the address must be HTTPS |
| Repair requests | Submitted explicitly by the user; POSTed to the school once an endpoint is configured, otherwise kept locally and labelled demo |
| Local records | Submitted requests are listed newest first so the result can be confirmed |
| Demo data | Unconfigured endpoints return clearly labelled demo data instead of pretending a school system is connected |

### Model access

| Mode | Notes |
| --- | --- |
| Cloud APIs | Qwen3 / DeepSeek with their own API keys and HTTPS endpoints; keys are stored locally and never echoed back |
| Automatic routing | Analytical or comparative questions prefer a configured DeepSeek, other questions prefer Qwen3; a model can also be chosen explicitly |
| Local models | A built-in catalogue (Qwen3 0.6B / 1.7B, DeepSeek R1 1.5B) with Ollama, Hugging Face or HF Mirror as download sources |
| Download reliability | Resumable downloads, pinned versions, SHA-256 verification and import retries, with progress and cancel |
| Degradation | Without a key or when a model is unavailable, the app plans with rules and quotes knowledge-base passages, labelled as such |

### Data, backup and updates

| Feature | Notes |
| --- | --- |
| Backup export | One click exports a zip with the knowledge base, conversations, model and campus-endpoint settings; SQLite is snapshotted consistently with `VACUUM INTO` and a SHA-256 manifest of every file is included |
| Backup import | Verified and restored, so a new machine or a reinstall can be brought back completely (the zip contains key files — keep it safe) |
| Update check | Once an administrator sets an HTTPS manifest, Settings can check for a newer version and open the download page; leaving it empty keeps the feature entirely offline |
| Version consistency | The build script refuses to package unless the desktop, frontend and backend versions agree |

### Desktop experience

| Feature | Notes |
| --- | --- |
| Works out of the box | The installer bundles the Python runtime — no separate Python, Node or database install |
| Window memory | Window size and position are remembered (coordinates that fall outside the screens are discarded) |
| Logs and data folder | Settings can show the backend log and open the data folder |
| Appearance | Light, dark or follow the system, plus a custom accent colour; the sidebar and mobile layouts are adapted separately |
| Runtime handshake | The frozen backend starts on a random port with a one-time token, and the shell validates the startup envelope before loading the interface |

### Plugins and operations

| Feature | Notes |
| --- | --- |
| Built-in plugins | OpenAlex scholarly search, Crossref lookups and Baidu Baike links (installed on demand; installation only registers the configuration) |
| Plugin manifests | HTTPS JSON manifests are supported; hosts must be listed in `PLUGIN_ALLOWED_HOSTS` |
| Invocation | An administrator invokes them explicitly; plugins may only return JSON, and ordinary Q&A never sends messages to external plugins |
| Outbound limits | The same HTTPS / pinned-IP / no-redirect / capped policy as web search |

## Platform support

| Platform | Status | Artefacts and data directory |
| --- | --- | --- |
| Windows 10/11 x64 | **Built and verified on a real machine** | `Mens-Setup-1.2.0-x64.exe` (NSIS, per-user install into `%LOCALAPPDATA%\Programs\Mens`), data in `%APPDATA%\CampusAgent` |
| macOS 12+ (Intel) | Built by CI, not verified on hardware | `Mens-1.2.0-x64.dmg` / `.zip`; unsigned and not notarised, so the first launch needs a right-click Open |
| macOS 12+ (Apple silicon) | Built by CI, not verified on hardware | `Mens-1.2.0-arm64.dmg` / `.zip`; data in `~/Library/Application Support/CampusAgent` |
| Linux x64 | Built by CI, not verified on hardware | `Mens-1.2.0-x86_64.AppImage` (no install needed) and `Mens-1.2.0-amd64.deb`; data in `~/.config/CampusAgent` |
| Android / iOS | No native app | Use the installable web app (PWA): open the deployed site in a browser and add it to the home screen; inference happens on the server |

> "Verified" means the build was installed, launched and checked on that system; "built by CI"
> means GitHub Actions produces the artefact but it has not been run on real hardware yet.
> See [PLATFORMS.md](PLATFORMS.md) for the matrix, build commands and the reasoning, and
> [VERIFICATION.md](VERIFICATION.md) for results and scope.

### Release assets (v1.2.0)

| Asset | Size | Notes |
| --- | --- | --- |
| `Mens-Setup-1.2.0-x64.exe` (+ `.blockmap`) | 126,402,135 B | Windows installer — this is the file used for the local install check |
| `Mens-1.2.0-x64.dmg` / `Mens-1.2.0-x64.zip` | ≈ 158 MB | macOS Intel |
| `Mens-1.2.0-arm64.dmg` / `Mens-1.2.0-arm64.zip` | ≈ 151 MB | macOS Apple silicon |
| `Mens-1.2.0-x86_64.AppImage` / `Mens-1.2.0-amd64.deb` | 191 MB / 153 MB | Linux |

The installer also carries `LICENSE`, `NOTICE` and `THIRD-PARTY-NOTICES.md` (they end up in
`resources/` after installation).

## Quick start

### 1. Install the Windows desktop app

Download `Mens-Setup-1.2.0-x64.exe` from the
[latest release](https://github.com/HuanMoovo/campus-agent/releases/latest), run it (per-user
install, no administrator rights needed) and launch Mens from the Start menu or the desktop.
Add a model API key in Settings (or pick a local Ollama model) and start asking questions.

### 2. Build the desktop app from source

One script covers all three platforms and writes into `release/`:

```bash
# Current platform (architecture detected automatically)
python scripts/build_desktop.py

# Explicit targets
python scripts/build_desktop.py --os mac   --arch arm64
python scripts/build_desktop.py --os linux --arch x64

# Useful switches
#   --skip-install   reuse installed dependencies (fast rebuild)
#   --directory      produce only the unpacked application directory
#   --full-rag       bundle the vector-retrieval dependencies (larger download)
```

The script runs the backend, frontend and desktop test suites, freezes the backend and then
packages with electron-builder; if any step fails it stops without producing an installer.

### 3. Run from source (web development)

On Windows you can double-click `install.cmd` (installs dependencies, checks LangGraph, runs the
backend tests, builds the frontend), then run `start-backend.cmd` and `start-frontend.cmd` and
open <http://localhost:5173>.

Manually:

```powershell
# Backend (terminal 1)
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env          # replace ADMIN_TOKEN with a strong random value
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Frontend (terminal 2)
cd frontend
npm install
npm run dev
```

Interface at <http://localhost:5173>, API documentation at <http://localhost:8000/docs>. Enter the
`ADMIN_TOKEN` from `backend/.env` in Settings to manage documents and plugins (the token is kept
in the browser session only).

### 4. Docker deployment (server, PWA)

```bash
cp .env.example .env      # set POSTGRES_PASSWORD and ADMIN_TOKEN
docker compose up -d --build
docker compose logs -f backend
```

Open <http://localhost:8080>; the stack is bound to `127.0.0.1:8080` only. Then open the address
in a phone browser and add it to the home screen for the installable web app (PWA).

The stack is PostgreSQL + backend + Nginx:

| Service | Image | Notes |
| --- | --- | --- |
| `database` | `postgres:16-alpine` | Health-checked before the backend starts; data in the `postgres_data` volume |
| `backend` | `python:3.11-slim` | Runs as a non-root user; data in `backend_data`, model cache in `model_cache`; health check on `/api/health` |
| `frontend` | `nginx:alpine` | Serves the built Vue app and proxies `/api/` to the backend; uploads capped at 6 MB |

Notes:

- All variables in the root `.env` are passed through, so web search, the update manifest and the plugin allow-list can be configured the same way as in a local install (see the configuration reference).
- `ENABLE_RAG=true` builds the vector-retrieval dependencies into the image (`INSTALL_VECTOR` build argument) and needs a rebuild.
- Data lives in named volumes, so `docker compose down` keeps it and `docker compose down -v` removes it. Back up the database before upgrading.
- The compose stack is meant for a single machine or a trusted network; exposing it to the internet still requires HTTPS, authentication in front and a rate limit.
- **Verified locally** (Docker Desktop 29.1.3): both images build; the database, backend and frontend services all start, the first two passing their health checks; `http://localhost:8080/` returns 200 and `/api/health` returns `{"status":"ok",…}`; the backend confirms a **PostgreSQL 16.15** connection inside the container; and a real browser loads the workbench with no failed requests and no page errors.

### 5. Phone / tablet (PWA) without Docker

Deploy the backend anywhere reachable (see the server deployment notes above), then open the site
in a phone browser and add it to the home screen for a full-screen, own-icon experience.

## Configuration reference

### backend/.env

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///backend/data/campus.db` | PostgreSQL also works: `postgresql+psycopg://user:pass@host:5432/campus_agent` (URL-encode reserved characters) |
| `ADMIN_TOKEN` | empty | Management token; Settings uses it for documents and plugins — replace it before deploying |
| `QWEN_API_KEY` / `DEEPSEEK_API_KEY` | empty | Cloud model keys (they can also be saved in Settings) |
| `QWEN_BASE_URL` / `DEEPSEEK_BASE_URL` | official HTTPS endpoints | Must be HTTPS |
| `QWEN_MODEL` / `DEEPSEEK_MODEL` | `qwen3-235b-a22b` / `deepseek-chat` | Set models your account can actually use |
| `ENABLE_RAG` | `false` | Enables BGE-M3 + Chroma vector retrieval (install `requirements-ai.txt` first) |
| `BGE_MODEL_NAME` | `BAAI/bge-m3` | May point at a model already downloaded locally |
| `PLUGIN_ALLOWED_HOSTS` | empty | Host allow-list for plugins (comma separated) |
| `CORS_ORIGINS` | `http://localhost:5173` | Origins allowed for the web app |
| `WEB_SEARCH_ENABLED` | `false` | Web search master switch |
| `WEB_SEARCH_PROVIDER` | `auto` | `auto` / `bing` (keyless) / `tavily` / `bocha` |
| `WEB_SEARCH_API_KEY` | empty | Key for Tavily or Bocha |
| `WEB_SEARCH_MAX_RESULTS` | `5` | Results per search |
| `WEB_SEARCH_FETCH_PAGES` | `2` | Pages whose text is fetched (maximum 3) |
| `UPDATE_MANIFEST_URL` | empty | Optional HTTPS update manifest, e.g. `{"version":"1.2.0","url":"https://…","notes":"…"}`; empty means no update check at all |

The desktop shell injects `CAMPUS_DESKTOP_MODE`, `CAMPUS_DESKTOP_TOKEN`, `CAMPUS_DESKTOP_NONCE`,
`CAMPUS_DATA_DIR`, `CAMPUS_FRONTEND_DIR` and `CAMPUS_CONFIG_FILE` (nothing to fill in; only
absolute paths are accepted).

### Models and vector retrieval

- Save a key in Settings and press "Test saved configuration" to check connectivity; on Windows new keys are encrypted with DPAPI and never echoed back.
- Local models: install and start Ollama, then pick a model and a download source in Settings; GGUF files are downloaded at pinned versions, verified with SHA-256 and imported into Ollama. Model files are not bundled with the installer.
- Enabling vector retrieval:

  ```powershell
  cd backend
  .venv\Scripts\python -m pip install -r requirements-ai.txt
  # set ENABLE_RAG=true in .env, restart the backend, then press "Rebuild index" on the knowledge page
  ```

  The first load of `BAAI/bge-m3` downloads the model; if vectors cannot be initialised the documents stay and retrieval falls back to keywords.

### Campus data endpoints

Field layouts, value paths and examples for the nine endpoints are in
[CAMPUS-DATA.md](CAMPUS-DATA.md). In short:

- HTTPS JSON only; Bearer tokens and result paths are supported.
- Unconfigured endpoints return clearly labelled demo data; the project ships **no** real school endpoint, identity provider or model key.
- A production deployment needs interfaces the school has authorised and its own acceptance testing; multi-user setups additionally need single sign-on, per-user student IDs, access auditing and rate limiting (see [CAMPUS-DATA.md](CAMPUS-DATA.md) and [ARCHITECTURE.md](ARCHITECTURE.md)).

## Architecture and security boundaries

### Stack

- **Frontend**: Vue 3 + TypeScript + Vite + Element Plus + Pinia; the build splits vendor chunks (the main bundle is about 71 KB).
- **Backend**: FastAPI + SQLAlchemy + LangGraph; default SQLite single-file database, PostgreSQL optional.
- **Desktop**: an Electron shell around a PyInstaller-frozen CPython (the installer carries the runtime).
- **Installable web app**: manifest, offline shell (service worker) and iOS safe-area handling.

### Security design

- **Local first**: the desktop backend listens only on a random port on `127.0.0.1` with a one-time token per start; the shell injects an extra request header and tightens Electron (`nodeIntegration:false`, `contextIsolation:true`, `sandbox:true`, `webSecurity:true`, `webviewTag` disabled), so outside pages cannot reach those endpoints.
- **Outbound discipline** (plugins, web search and update checks share it): HTTPS on 443 only; the connection is pinned to a resolved and validated public address (SNI preserved against DNS rebinding); redirects are refused; responses have size and timeout caps; system proxy environment variables are ignored (`trust_env=False`); anything resolving to a private address is rejected outright.
- **Key storage**: Windows uses DPAPI; macOS and Linux have no equivalent system facility, so keys go into a plain file with `0600` permissions readable by the same user only — stated plainly in [PLATFORMS.md](PLATFORMS.md).
- **Backups**: the exported zip contains key files, so keep it safe; imports verify the SHA-256 manifest first.
- **Nothing is faked**: demo data, degraded retrieval and web sources are always labelled.

### Repository layout

```text
campus-agent/
├─ backend/         FastAPI backend (app/, tests/, requirements*.txt)
├─ frontend/        Vue 3 frontend (src/, tests/, dist/ build output)
├─ desktop/         Electron shell (main.cjs, preload.cjs, lib/, assets/ icons)
├─ scripts/         Build and packaging (build_desktop.py, install.py, create_icon.py, …)
├─ docs/            Project page (GitHub Pages, zh / en / ja)
├─ assets/          Brand sources
├─ examples/        Plugin manifest examples
├─ compose.yaml     PostgreSQL + backend + Nginx for Docker deployments
├─ PLATFORMS.md     Platform matrix and build commands
├─ DESKTOP.md       Desktop notes
├─ ARCHITECTURE.md  Architecture and main interfaces
├─ CAMPUS-DATA.md   Campus endpoint formats
├─ VERIFICATION.md  Verification record (sizes, SHA-256, scope)
└─ LICENSE / NOTICE / THIRD-PARTY-NOTICES.md
```

## Tests and verification

```powershell
# Backend (260 cases, 65 subtests)
cd backend
.venv\Scripts\python -m pytest -q

# Frontend (13 unit tests) and production build
cd ..\frontend
npm test
npm run build

# Desktop shell (8 tests)
cd ..\desktop
npm test

# Everything above at once (Windows)
.\verify.ps1
```

Without network access, two logic-only suites run on the system Python (no framework, network or
database dependencies):

```powershell
cd backend
python -m unittest discover -s tests -p test_core_unit.py -v
python -m unittest discover -s tests -p test_agent_unit.py -v
```

These cover core validation and decision logic but cannot replace real FastAPI, LangGraph, Chroma,
model-service or browser testing — and no test guarantees the absence of bugs. The completed scope,
installer size and SHA-256 are in [VERIFICATION.md](VERIFICATION.md).

## Screenshots

| Chat (with web sources) | Settings (web search) |
| --- | --- |
| <img src="docs/img/chat-web-search.png" alt="Chat with web search results and source links" /> | <img src="docs/img/settings-web-search.png" alt="Settings for web search" /> |

| Campus services (repair request and local records) |
| --- |
| <img src="docs/img/campus-services.png" alt="Campus services with repair request and local records" /> |

## Known limitations

- **macOS / Linux artefacts are not verified on hardware** — they are produced by CI and have not been installed and run on a real machine.
- **Unsigned and not notarised** — there is no publisher certificate, so the first launch on Windows or macOS may show a system prompt; signing should be set up before wider distribution.
- **Campus endpoints and single sign-on** — no real school endpoint, identity provider or model key ships with the project; a production deployment needs interfaces the school has authorised, plus acceptance testing.
- **Cloud models and web search** — each needs its own API key (the Bing channel is keyless); the availability of the search backend depends on your network environment.
- **Native Android / iOS apps** — out of scope; see [PLATFORMS.md](PLATFORMS.md) for why (the Python backend cannot ship on mobile stores).
- **One-click updates** — the update check only reports a version difference and opens the download page; it does not download or install silently.
- **Multi-user deployments** — demo conversations currently use a random session ID as their access credential, which is fine for local development only; production needs user ownership checks, operation auditing, rate limiting, HTTPS, database migrations and a backup strategy.

## Licence

Released under the **Apache License 2.0** ([`LICENSE`](LICENSE)); copyright and attribution notes
are in [`NOTICE`](NOTICE).

- **You may** use, modify and redistribute it freely, including commercially, for in-house campus deployment and in closed-source modified versions.
- **You must** keep the copyright, licence and NOTICE notices and mark the files you changed; the licence grants no right to use the project name or trademarks.
- **No warranty** — the software is provided as is, without any express or implied warranty.
- **Third-party components** — the installer bundles Electron, Chromium, CPython, PyInstaller, FastAPI, Vue, Element Plus and others, each under its own licence; the list is in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).

## Documentation

| Document | Contents |
| --- | --- |
| [Project page](https://huanmoovo.github.io/campus-agent/) | Illustrated introduction in Chinese, English and Japanese, with the platform matrix and limitations |
| [PLATFORMS.md](PLATFORMS.md) | Platform matrix, build commands, macOS / Linux key-storage differences, mobile rationale |
| [DESKTOP.md](DESKTOP.md) | Desktop runtime, data directories, IPC and security settings |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architecture, module responsibilities and main interfaces |
| [CAMPUS-DATA.md](CAMPUS-DATA.md) | Field layouts and integration formats for the nine campus endpoints |
| [VERIFICATION.md](VERIFICATION.md) | How each batch was verified, installer sizes and SHA-256, unverified areas |
| [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) | Third-party components and their licences |
