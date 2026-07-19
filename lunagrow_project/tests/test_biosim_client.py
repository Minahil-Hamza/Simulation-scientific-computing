"""
Unit tests for BioSimClient and the LunaGrow scenario/config layer.

These mock the BioSim REST API rather than requiring a live server, so they
run anywhere (CI, this container, your laptop) without Docker or a JVM.
They verify OUR code's request/response handling — they do NOT verify
BioSim's own simulation physics, which only a real server run can confirm.
"""
import json
import responses
import pytest
from lxml import etree

from lunagrow_biosim.run import (
    BioSimClient, scenarios, snapshot, run_scenario, write_csv,
)
from lunagrow_biosim.config import build_config, default_crew, LUNAGROW_SHELVES, Shelf

BASE = "http://localhost:8009/api/simulation"
SCHEMA = etree.XMLSchema(
    etree.parse("/home/claude/biosim/etc/schema/BiosimInitSchema.xsd")
)

# BioSim's real PlantType enum (etc/schema/simulation/Food.xsd) — used only
# to check our own defaults, not enforced by build_config() itself.
VALID_CROP_TYPES = {
    "DRY_BEAN", "LETTUCE", "PEANUT", "RICE", "SOYBEAN",
    "SWEET_POTATO", "TOMATO", "WHEAT", "WHITE_POTATO",
}


# =============================================================================
# Config generation
# =============================================================================

def test_build_config_is_schema_valid():
    xml = build_config()
    doc = etree.fromstring(xml.encode())
    assert SCHEMA.validate(doc), SCHEMA.error_log


def test_all_scenarios_generate_valid_config():
    for name, sc in scenarios().items():
        xml = build_config(
            crew=default_crew(sc.crew_size), shelves=sc.shelves, power_kw=sc.power_kw
        )
        doc = etree.fromstring(xml.encode())
        assert SCHEMA.validate(doc), f"{name}: {SCHEMA.error_log}"


def test_invalid_crop_type_fails_schema_validation():
    """
    build_config() itself doesn't validate crop types (it just formats
    whatever string it's given into the XML) — so an invalid crop type
    should still be caught downstream by the real BioSim schema, which is
    what the server would enforce on POST /start. This guards against
    someone quietly removing that safety net.
    """
    bad_shelf = Shelf(crop_type="MOON_CHEESE", area_m2=10.0, represents="not real")
    xml = build_config(shelves=[bad_shelf])
    doc = etree.fromstring(xml.encode())
    assert not SCHEMA.validate(doc)


def test_default_shelves_use_only_valid_crop_types():
    for shelf in LUNAGROW_SHELVES:
        assert shelf.crop_type in VALID_CROP_TYPES


def test_crop_loss_scenario_excludes_sweet_potato():
    sc = scenarios()["crop_loss"]
    assert all(s.crop_type != "SWEET_POTATO" for s in sc.shelves)


# =============================================================================
# BioSimClient — lifecycle
# =============================================================================

@responses.activate
def test_client_start_returns_sim_id():
    responses.add(
        responses.POST, f"{BASE}/start",
        json={"simId": 7}, status=200,
    )
    client = BioSimClient()
    sim_id = client.start(build_config())
    assert sim_id == 7
    assert client.sim_id == 7


@responses.activate
def test_client_start_raises_on_400_config_rejected():
    """Runbook 4.1: a 400 means the XML is being rejected by the schema."""
    responses.add(
        responses.POST, f"{BASE}/start",
        json={"error": "invalid config"}, status=400,
    )
    client = BioSimClient()
    with pytest.raises(Exception):
        client.start(build_config())


@responses.activate
def test_client_tick_increments():
    responses.add(responses.POST, f"{BASE}/start", json={"simId": 1}, status=200)
    responses.add(responses.POST, f"{BASE}/1/tick", json={"ticks": 1}, status=200)
    client = BioSimClient()
    client.start(build_config())
    assert client.tick() == 1


@responses.activate
def test_client_state_and_module():
    state_payload = {
        "globals": {"simulationEnded": False},
        "modules": {"Food_Store": {"properties": {"currentLevel": 12345.0}}},
    }
    responses.add(responses.POST, f"{BASE}/start", json={"simId": 3}, status=200)
    responses.add(responses.GET, f"{BASE}/3", json=state_payload, status=200)
    client = BioSimClient()
    client.start(build_config())
    state = client.state()
    assert state["modules"]["Food_Store"]["properties"]["currentLevel"] == 12345.0


