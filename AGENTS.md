# Repository Guidelines

## Project Structure & Module Organization
- `quarkdav/` holds the application code: `main.py` is the entry point, `config.py` centralizes settings, `webdav/` contains the aiohttp handlers, `quark_client/` wraps Quark storage operations, and `cache/db.py` manages the SQLite index.
- `cache/` (at the repo root) is populated at runtime for `index.db` and attachment storage; keep it disposable and out of version control.
- `requirements.txt` lists runtime dependencies, `Dockerfile` mirrors production deployment, and `plan.md` documents architectural context worth consulting before large refactors.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` creates an isolated Python environment.
- `pip install -r requirements.txt` installs server dependencies.
- `python -m quarkdav.main` launches the WebDAV service using values from `.env` or the environment.
- `docker build -t quarkdav .` followed by `docker run -p 5212:5212 -v $(pwd)/cache:/app/cache --env-file .env quarkdav` reproduces the container workflow.
- `cadaver http://localhost:5212/` (or another WebDAV client) exercises PROPFIND/PUT/GET flows during development.

## Coding Style & Naming Conventions
- Follow PEP 8/Black defaults: 4-space indents and focused 88-character lines.
- Modules and files use `snake_case`; classes use `PascalCase`; functions, methods, and variables stay in `snake_case`.
- Preserve type hints and dataclasses as seen in `quarkdav/cache/db.py`, and prefer `loguru.logger` for structured logging.
- Document new configuration keys in `.env` samples so settings stay discoverable.

## Testing Guidelines
- Automated tests are pending; add `pytest`-based suites under `tests/` with files named `test_*.py` as features mature.
- Prioritize `cadaver` and Zotero “Verify Server” integration checks before merging.
- When touching cache or auth logic, capture cache hit/miss and auth failure regressions.

## Commit & Pull Request Guidelines
- Write commit subjects in the imperative mood (`Add`, `Fix`, `Refactor`) and keep them under ~72 characters, following `Build initial QuarkDAV service`.
- Group related changes per commit and include body details when behavior, schema, or config shifts.
- Pull requests should summarize impact, link issues, note config/migration steps, and record verification evidence.
- Call out risky areas (filesystem writes, Quark API integration) and track deferred work in follow-up issues when scope must narrow.

## Security & Configuration Tips
- Do not commit real credentials or cookies; rely on `.env` and environment variables for secrets (`WEBDAV_USER`, `WEBDAV_PASSWORD`, `QUARK_COOKIE`, etc.).
- Keep cache directories writable but protected in production, and rotate credentials on shared instances.
