# QuarkDAV

QuarkDAV is a lightweight Python WebDAV server that mimics Zotero's WebDAV requirements while storing data in a Quark Cloud compatible layout. The current implementation focuses on a local filesystem backend so that the service can be developed and tested without the official Quark APIs.

## Features

- Basic WebDAV verbs: `PROPFIND`, `MKCOL`, `PUT`, `GET`, `HEAD`, `DELETE`, and `MOVE`
- HTTP Basic authentication compatible with Zotero's WebDAV client
- SQLite metadata cache and local file cache to avoid duplicate transfers
- Pluggable Quark client layer (currently filesystem backed) for future API integration
- Docker-friendly deployment

## Getting Started

### Requirements

- Python 3.11+
- `pip`

Install dependencies:

```bash
pip install -r requirements.txt
```

### Configuration

QuarkDAV reads its configuration from environment variables or a local `.env` file. Example:

```env
WEBDAV_USER=zotero
WEBDAV_PASSWORD=123456
PORT=5212
CACHE_DIR=cache/storage
DB_PATH=cache/index.db
QUARK_COOKIE=__quark_did=xxxx
SSL_CERT_FILE=/path/to/cert.pem
SSL_KEY_FILE=/path/to/key.pem
```

### Run the Server

```bash
python -m quarkdav.main
```

The server will listen on `http://0.0.0.0:5212` by default. When both `SSL_CERT_FILE`
and `SSL_KEY_FILE` are provided, QuarkDAV serves traffic over HTTPS instead. Use the
configured username and password for Basic authentication.

### Docker

Build and run the container:

```bash
docker build -t quarkdav .
docker run -p 5212:5212 -v $(pwd)/cache:/app/cache --env-file .env quarkdav
```

### WebDAV Testing

You can exercise the service using the `cadaver` CLI:

```bash
cadaver http://localhost:5212/
```

Use the configured WebDAV credentials when prompted.

## Project Layout

The repository structure mirrors the development plan from `plan.md`, with dedicated packages for configuration, the Quark client abstraction, cache management, and the WebDAV server implementation.

## Roadmap

- Replace the filesystem-backed `QuarkClient` with real HTTP bindings to Quark Cloud
- Implement cookie refresh flows and `/status` diagnostics endpoints
- Add comprehensive unit tests and CI/CD integration
