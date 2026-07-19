# Running the LunaGrow BioSim stack

This documents how to build and run the full docker-compose stack in
`lunagrow_project/` on Windows, including the fixes that were needed to
get it working (upstream URLs are broken on this platform/tooling as
shipped).

## Stack overview

`docker-compose.yml` defines three services:

- **biosim-server** — the real BioSim Java REST server (Maven/Eclipse
  Temurin JDK 21), listens on `:8009`.
- **openmct-biosim** — an Open MCT plugin + the Open MCT web app itself,
  served by nginx on `:9091`. This is what you open in a browser.
- **lunagrow-client** — the Python scenario runner. Waits for
  biosim-server, drives simulations, writes `results/*.csv`.

## Prerequisites

- Docker Desktop running (`docker info` should succeed).
- No other process needs ports `8009` or `9091`.

## Build and run

```bash
cd lunagrow_project
docker compose up --build
```

Open **http://localhost:9091/** once `openmct-biosim` and
`biosim-server` report as started.

To just check status / logs without rebuilding:

```bash
docker compose ps
docker compose logs -f openmct-biosim
```

## Fixes already applied (why they were necessary)

1. **`docker-compose.yml` build contexts changed from git URLs to local
   dirs.** The original file built `biosim-server` and `openmct-biosim`
   from `https://github.com/...git` contexts. Docker Compose v5.0.2 on
   Windows mis-parses these as local paths (`failed to evaluate path
   "https://...": CreateFile ... https:: The filename ... is
   incorrect`), even with `COMPOSE_BAKE=false`. Both vendored source
   dirs (`biosim/`, `openmct-biosim/`) already exist in this repo, so
   `context:` now points at them directly (`./biosim`, `./openmct-biosim`).
   Plain `docker build <git-url>` works fine — this is specifically a
   Compose/buildx-bake parsing bug.

2. **`openmct-biosim/Dockerfile` builder image bumped `node:20-alpine`
   → `node:24-alpine`.** Upstream `nasa/openmct` (installed at
   `#master`) now requires Node `>=24` in its own `package.json`
   engines field; under Node 20 its own build silently produced no
   usable output.

3. **`openmct-biosim/Dockerfile` builds `nasa/openmct`'s own `dist/`
   from a full clone, not from the npm-installed copy.** Installing
   `nasa/openmct#master` via `npm install` (as the plugin's own
   `build:prod` script does) only pulls the files allowed by its
   `.npmignore` — which excludes `.webpack/` and any prebuilt `dist/`.
   So `node_modules/openmct/dist` never gets created and the final
   `COPY --from=builder .../node_modules/openmct/dist/ ...` step fails.
   Fix: separately `git clone --depth 1 https://github.com/nasa/openmct`,
   `npm install`, `npm run build:prod` there, then move that `dist/`
   into `node_modules/openmct/dist` before the nginx stage copies it out.

4. **Memory**: building `nasa/openmct` with the production webpack
   config is memory-hungry. If it OOM-kills (exit 137) during
   `docker compose build`, it's almost always resource contention from
   *other* concurrent builds/containers on the Docker Desktop VM (which
   has a fixed total memory, e.g. ~7.7GiB) — stop unrelated containers
   or wait for other builds to finish, then retry. `build:dev` also
   works as a lower-memory fallback but should not be needed once other
   builds have finished.

5. **UI fix**: `openmct-biosim/Dockerfile` clones
   `github.com/scottbell/openmct-biosim` fresh on every build — so any
   local edits under `openmct-biosim/etc/` or `openmct-biosim/src/` are
   silently discarded unless explicitly re-applied. The Dockerfile now
   has an explicit `COPY etc/prod/index.html ./etc/prod/index.html`
   step right after the clone to layer local changes back on top
   (currently: a defensive CSS reset — full-height `html body #app
   .l-shell`, `box-sizing: border-box`, a viewport meta tag — added
   because the shell rendered with broken alignment otherwise).
   **If you edit any other file that upstream's clone also provides,
   add a matching `COPY` line for it, or the edit will not take
   effect.**

## Fixed: `lunagrow-client` 500 error on simulation start

`lunagrow-client` used to exit with `500 Server Error` on
`POST /api/simulation/start`, with `biosim-server` logging a
`NullPointerException` in `SimulationInitializer.createSchedule`.

Root cause (in **our** `lunagrow_biosim/config.py`, not BioSim itself):
BioSim's `createCrewPerson` locates a `<crewPerson>`'s `<schedule>` via
`node.getFirstChild().getNextSibling()` — it only works if the first
child of `<crewPerson>` is a whitespace text node and `<schedule>` is
the *second* child (true for pretty-printed XML, e.g. the working
example configs under `biosim/configuration/`). Our generator emitted
`<crewPerson ...><schedule>...` with no whitespace in between, so
`<schedule>` was the *first* child and `.getNextSibling()` returned
`null` → NPE.

Fix: `config.py` now emits a leading `"\n"` before `<schedule>` inside
each `<crewPerson>` so the DOM shape matches what BioSim's parser
expects. Verified: all 8 scenarios (`nominal`, `crew_reduced`,
`crew_expanded`, `power_reduced`, `power_fault`, `crop_loss`,
`water_fault`, `ogs_fault`) now run to completion and write CSVs to
`results/`, with a JSON summary printed at the end (and saved to
`results/summary.json`).

Rebuild `lunagrow-client` after editing `config.py`/`run.py` — it's a
plain `COPY`-based Dockerfile (unlike `openmct-biosim`'s, see above),
so local edits are picked up on rebuild automatically:

```bash
docker compose build lunagrow-client
docker compose run --rm lunagrow-client --scenario all --sols 100 \
    --url http://biosim-server:8009/api/simulation
```


Producing the 8 scenarios
Once docker compose up --build is running (BioSim server up on port 8009), open a second terminal/PowerShell window in the same lunagrow_project folder and run:
powershelldocker compose run lunagrow-client --scenario all --sols 500
This runs all 8 scenarios back-to-back: nominal, crew_reduced, crew_expanded, power_reduced, power_fault, crop_loss, water_fault, ogs_fault. Each one starts a fresh sim, ticks it forward, and writes a CSV to results/.
If you'd rather run them one at a time (useful for debugging or if one scenario is slow):
powershelldocker compose run lunagrow-client --scenario nominal --sols 500
docker compose run lunagrow-client --scenario power_fault --sols 500
# ...and so on for each name above
When it's done, check the results folder on your host machine (it's mounted as a volume) — you should see 8 CSVs, one per scenario, plus a JSON summary printed to the terminal.
What the Open MCT screenshot is
Open MCT (Mission Control Technologies) is NASA's real-time telemetry dashboard — it's the second service in your compose file (openmct-biosim), and it's what actually visualizes the BioSim run: line graphs of food store, water levels, O2/CO2, power, etc., live as the simulation ticks.
To get the screenshot:

While a scenario is running (or right after), open a browser to http://localhost:9091
It'll show a dashboard with BioSim's telemetry channels — add/select the ones you care about (food, water, O2, power are the usual suspects for the Challenge writeup)
Let it plot through a run of the nominal scenario, then take a screenshot of the graphs

That screenshot is what shows a reviewer the system holding steady (or degrading, for the fault scenarios) over the mission — it's the visual proof-of-life for the write-up, alongside the CSV data.