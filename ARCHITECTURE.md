# V47.3 Architecture

The V47.2 shared runtime architecture is retained. `monitoring.py` owns V47.3 system-health collection and persistent health history. `runtime.py` schedules an initial snapshot at startup and then an hourly snapshot. Health-history failures are isolated from the capture cycle. `publishing.py` retains the immutable telemetry schema v4 58-field contract.
