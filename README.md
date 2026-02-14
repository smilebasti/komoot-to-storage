# Komoot to Storage Exporter

Export your Komoot tours as GPX files to various storage backends.
Test it live: https://komoot.smilebasti.de

## Features

- 🔐 Login with your Komoot credentials
- 📅 Filter tours by date range and sport type
- 💾 Multiple storage backends:
  - **S3** — AWS S3, MinIO, Backblaze B2, Wasabi, etc.
  - **NFS** — Local path or network mount (self-hosted only)
  - **SMB/CIFS** — Windows shares, NAS devices
- 🐳 Docker support for easy deployment
- 🔒 Credentials are not stored (used only during export)

## Quick Start

### Using Docker (recommended)

```bash
docker run -d -p 5000:5000 smilebasti/komoot-to-storage:latest
```

Or with Docker Compose:

```bash
curl -O https://raw.githubusercontent.com/smilebasti/komoot-to-storage/main/docker-compose.yml
docker compose up -d
```

Then open `http://localhost:5000` in your browser.

### Self-Hosted Mode

Set `SELF_HOSTED=true` to enable additional features:

```bash
docker run -d -p 5000:5000 -e SELF_HOSTED=true smilebasti/komoot-to-storage:latest
```

Or in docker-compose.yml:
```yaml
environment:
  - SELF_HOSTED=true
```

Self-hosted features:
- **NFS / Local storage** — Save to local paths or mounted network drives
- **Automatic exports** — Scheduled backups via cron *(planned)*
- **Map preview** — Preview tours before export *(planned)*

### Manual Setup

```bash
git clone https://github.com/smilebasti/komoot-to-storage.git
cd komoot-to-storage

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python3 app.py
```

## Storage Backends

### S3-compatible Storage
- **Endpoint URL** — e.g., `https://s3.eu-central-1.amazonaws.com`
- **Bucket Name** — Your bucket name
- **Access Key** — AWS access key or equivalent
- **Secret Key** — AWS secret key or equivalent

### NFS / Local Path (self-hosted only)
- **Path** — Local or mounted path, e.g., `/mnt/nfs/komoot-backup`
- The path must exist and be writable
- Requires `SELF_HOSTED=true`

### SMB / CIFS
- **Server** — IP or hostname of SMB server
- **Share** — Share name (without `\\server\`)
- **Username/Password** — SMB credentials
- **Subfolder** — Optional path within the share

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `5000` | Port to listen on |
| `FLASK_DEBUG` | `False` | Enable debug mode |
| `SELF_HOSTED` | `false` | Enable self-hosted features |

## API

### POST /api/export

Programmatic export endpoint.

```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-12-31",
  "komoot_api_key": "email:password",
  "storage_type": "s3",
  "s3_endpoint": "https://s3.amazonaws.com",
  "s3_bucket": "my-bucket",
  "s3_access_key": "...",
  "s3_secret_key": "...",
  "export_name": "backup-2026",
  "exercise_type": "",
  "complete_only": true
}
```

### GET /health

Health check endpoint.
```json
{"status": "ok", "version": "1.0.0"}
```

## Security Notes

- Credentials are **not saved** to disk
- Use HTTPS in production (reverse proxy recommended)
- Consider running in a private network

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE) for details.

---

© 2026 Sebastian Wieser
