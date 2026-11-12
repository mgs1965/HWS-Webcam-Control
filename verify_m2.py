#!/usr/bin/env python3
"""Static M2 completeness and syntax validation; does not initialise Picamera2."""
import ast, json, hashlib
from pathlib import Path
root=Path(__file__).resolve().parent
manifest=json.loads((root/"manifest.json").read_text())
found={}
for path in root.glob("*.py"):
    if path.name in {"verify_m2.py","loader.py","weather_camera.py","core.py"}: continue
    source=path.read_text(encoding="utf-8"); compile(source,str(path),"exec")
    tree=ast.parse(source)
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            segment=ast.get_source_segment(source,node)
            found[node.name]=(path.name,hashlib.sha256((segment+"\n").encode()).hexdigest())
missing=set(manifest)-set(found); extra=set(found)-set(manifest)
if missing or extra: raise SystemExit(f"FAIL missing={sorted(missing)} extra={sorted(extra)}")
for name, (module, digest) in found.items():
    expected=manifest[name]
    if expected.get("module") != module or expected.get("sha256") != digest:
        raise SystemExit(f"FAIL manifest mismatch for {name}: found={module}/{digest} expected={expected}")
print("PASS: manifest module ownership and function hashes match.")
compile((root/"core.py").read_text(),str(root/"core.py"),"exec")
print(f"PASS: {len(found)} classes/functions mapped; all M2 source files compile.")

required={"camera.py":"OVERLAY_FONT","publishing.py":"TELEMETRY_FIELDS"}
for filename,name in required.items():
    tree=ast.parse((root/filename).read_text(encoding="utf-8"))
    stores={x.id for x in ast.walk(tree) if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Store)}
    if name not in stores: raise SystemExit(f"FAIL: missing module initialisation {name} in {filename}")
print("PASS: required module-level initialisations are present.")

version_source=(root/"version.py").read_text(encoding="utf-8")
version_tree=ast.parse(version_source)
vals={}
for node in version_tree.body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and isinstance(node.value,ast.Constant):
        vals[node.targets[0].id]=node.value.value
if vals.get("VERSION") != "V46-RC1": raise SystemExit("FAIL: central VERSION is not V45-TL8-M2.5")
if vals.get("TELEMETRY_SCHEMA_VERSION") != 2: raise SystemExit("FAIL: telemetry schema version is not 2")
pub=(root/"publishing.py").read_text(encoding="utf-8")
if "_v{TELEMETRY_SCHEMA_VERSION}_" not in pub: raise SystemExit("FAIL: explicit telemetry version filename missing")
print("PASS: central release metadata and explicit telemetry v2 filename policy are present.")

runtime_source=(root/"runtime.py").read_text(encoding="utf-8")
for marker in ("[STARTUP] Python=%s", "[STARTUP] Host=%s", "[STARTUP] PID=%d", "[STARTUP] Started=%s"):
    if marker not in runtime_source: raise SystemExit(f"FAIL: missing startup marker {marker}")
print("PASS: startup Python, Host, PID and Started logging are present.")

# M2.4 defect-regression guards.
pub_tree=ast.parse(pub)
append_node=next(node for node in pub_tree.body if isinstance(node,ast.FunctionDef) and node.name=="append_monthly_telemetry")
for node in ast.walk(append_node):
    if isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id=="telemetry_failure_count":
        raise SystemExit("FAIL: append_monthly_telemetry must not mutate telemetry_failure_count")
    if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=="telemetry_failure_count" for target in node.targets):
        raise SystemExit("FAIL: append_monthly_telemetry must not mutate telemetry_failure_count")
monitoring_source=(root/"monitoring.py").read_text(encoding="utf-8")
for marker in ("telemetry_suffix.startswith('v')", "schema_text, telemetry_suffix = telemetry_suffix.split('_', 1)", "not 1 <= month <= 12"):
    if marker not in monitoring_source: raise SystemExit(f"FAIL: missing M2.4 telemetry retention guard {marker}")
print("PASS: M2.4 telemetry failure ownership and versioned retention guards are present.")

# M2.5 LOW LIGHT entry-floor regression guards.
core_source=(root/"core.py").read_text(encoding="utf-8")
modes_source=(root/"modes.py").read_text(encoding="utf-8")
exposure_source=(root/"exposure.py").read_text(encoding="utf-8")
for marker, source in (
    ("low_light_entry_floor_product = None", core_source),
    ("previous_mode == 'TWILIGHT'", modes_source),
    ("[LOW LIGHT ENTRY FLOOR] Armed", modes_source),
    ("[LOW LIGHT FLOOR] Applied", exposure_source),
    ("action != 'HIGHLIGHT PROTECTION'", exposure_source),
):
    if marker not in source: raise SystemExit(f"FAIL: missing M2.5 LOW LIGHT floor marker {marker}")
print("PASS: M2.5 LOW LIGHT entry floor and highlight-protection override are present.")
