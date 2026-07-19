"""
Offline schema check for all LunaGrow BioSim scenarios — no server, no Docker.

Validates each scenario's generated XML against BioSim's real BiosimInitSchema.xsd
using xmllint. Run this before standing up the server to catch config regressions.

Usage:
    python validate_scenarios.py [path-to-biosim-clone]

If no path is given, looks for ./biosim (a clone of github.com/scottbell/biosim).
Requires: xmllint (apt-get install libxml2-utils) and the lunagrow_biosim package
on the path (run from the folder that contains lunagrow_biosim/).
"""
import os
import sys
import subprocess
import tempfile

from lunagrow_biosim.run import scenarios
from lunagrow_biosim.config import build_config, default_crew

biosim = sys.argv[1] if len(sys.argv) > 1 else "biosim"
schema = os.path.join(biosim, "etc", "schema", "BiosimInitSchema.xsd")
if not os.path.exists(schema):
    sys.exit(f"schema not found: {schema}\n"
             f"clone it:  git clone https://github.com/scottbell/biosim.git\n"
             f"or pass the path:  python validate_scenarios.py /path/to/biosim")

fails = 0
for name, sc in scenarios().items():
    xml = build_config(crew=default_crew(sc.crew_size),
                       shelves=sc.shelves, power_kw=sc.power_kw)
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
        f.write(xml)
        path = f.name
    r = subprocess.run(["xmllint", "--noout", "--schema", schema, path],
                       capture_output=True, text=True,
                       cwd=os.path.dirname(schema))
    ok = r.returncode == 0
    shelves = len(sc.shelves) if sc.shelves else "default"
    print(f"  {'PASS' if ok else 'FAIL'}  {name:14s} "
          f"crew={sc.crew_size} power={sc.power_kw} shelves={shelves}")
    if not ok:
        print("       ", r.stderr.strip().split("\n")[0])
        fails += 1
    os.unlink(path)

print(f"\n{'ALL SCENARIOS VALIDATE' if fails == 0 else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
