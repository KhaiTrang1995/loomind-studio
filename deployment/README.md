# Deployment

This directory contains deployment configurations for Loomind Experience Engine.

## Available Deployment Methods

### Docker Compose (Recommended for VPS)

See [`apps/docker-deployment/`](../apps/docker-deployment/) for the Docker Compose setup.

```bash
cd apps/docker-deployment
docker compose up -d
```

### Linux systemd Service

See [`systemd/`](systemd/) for the systemd unit file to run the engine as a background service on Linux.

```bash
sudo cp systemd/loomind-engine.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now loomind-engine
```

### Windows Desktop (NSIS Installer)

Build the all-in-one installer:

```bash
python build_all.py
# → Output: dist/Loomind-Setup.exe
```
