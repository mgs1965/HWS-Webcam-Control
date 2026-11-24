"""Shared helpers for the test files."""
from pathlib import Path
import ast
import importlib.util
import hashlib
import json
import logging
import os
import pytest
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent

VERSION = re.search(r'VERSION="(V(?:\d{4}\.\d{2}\.\d{2}\.\d{2}|\d+\.\d+|\d{4}-\d{2}-\d{2}-\d{2}))"', (ROOT / 'version.py').read_text(encoding='utf-8')).group(1)

NUM = VERSION[1:]

def load_source_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def load_v52_namespace(tmp_path, *filenames):
    import glob, math, threading, time
    from collections import deque
    import numpy as np
    from PIL import Image, ImageDraw
    namespace = {
        'np': np, 'os': os, 'json': json, 'glob': glob, 'math': math, 'time': time,
        'threading': threading, 'deque': deque, 'datetime': datetime, 'timedelta': timedelta,
        'Image': Image, 'ImageDraw': ImageDraw, 'logger': logging.getLogger('v52-test'),
        'local_now': lambda: datetime.now().astimezone(), 'audit_event': lambda *a, **k: None,
        'clamp': lambda value, low, high: max(low, min(high, value)),
        'LOGS_PATH': str(tmp_path / 'logs'), 'LOCAL_SAVE_PATH': str(tmp_path),
        'WEB_WIDTH': 1920, 'WEB_HEIGHT': 1080, 'current_camera_mode': 'DAY',
        'upload_to_ftp': lambda *a, **k: True,
    }
    os.makedirs(namespace['LOGS_PATH'], exist_ok=True)
    for filename in filenames:
        exec(compile((ROOT / filename).read_text(encoding='utf-8'), filename, 'exec'), namespace)
    return namespace

def load_timelapse_functions(*names, **extra):
    tree = ast.parse((ROOT / 'timelapse.py').read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    import threading
    namespace = {'timedelta': timedelta, 'os': os, 'threading': threading, 'logger': logging.getLogger('v52-test'), 'audit_event': lambda *a, **k: None}
    namespace.update(extra)
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<periodic>', 'exec'), namespace)
    return namespace

def _load_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv('WEATHERCAM_ROOT', str(tmp_path))
    monkeypatch.setenv('DASHBOARD_OUT', str(tmp_path / 'out'))
    spec = importlib.util.spec_from_file_location('dash54_7', ROOT / 'weathercam_dashboard/dashboard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _camera_namespace(tmp_path, **extra):
    ns = load_v52_namespace(tmp_path, 'modes.py', 'exposure.py', 'image_quality.py')
    morning = datetime(2026, 11, 20, 6, 0).astimezone()
    ns.update({
        'NIGHT_ELEVATION': -5.0, 'NIGHT_DAWN_CAP_START_ELEVATION': -8.0, 'MAX_NIGHT_EXPOSURE_US': 4500000,
        'MAX_LOW_LIGHT_EXPOSURE_US': 1500000, 'MAX_TWILIGHT_EXPOSURE_US': 1000000, 'current_solar_elevation': -10.0,
        'get_harpenden_sun_times': lambda: (morning.replace(hour=7), morning.replace(hour=16)),
        'local_now': lambda: morning, 'BRIGHTNESS_FILTER_ALPHA': 0.2, 'DAWN_BRIGHTNESS_FILTER_ALPHA': 0.1,
        'NIGHT_QUALITY_NOISY_GAIN': 3.2, 'NIGHT_QUALITY_WASH_BRIGHTNESS': 85.0, 'NIGHT_MAX_HIGHLIGHT_PERCENT': 5.0,
        'NIGHT_OBSERVABILITY_MIN_BRIGHTNESS': 18.0, 'night_quality_state': 'N/A', 'manual_gain': 1.5,
    })
    ns.update(extra)
    return ns

def _dash(tmp_path):
    dash = load_source_module('dash_insights', ROOT / 'weathercam_dashboard/dashboard.py')
    dash.LD = tmp_path
    dash.FORECAST_ENABLED = False
    return dash
