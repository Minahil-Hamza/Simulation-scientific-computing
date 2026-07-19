# Simulation-scienLunaGrow — BioSim Scenario Runner

A Python REST client that drives NASA BioSim to
model the LunaGrow closed-loop bioregenerative food system for a Mars surface habitat.

The client builds BioSim's XML configuration from LunaGrow's design values, starts a
simulation over the REST API, advances it sol by sol, injects malfunctions for the
off-nominal cases, and writes per-scenario CSV results.


Team LunaGrow — Mary Lee Tupling Bergman, DAOM, AP, CNC
NASA Deep Space Food Challenge: Mars to Table




What this is (and is not)

BioSim is a Java simulation of an integrated Advanced Life Support system, developed at
NASA Johnson Space Center with TRACLabs. It exposes a RESTful API, which means it can be
driven from any HTTP-capable language.

This repository does not reimplement BioSim. It is a thin client that configures and
drives the real upstream server. docker-compose.yml builds BioSim straight from source
as a sibling service, so the physics stays authoritative and only the habitat design is
ours.tific-computing
