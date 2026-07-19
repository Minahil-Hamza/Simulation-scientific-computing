"""
LunaGrow — BioSim REST client and scenario runner
==================================================
Drives a running BioSim server (github.com/scottbell/biosim) over its REST API.

Start the server first:
    git clone https://github.com/scottbell/biosim.git && cd biosim
    docker compose up
    # server -> http://localhost:8009/api/simulation
    # Open MCT viewer -> http://localhost:9091

Then:
    python -m lunagrow_biosim.run --scenario all

Team LunaGrow — Mary Lee Tupling Bergman, DAOM, AP, CNC
NASA Deep Space Food Challenge: Mars to Table
"""

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

from .config import (
    build_config, default_crew, LUNAGROW_SHELVES, Shelf,
    CREW_SIZE, MISSION_SOLS, KCAL_PER_CREW_SOL, HABITAT_POWER_KW,
)

BASE = "http://localhost:8009/api/simulation"


# =============================================================================
# REST CLIENT
# =============================================================================

class BioSimClient:
    """Thin wrapper over the BioSim REST API."""

    def __init__(self, base_url: str = BASE, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.sim_id: Optional[int] = None

    # ---- lifecycle ----------------------------------------------------------
    def start(self, xml_config: str) -> int:
        """POST /api/simulation/start — XML config as plain text."""
        r = requests.post(f"{self.base}/start", data=xml_config.encode("utf-8"),
                          headers={"Content-Type": "text/plain"}, timeout=self.timeout)
        r.raise_for_status()
        self.sim_id = r.json()["simId"]
        return self.sim_id

    def tick(self) -> int:
        """POST /api/simulation/{simID}/tick — advance one tick."""
        r = requests.post(f"{self.base}/{self.sim_id}/tick", timeout=self.timeout)
        r.raise_for_status()
        return r.json()["ticks"]

    def state(self) -> dict:
        """GET /api/simulation/{simID} — globals + all modules."""
        r = requests.get(f"{self.base}/{self.sim_id}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def module(self, name: str) -> dict:
        r = requests.get(f"{self.base}/{self.sim_id}/modules/{name}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ---- flow control -------------------------------------------------------
    def set_consumer(self, module: str, rtype: str, rates: List[float],
                     connections: Optional[List[str]] = None) -> dict:
        body = {"desiredFlowRates": rates}
        if connections:
            body["connections"] = connections
        r = requests.post(f"{self.base}/{self.sim_id}/modules/{module}/consumers/{rtype}",
                          json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def set_producer(self, module: str, rtype: str, rates: List[float],
                     connections: Optional[List[str]] = None) -> dict:
        body = {"desiredFlowRates": rates}
        if connections:
            body["connections"] = connections
        r = requests.post(f"{self.base}/{self.sim_id}/modules/{module}/producers/{rtype}",
                          json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ---- malfunctions (off-nominal scenarios) -------------------------------
    def malfunction(self, module: str, intensity: str = "MEDIUM_MALF",
                    length: str = "TEMPORARY_MALF",
                    tick_to_occur: Optional[int] = None):
        """
        intensity: SEVERE_MALF | MEDIUM_MALF | LOW_MALF
        length:    TEMPORARY_MALF | PERMANENT_MALF

        Note on the server's two response shapes (verified against
        SimulationController.postMalfunction):
          - IMMEDIATE (no tickToOccur):  {"malfunctionID": <long>}
          - SCHEDULED (tickToOccur set): {"message": "Malfunction scheduled for tick N"}
        All fault scenarios here schedule with tickToOccur, so we must not
        assume a malfunctionID is present or the run crashes with KeyError.
        """
        body = {"intensity": intensity, "length": length}
        if tick_to_occur is not None:
            body["tickToOccur"] = tick_to_occur
        r = requests.post(f"{self.base}/{self.sim_id}/modules/{module}/malfunctions",
                          json=body, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data.get("malfunctionID", data.get("message", "scheduled"))

    def clear_malfunctions(self, module: str) -> dict:
        r = requests.delete(f"{self.base}/{self.sim_id}/modules/{module}/malfunctions",
                            timeout=self.timeout)
        r.raise_for_status()
        return r.json()


# =============================================================================
# METRIC EXTRACTION
# =============================================================================

@dataclass
class SolRecord:
    sol: int
    food_store_kcal: float
    biomass_store: float
    potable_water_l: float
    o2_level: float
    co2_level: float
    power_level: float
    dry_waste: float
    crew_alive: bool


def _level(state: dict, module: str) -> float:
    m = state.get("modules", {}).get(module, {})
    return float(m.get("properties", {}).get("currentLevel", 0.0))


def snapshot(state: dict, sol: int) -> SolRecord:
    g = state.get("globals", {})
    return SolRecord(
        sol=sol,
        food_store_kcal=_level(state, "Food_Store"),
        biomass_store=_level(state, "Biomass_Store"),
        potable_water_l=_level(state, "Potable_Water_Store"),
        o2_level=_level(state, "O2_Store"),
        co2_level=_level(state, "CO2_Store"),
        power_level=_level(state, "Habitat_Power_Store"),
        dry_waste=_level(state, "Dry_Waste_Store"),
        crew_alive=not g.get("simulationEnded", False),
    )


# =============================================================================
# SCENARIOS — nominal + off-nominal, per Challenge rules
# =============================================================================

@dataclass
class Scenario:
    name: str
    description: str
    crew_size: int = CREW_SIZE
    power_kw: float = HABITAT_POWER_KW
    shelves: Optional[List[Shelf]] = None
    malfunctions: Optional[List[dict]] = None
    sols: int = 100


def scenarios() -> Dict[str, Scenario]:
    """The Challenge requires nominal AND off-nominal: crew-size, power, resource."""
    return {
        "nominal": Scenario(
            "nominal",
            f"Baseline: {CREW_SIZE} crew, {HABITAT_POWER_KW} kW, full grow area.",
        ),
        # ---- crew-size variation ----
        "crew_reduced": Scenario(
            "crew_reduced",
            "Crew reduced to 10 (medical evacuation / partial handover).",
            crew_size=10,
        ),
        "crew_expanded": Scenario(
            "crew_expanded",
            "Crew expanded to 20 (overlapping handover — surge demand).",
            crew_size=20,
        ),
        # ---- power-availability variation ----
        "power_reduced": Scenario(
            "power_reduced",
            "Power reduced to 20 kW (dust storm attenuation of solar augmentation).",
            power_kw=20.0,
        ),
        "power_fault": Scenario(
            "power_fault",
            "Severe temporary fault on the power source at sol 30.",
            malfunctions=[{"module": "Nuclear_Source", "intensity": "SEVERE_MALF",
                           "length": "TEMPORARY_MALF", "tickToOccur": 30}],
        ),
        # ---- resource-constraint variation ----
        "crop_loss": Scenario(
            "crop_loss",
            "Loss of the sweet potato tier (dominant caloric crop) — 96 m2 offline.",
            shelves=[s for s in LUNAGROW_SHELVES if s.crop_type != "SWEET_POTATO"],
        ),
        "water_fault": Scenario(
            "water_fault",
            "Permanent medium fault on water recovery at sol 20 — tests 91% reclamation.",
            malfunctions=[{"module": "WaterRS", "intensity": "MEDIUM_MALF",
                           "length": "PERMANENT_MALF", "tickToOccur": 20}],
        ),
        "ogs_fault": Scenario(
            "ogs_fault",
            "Severe permanent O2 generation fault at sol 40 — tests plant O2 contribution.",
            malfunctions=[{"module": "OGS", "intensity": "SEVERE_MALF",
                           "length": "PERMANENT_MALF", "tickToOccur": 40}],
        ),
    }


def run_scenario(sc: Scenario, base_url: str = BASE, verbose: bool = True) -> List[SolRecord]:
    client = BioSimClient(base_url)
    xml = build_config(
        crew=default_crew(sc.crew_size),
        shelves=sc.shelves,
        power_kw=sc.power_kw,
    )
    sim_id = client.start(xml)
    if verbose:
        print(f"  [{sc.name}] simId={sim_id} — {sc.description}")

    for m in (sc.malfunctions or []):
        mid = client.malfunction(m["module"], m["intensity"], m["length"], m.get("tickToOccur"))
        if verbose:
            print(f"      scheduled malfunction {mid}: {m['module']} "
                  f"{m['intensity']} @ tick {m.get('tickToOccur')}")

    records: List[SolRecord] = []
    for sol in range(1, sc.sols + 1):
        client.tick()
        if sol % 5 == 0 or sol == 1:
            rec = snapshot(client.state(), sol)
            records.append(rec)
            if not rec.crew_alive:
                if verbose:
                    print(f"      !! simulation ended at sol {sol}")
                break
    return records


def write_csv(name: str, records: List[SolRecord], outdir: str = "results") -> str:
    import os
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{name}.csv")
    with open(path, "w", newline="") as f:
        if not records:
            return path
        w = csv.DictWriter(f, fieldnames=list(asdict(records[0]).keys()))
        w.writeheader()
        for r in records:
            w.writerow(asdict(r))
    return path


def main():
    ap = argparse.ArgumentParser(description="LunaGrow BioSim scenario runner")
    ap.add_argument("--scenario", default="nominal",
                    help="scenario name, or 'all'")
    ap.add_argument("--sols", type=int, default=100)
    ap.add_argument("--url", default=BASE)
    ap.add_argument("--print-config", action="store_true",
                    help="print the XML config and exit (no server needed)")
    args = ap.parse_args()

    if args.print_config:
        print(build_config())
        return

    all_sc = scenarios()
    names = list(all_sc) if args.scenario == "all" else [args.scenario]

    print(f"LunaGrow BioSim — {CREW_SIZE} crew · {KCAL_PER_CREW_SOL} kcal/crew/sol\n")
    summary = {}
    for n in names:
        sc = all_sc[n]
        sc.sols = args.sols
        try:
            recs = run_scenario(sc, args.url)
            path = write_csv(n, recs)
            last = recs[-1] if recs else None
            summary[n] = {
                "sols_run": last.sol if last else 0,
                "crew_alive": last.crew_alive if last else False,
                "final_food": last.food_store_kcal if last else 0,
                "final_water": last.potable_water_l if last else 0,
                "csv": path,
            }
            print(f"      -> {path}")
        except requests.exceptions.ConnectionError:
            sys.exit(f"\nERROR: no BioSim server at {args.url}\n"
                     f"Start it with:  docker compose up   (see RUNBOOK.md)")

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
