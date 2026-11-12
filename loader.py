"""Load physical M2 source modules into one shared namespace.

V45-TL8 relied on module-level shared mutable state. Executing the physically
separated subsystem files into this single namespace retains that exact state
model while removing the monolithic runtime source file.
"""
from pathlib import Path
MODULE_ORDER = ['version.py', 'core.py', 'camera.py', 'modes.py', 'exposure.py', 'image_quality.py', 'state.py', 'publishing.py', 'timelapse.py', 'monitoring.py', 'runtime.py']
def load_runtime():
    root=Path(__file__).resolve().parent
    ns={"__name__":"weather_camera_m2_runtime","__file__":str(root/"weather_camera.py")}
    for filename in MODULE_ORDER:
        path=root/filename
        exec(compile(path.read_text(encoding="utf-8"),str(path),"exec"),ns,ns)
    return ns
