#!/bin/bash
set -e

echo "==========================================="
echo "Chrome Pool Manager - Installation"
echo "(Skipping Chrome installation)"
echo "==========================================="
echo ""

# Note about Chrome
echo "⚠️  Chrome installation skipped (requires sudo)"
echo "    Install manually if needed:"
echo "    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -"
echo "    sudo sh -c 'echo \"deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main\" >> /etc/apt/sources.list.d/google-chrome.list'"
echo "    sudo apt-get update && sudo apt-get install -y google-chrome-stable"
echo ""

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.11+"
    exit 1
fi

echo "✅ Python found: $(python3 --version)"

# Install pool service
echo ""
echo "Installing Pool Service..."
cd pool-service
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
echo "✅ Pool service installed"

# Install MCP server
echo ""
echo "Installing MCP Server..."
cd ../mcp-server
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
echo "✅ MCP server installed"

# Install systemd services
echo ""
echo "Installing systemd services..."
cd ../scripts

mkdir -p ~/.config/systemd/user/
cp chrome-pool.service ~/.config/systemd/user/
cp chrome-manager-mcp.service ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

echo "✅ Systemd services installed"

# Enable services
echo ""
echo "Enabling services..."
systemctl --user enable chrome-pool.service
systemctl --user enable chrome-manager-mcp.service
echo "✅ Services enabled"

echo ""
echo "==========================================="
echo "Installation Complete!"
echo "==========================================="
echo ""
echo "⚠️  NOTE: Chrome not installed. Pool service will fail to start."
echo "    Either install Chrome, or the service will work once Chrome is available."
echo ""
echo "Start services:"
echo "  systemctl --user start chrome-pool"
echo "  systemctl --user start chrome-manager-mcp"
echo ""
echo "Check status:"
echo "  systemctl --user status chrome-pool"
echo "  systemctl --user status chrome-manager-mcp"
echo ""
echo "View logs:"
echo "  journalctl --user -u chrome-pool -f"
echo "  journalctl --user -u chrome-manager-mcp -f"
echo ""
echo "Test pool service:"
echo "  curl http://localhost:8765/health"
echo ""
