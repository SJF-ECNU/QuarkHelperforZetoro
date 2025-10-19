Here’s the English translation of your document:

---

## 🔍 1. Project Goals and Scope

The goal is to build:

> **A Zotero-compatible WebDAV service implemented in Python, using Quark Cloud Drive as the underlying storage.**

### Specific Requirements

| Feature                           | Description                                                             |
| --------------------------------- | ----------------------------------------------------------------------- |
| ✅ WebDAV Standard API             | Support for `PROPFIND`, `MKCOL`, `PUT`, `GET`, `DELETE`, `HEAD`, `MOVE` |
| ✅ Zotero Compatibility            | Must pass Zotero’s “Verify Server” check                                |
| ✅ Upload/Download via Quark Drive | File storage and retrieval handled via Quark APIs                       |
| ✅ Caching Support                 | Local temporary cache to reduce duplicate uploads                       |
| ✅ Basic Auth Security             | Username/password protection                                            |
| ✅ Docker Deployment               | Supports running in containers                                          |

---

## ⚙️ 2. Technical Stack

| Module                 | Technology Choice                    | Reason                                  |
| ---------------------- | ------------------------------------ | --------------------------------------- |
| WebDAV Server          | `wsgidav` or `aiohttp` + `pywebdav3` | Implements the standard WebDAV protocol |
| QuarkDrive API Wrapper | `requests` + custom wrapper          | Simulate Quark Cloud API                |
| Cache Layer            | `sqlite3` + file cache directory     | Store file metadata and local mirrors   |
| Authentication         | HTTP Basic Auth                      | Compatible with Zotero WebDAV login     |
| Logging & Debugging    | `loguru`                             | Easier debugging and diagnostics        |
| Configuration          | `.env` + `pydantic`                  | Manage cookies, accounts, ports         |
| Deployment             | Dockerfile + docker-compose          | Cross-platform deployment               |

---

## 🧱 3. Module Architecture

```
quarkdav/
├── main.py                 # Entry point, starts the WebDAV service
├── config.py               # Configuration parser (cookie, port, etc.)
├── quark_client/
│   ├── __init__.py
│   ├── api.py              # Encapsulates Quark Cloud HTTP APIs
│   ├── auth.py             # Cookie login and refresh logic
│   ├── utils.py            # Encryption/signature/request utilities
├── webdav/
│   ├── __init__.py
│   ├── server.py           # WebDAV handler implementation
│   ├── resource.py         # Abstractions for WebDAV file/directory resources
│   ├── compat_zotero.py    # Zotero compatibility fixes
├── cache/
│   ├── index.db            # Local metadata cache
│   ├── storage/            # Temporary file directory
└── Dockerfile
```

---

## 💾 4. Data Flow & API Interaction

### 4.1 File Upload (Zotero → WebDAV → Quark)

1. Zotero performs `PUT /zotero/userid/xxxx.zip`
2. WebDAV receives the file stream → saves to cache folder
3. Upload via `quark_client.api.upload(file_path)` to Quark Cloud
4. Return `201` with correct `ETag` and `Content-Length`

### 4.2 File Download (Zotero → WebDAV → Quark)

1. Zotero sends `GET /zotero/...`
2. WebDAV queries cache index (sqlite)
3. If cached, serve directly; otherwise, call `quark_client.api.download(url)` to fetch and cache
4. Return `200` with file stream

### 4.3 Directory Listing (Zotero → PROPFIND)

1. Return a simulated file tree (from sqlite index or QuarkDrive metadata)
2. Format must comply with WebDAV XML response (Zotero is strict)

### 4.4 File Validation (Zotero → HEAD)

1. WebDAV returns `Content-Length`, `ETag`, `Last-Modified`
2. Ensure `ETag` equals the file’s MD5 checksum

---

## 🔐 5. Authentication & Security

| Item             | Implementation                                        |
| ---------------- | ----------------------------------------------------- |
| WebDAV Auth      | Basic Auth (USER/PASSWORD in config file)             |
| QuarkDrive Login | Reads `QUARK_COOKIE` from `.env`                      |
| Cookie Refresh   | Provide `/refresh` endpoint or background auto-check  |
| HTTPS            | Recommend using Nginx reverse proxy or Caddy with SSL |
| Rate Limiting    | Prevent Quark’s anti-bot triggers during Zotero sync  |

---

## 🧪 6. Testing & Compatibility Verification

### Test Checklist

| Test Item               | Method                                   | Goal                         |
| ----------------------- | ---------------------------------------- | ---------------------------- |
| ✅ WebDAV Basic Test     | Use `cadaver` or `davfs2`                | Verify basic upload/download |
| ✅ Zotero Verify Server  | Zotero → Preferences → Verify Server     | Must pass verification       |
| ✅ Multi-file Upload     | Upload 100 attachments                   | Test performance             |
| ✅ File Deletion         | Ensure no sync errors after deletion     |                              |
| ✅ Cookie Expiry Retry   | Simulate invalid cookie scenario         |                              |
| ✅ High Concurrency Test | 10 Zotero clients syncing simultaneously |                              |

---

## 🚀 7. Three-Phase Development Plan

### 🥇 Phase 1: Minimum Viable Version (1–2 weeks)

Goal: Zotero passes “Verify Server” check.

* Use `wsgidav` to start a local WebDAV service
* Implement `GET`, `PUT`, `HEAD`, `MKCOL`, etc. (local-only)
* Mock Quark API: no real uploads yet, just local cache

👉 Output: A local WebDAV server that Zotero recognizes as valid

---

### 🥈 Phase 2: Integrate Quark Cloud API (2–3 weeks)

Goal: Files actually stored in Quark Cloud.

* Reverse-engineer Quark API (via browser requests or reference Rust version `quarkdrive-webdav`)
* Implement `upload`, `download`, `list`, `delete`, etc.
* Add caching layer (`sqlite` + `storage/`)

👉 Output: Zotero syncs via WebDAV; files actually saved to Quark Cloud

---

### 🥉 Phase 3: Optimization & Deployment (2 weeks)

* Implement automatic cookie refresh
* Add Docker support
* Provide log dashboard and `/status` health check
* Add multi-user support (optional)

👉 Output: Stable Docker service deployable on NAS or VPS for long-term use

---

## 💡 Appendix: Example `.env` Configuration

```env
# WebDAV user authentication
WEBDAV_USER=zotero
WEBDAV_PASSWORD=123456
PORT=5212

# Quark login cookie
QUARK_COOKIE=__quark_did=xxxx

# Cache paths
CACHE_DIR=/data/cache
DB_PATH=/data/index.db
```

---

## Recommended Reference Repositories

* [https://github.com/chenqimiao/quarkdrive-webdav](https://github.com/chenqimiao/quarkdrive-webdav)
* [https://github.com/AlistGo/alist.git](https://github.com/AlistGo/alist.git)

---
