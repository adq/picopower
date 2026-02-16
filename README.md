# Pico Power Monitor

MicroPython-based power monitoring system using a Raspberry Pi Pico and BH1750 light sensor for pulse detection.

## Features

- Light pulse detection and counting for energy monitoring
- MQTT integration with Home Assistant
- Async/await architecture for concurrent sensor reading and MQTT publishing
- Syslog support for remote logging
- WiFi connectivity

## Hardware Requirements

- Raspberry Pi Pico W
- BH1750 light sensor (I2C)
- LED indicator (built-in Pico LED)

## Configuration

Copy `cfgsecrets_template.py` to `cfgsecrets.py` and configure:
- WiFi SSID and password
- MQTT broker hostname

## Testing

This project uses UV for Python dependency management:

```bash
# Install test dependencies
uv sync --extra test

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov
```

## Deployment

Use the `deploy` script to upload code to the Pico.

## Architecture

- **async_mqtt_client.py**: Async MQTT client implementation
- **lib.py**: Syslog logging functionality
- **main.py**: Main application with sensor and MQTT tasks
- **unittests/**: Comprehensive test suite