@responses.activate
def test_client_malfunction_immediate_shape():
    """No tickToOccur -> real server returns {"malfunctionID": <id>}."""
    responses.add(responses.POST, f"{BASE}/start", json={"simId": 5}, status=200)
    responses.add(
        responses.POST, f"{BASE}/5/modules/WaterRS/malfunctions",
        json={"malfunctionID": 42}, status=200,
    )
    client = BioSimClient()
    client.start(build_config())
    result = client.malfunction("WaterRS", "MEDIUM_MALF", "TEMPORARY_MALF")
    assert result == 42


@responses.activate
def test_client_malfunction_scheduled_shape_no_keyerror():
    """
    tickToOccur set -> real server returns {"message": "..."}, no
    malfunctionID (confirmed against SimulationController.postMalfunction).
    All three fault scenarios (power_fault/water_fault/ogs_fault) hit this
    path — this is the exact case that used to crash with a KeyError.
    """
    responses.add(responses.POST, f"{BASE}/start", json={"simId": 5}, status=200)
    responses.add(
        responses.POST, f"{BASE}/5/modules/WaterRS/malfunctions",
        json={"message": "Malfunction scheduled for tick 20"}, status=200,
    )
    client = BioSimClient()
    client.start(build_config())
    result = client.malfunction("WaterRS", "MEDIUM_MALF", "PERMANENT_MALF", tick_to_occur=20)
    assert result == "Malfunction scheduled for tick 20"


@responses.activate
def test_client_clear_malfunctions():
    responses.add(responses.POST, f"{BASE}/start", json={"simId": 5}, status=200)
    responses.add(
        responses.DELETE, f"{BASE}/5/modules/WaterRS/malfunctions",
        json={"cleared": True}, status=200,
    )
    client = BioSimClient()
    client.start(build_config())
    result = client.clear_malfunctions("WaterRS")
    assert result["cleared"] is True


# =============================================================================
# Snapshot / metric extraction
# =============================================================================

def test_snapshot_reads_all_expected_levels():
    state = {
        "globals": {"simulationEnded": False},
        "modules": {
            "Food_Store": {"properties": {"currentLevel": 100.0}},
            "Biomass_Store": {"properties": {"currentLevel": 50.0}},
            "Potable_Water_Store": {"properties": {"currentLevel": 20000.0}},
            "O2_Store": {"properties": {"currentLevel": 900.0}},
            "CO2_Store": {"properties": {"currentLevel": 1.0}},
            "Habitat_Power_Store": {"properties": {"currentLevel": 99000.0}},
            "Dry_Waste_Store": {"properties": {"currentLevel": 5.0}},
        },
    }
    rec = snapshot(state, sol=10)
    assert rec.sol == 10
    assert rec.food_store_kcal == 100.0
    assert rec.potable_water_l == 20000.0
    assert rec.crew_alive is True


def test_snapshot_detects_crew_death():
    state = {"globals": {"simulationEnded": True}, "modules": {}}
    rec = snapshot(state, sol=42)
    assert rec.crew_alive is False


def test_snapshot_missing_module_defaults_to_zero():
    """Runbook module-name mismatch case: don't crash, surface a 0 instead."""
    state = {"globals": {"simulationEnded": False}, "modules": {}}
    rec = snapshot(state, sol=1)
    assert rec.food_store_kcal == 0.0


# =============================================================================
# Full scenario run (mocked) + CSV output
# =============================================================================

@responses.activate
def test_run_scenario_end_to_end_mocked(tmp_path):
    responses.add(responses.POST, f"{BASE}/start", json={"simId": 9}, status=200)
    responses.add(responses.POST, f"{BASE}/9/tick", json={"ticks": 1}, status=200)
    responses.add(
        responses.GET, f"{BASE}/9",
        json={
            "globals": {"simulationEnded": False},
            "modules": {"Food_Store": {"properties": {"currentLevel": 500.0}}},
        },
        status=200,
    )
    sc = scenarios()["nominal"]
    sc.sols = 5
    records = run_scenario(sc, base_url=BASE, verbose=False)
    # sol 1 and sol 5 are snapshotted per run_scenario's "sol % 5 == 0 or sol == 1"
    assert [r.sol for r in records] == [1, 5]

    path = write_csv("nominal_test", records, outdir=str(tmp_path))
    assert path.endswith("nominal_test.csv")
    with open(path) as f:
        content = f.read()
    assert "food_store_kcal" in content
    assert "500.0" in content
