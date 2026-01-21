# Installing Chrome on WSL

The Chrome Pool Manager requires Chrome to be installed on WSL. Here's how to install it:

## Quick Install

```bash
# Add Google Chrome repository
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'

# Update and install
sudo apt-get update
sudo apt-get install -y google-chrome-stable

# Verify installation
google-chrome --version
```

## Testing Chrome in WSL

Chrome requires specific flags to run in WSL (no GUI, headless mode):

```bash
# Test Chrome can start
google-chrome --headless=new --no-sandbox --disable-gpu --remote-debugging-port=9999 about:blank &

# Check if debugging port is accessible
curl http://localhost:9999/json/version

# Kill test instance
pkill chrome
```

## After Installing Chrome

Once Chrome is installed:

```bash
# Start the pool service
systemctl --user start chrome-pool

# Check it's working
curl http://localhost:8765/health
```

## Alternative: Use Chromium

If you prefer Chromium over Chrome:

```bash
sudo apt-get install -y chromium-browser
```

Then edit `/home/john/chrome-pool-manager/pool-service/chrome_pool_service.py`:

```python
# Change this line:
CHROME_PATH = "/usr/bin/google-chrome"

# To:
CHROME_PATH = "/usr/bin/chromium-browser"
```

Then restart the service:

```bash
systemctl --user restart chrome-pool
```
