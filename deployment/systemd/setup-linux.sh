#!/bin/bash
# Loomind — Linux Setup Script
# Sets up the engine as a systemd service
#
# Usage: sudo bash setup-linux.sh

set -euo pipefail

INSTALL_DIR="/opt/loomind"
DATA_DIR="/var/lib/loomind"
LOG_DIR="/var/log/loomind"
SERVICE_USER="loomind"

echo "═══════════════════════════════════════════════════"
echo "  Loomind — Linux Server Setup"
echo "═══════════════════════════════════════════════════"

# Check root
if [ "$EUID" -ne 0 ]; then
  echo "[ERROR] Please run as root: sudo bash $0"
  exit 1
fi

# Create service user
if ! id "$SERVICE_USER" &>/dev/null; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  echo "[OK] Created user: $SERVICE_USER"
else
  echo "[OK] User exists: $SERVICE_USER"
fi

# Create directories
mkdir -p "$DATA_DIR/qdrant"
mkdir -p "$LOG_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR" "$LOG_DIR"
echo "[OK] Created data directories"

# Copy project (if not already in /opt)
if [ ! -d "$INSTALL_DIR/core/loomind-engine" ]; then
  echo "[INFO] Copying project to $INSTALL_DIR..."
  mkdir -p "$INSTALL_DIR"
  cp -r . "$INSTALL_DIR/"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
else
  echo "[OK] Project already at $INSTALL_DIR"
fi

# Setup Python venv
cd "$INSTALL_DIR/core/loomind-engine"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt 2>/dev/null || .venv/bin/pip install -r "$INSTALL_DIR/requirements.txt"
  echo "[OK] Python venv created"
else
  echo "[OK] Python venv exists"
fi

# Install systemd service
cp "$INSTALL_DIR/deployment/systemd/loomind-engine.service" /etc/systemd/system/
systemctl daemon-reload
echo "[OK] Systemd service installed"

# Enable and start
systemctl enable loomind-engine
systemctl start loomind-engine

echo ""
echo "═══════════════════════════════════════════════════"
echo "  SETUP COMPLETE!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Service: systemctl status loomind-engine"
echo "  Logs:    journalctl -u loomind-engine -f"
echo "  URL:     http://127.0.0.1:8082"
echo "  Docs:    http://127.0.0.1:8082/docs"
echo ""
echo "  Commands:"
echo "    sudo systemctl start loomind-engine"
echo "    sudo systemctl stop loomind-engine"
echo "    sudo systemctl restart loomind-engine"
echo ""
