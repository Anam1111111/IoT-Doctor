# IoT Debugger

A portable, real-time serial log viewer and debugger for IoT/embedded firmware development.

## What it does
- Connects to any device over serial (UART)
- Parses logs using a per-project YAML profile (no code changes needed between projects)
- Shows live, color-coded, searchable logs in a browser dashboard
- Tracks event rate and saves every session to a timestamped log file
- Automatically reconnects if the device is unplugged

## Setup
\`\`\`bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
\`\`\`

## Running it
1. Plug in your device
2. Find its port: \`ls /dev/tty.*\`
3. Update \`profiles/<your_device>.yaml\` with the correct port, baud rate, and log pattern
4. Run: \`uvicorn core.server:app --reload\`
5. Open \`http://127.0.0.1:8000\`

## Adding a new device
Copy \`profiles/arduino_uno.yaml\`, adjust the \`port\`, \`baud_rate\`, and \`log_pattern\` regex to match your device's actual log format. No code changes needed.

## Project structure
- \`core/\` — the reusable engine (serial reading, parsing, dashboard server)
- \`profiles/\` — per-device/per-project config files
- \`ui/\` — the dashboard frontend
- \`sessions/\` — saved log files from past sessions
- \`tools/\` — simulation scripts used during development/testing
