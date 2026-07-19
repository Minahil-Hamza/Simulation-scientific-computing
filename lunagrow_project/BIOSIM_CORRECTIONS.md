# LunaGrow BioSim — Review, Corrections & Verification

**Reviewed against the real BioSim source** (github.com/scottbell/biosim, cloned fresh):
the XML Schema (`etc/schema/**`), the plant enum (`PlantType.java`), and the live REST
handlers (`SimulationController.java`). Not by eyeballing — by validating generated XML
with `xmllint` against the actual `.xsd`, and by reading each endpoint's handler code.

**Headline:** the prior "schema-verified for all 8 scenarios" claim did **not** hold. The
base config failed schema validation, and every off-nominal (fault) scenario would have
crashed the runner. Both classes of bug are now fixed and verified. All 8 scenarios now
validate against the real schema.

---

## What was actually broken

### 1. Config XML failed the real schema (would 400 on `POST /start`)

| # | Module | Problem | Fix |
|---|--------|---------|-----|
| A | `FoodProcessor` (Cookoon Kitchen) | child order `foodProducer → waterProducer → dryWasteProducer`. Schema (`Food.xsd`, `FoodProcessorType`) requires `… → dryWasteProducer → waterProducer`. | swapped to schema order |
| B | Waste module named `IncineratorPS` | No such element. The waste processor is `Incinerator` (`Waste.xsd`, `IncineratorType`). `…PS` would be rejected. | renamed `IncineratorPS → Incinerator` |
| C | `Incinerator` child order `powerConsumer → dryWasteConsumer → O2Consumer → CO2Producer` | Schema requires `powerConsumer → O2Consumer → dryWasteConsumer → CO2Producer`. | swapped `O2Consumer`/`dryWasteConsumer` |

XSD element ordering is strict `xsd:sequence` — order alone is enough to fail validation,
even when every child is present. `xmllint --schema BiosimInitSchema.xsd` now passes for
nominal, crew_reduced, crew_expanded, power_reduced, power_fault, crop_loss, water_fault,
and ogs_fault.

### 2. Runner crashed on every fault scenario (KeyError)

`BioSimClient.malfunction()` did `return r.json()["malfunctionID"]`. But
`SimulationController.postMalfunction` returns **two different shapes**:

- immediate malfunction (no `tickToOccur`) → `{"malfunctionID": <id>}`
- **scheduled** malfunction (`tickToOccur` set) → `{"message": "Malfunction scheduled…"}`

All three fault scenarios (`power_fault`, `water_fault`, `ogs_fault`) schedule with
`tickToOccur`, so they'd all hit `KeyError: 'malfunctionID'` and abort. Fixed to accept
either shape.

---

## What was already correct (verified, not assumed)

- Root/namespace, `Globals`, `SimBioModules` grouping — OK.
- Store/PS module names: `SimEnvironment, CO2Store, O2Store, H2Store, NitrogenStore, MethaneStore, VCCR, OGS, PotableWaterStore, GreyWaterStore, DirtyWaterStore, WaterRS, PowerStore, PowerPS, FoodStore, BiomassStore, BiomassPS, FoodProcessor, DryWasteStore, CrewGroup` — all present in the schema.
- `BiomassPS` child order and `shelf cropType/cropArea` attributes — OK.
- All 8 `cropType` values are valid `CropType` enum members.
- Malfunction enum strings `SEVERE_MALF / MEDIUM_MALF / LOW_MALF / TEMPORARY_MALF / PERMANENT_MALF` — exact matches.
- REST contract: `POST /start → {"simId"}`, `POST /{id}/tick → {"ticks"}`,
  `GET /{id} → {globals, modules}`, store `properties.currentLevel`,
  `globals.simulationEnded`, consumer/producer bodies (`desiredFlowRates`, `connections`).
  All match the handlers.

A mocked end-to-end (server-shaped JSON, no live server) confirms `snapshot()` parses real
values and the malfunction fix no longer raises.

---

## What I did NOT touch — needs your confirmation (design IP, per Runbook §6)

These are **your** mission-design numbers, not mine to set. Runbook §6 marks them
"do not change without asking." Placeholders are in place so the pipeline runs; confirm or
replace before the numbers are cited anywhere:

1. `ISRU_MAKEUP_SUPPLY_L_PER_SOL` — placeholder **55.0** L/sol (≈9% of 548 L/sol throughput)
2. `INITIAL_WATER_INVENTORY_L` — placeholder **20000.0** L
3. `LUNAGROW_SHELVES` — the crop→BioSim-analogue mapping and per-shelf areas (sum = 320 m²)

If the water balance looks off in the results, items 1–2 are the first suspects.

**On `config.py` provenance:** the runbook says your `config.py` was already "written and
tested," but the file uploaded to this project *is* a working scaffold (with the bugs above),
not an empty placeholder — so I corrected the real file rather than inventing one. If you
have a different "real" config.py, diff it against this one; the three schema fixes above
still apply to it.

---

## Two notes (judgment calls, not bugs — your call)

- **Tick vs. sol semantics.** The runner treats one `tick` as one sol and schedules
  malfunctions at `tickToOccur = 30/20/40`. BioSim's native tick is finer-grained
  (crew activity lengths are in hours, summing to 24). The survival/trend checks are robust
  to this, but if you want malfunctions to fire on a specific *sol*, the tick↔sol mapping is
  a modeling decision to confirm with whoever validates the run.
- **`food_store_kcal` column label.** The CSV reads the FoodStore's `currentLevel`, which is
  BioSim's internal food unit, not literally kcal. Fine for the "rising/stable vs. falling"
  trend check the runbook asks for; just don't quote the raw number as kcal.

---

## Files in this delivery

```
lunagrow_biosim/
  __init__.py          (makes `python -m lunagrow_biosim.run` work — the runbook's invocation
                         needs the files inside this package folder; flat files break the
                         `from .config import` relative import)
  config.py            corrected (fixes A, B, C)
  run.py               corrected (malfunction response handling)
  requirements.txt
validate_scenarios.py  offline check: validates all 8 scenarios against the bundled schema
                       via xmllint — run this BEFORE standing up Docker to catch config
                       regressions early.
```

### Quick offline check (no server, no Docker)
```bash
pip install requests
# point validate_scenarios.py at your local clone's schema, then:
python validate_scenarios.py        # expect: ALL SCENARIOS VALIDATE
python -m lunagrow_biosim.run --print-config   # prints the XML, no server needed
```

### Then the real run (unchanged from runbook)
```bash
git clone https://github.com/scottbell/biosim.git && cd biosim && docker compose up
# in another shell, from the folder containing lunagrow_biosim/:
python -m lunagrow_biosim.run --scenario all --sols 100
# results in results/*.csv
```

---

*Generative AI was used to assist in drafting the narrative and visualizing the habitat
layout. All AI-generated outputs have been reviewed and verified. IP © Mary Lee Tupling
Bergman, DAOM.*
