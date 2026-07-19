"""
LunaGrow — BioSim configuration generator
==========================================
Generates the BioSim XML configuration for the LunaGrow habitat.

BioSim (github.com/scottbell/biosim) is a NASA JSC / TRACLabs Java simulation of an
integrated Advanced Life Support system. It is started by POSTing an XML configuration
to /api/simulation/start. This module builds that XML from LunaGrow's design values.

Team LunaGrow — Mary Lee Tupling Bergman, DAOM, AP, CNC
NASA Deep Space Food Challenge: Mars to Table
"""

from dataclasses import dataclass, field
from typing import List
from xml.sax.saxutils import escape

# =============================================================================
# LUNAGROW DESIGN CONSTANTS
# Single source of truth. Edit here, not in the XML.
# =============================================================================

CREW_SIZE = 15                    # LunaGrow crew (NOT 4 — earlier exploratory model was wrong)
MISSION_SOLS = 500                # surface stay
KCAL_PER_CREW_SOL = 3035          # canonical; 3502 on EVA sols 5 & 13
KCAL_TOTAL_PER_SOL = CREW_SIZE * KCAL_PER_CREW_SOL   # 45,525 kcal/sol

HABITAT_POWER_KW = 30.0           # habitat power budget
DOME_FLOOR_M2 = 396.0             # two domes, 22 x 9 m each
GROW_AREA_M2 = 320.0              # cultivated area across four vertical tiers

WATER_RECLAMATION_PCT = 91.0      # closed-loop reclamation
WATER_THROUGHPUT_L_PER_SOL = 548.0
CREW_WATER_L_PER_SOL = 32.0       # per-crew total water demand (Mary Bergman, confirmed)
                                  # 15 crew x 32 = 480 L/sol crew throughput

# ---- WATER STARTING STATE ---------------------------------------------------
# DESIGN PREMISE: the arriving crew inherits a FULLY FUNCTIONING system from the
# departing crew. The closed loop is already at steady state on Sol 1 — this is
# NOT a cold start and NOT a landed/payload quantity. Water stores are handed
# over near-full at their normal operating level.
INITIAL_WATER_INVENTORY_L = 28500.0   # ~95% of the 30,000 L potable store capacity
                                      # (near-full handover, small headroom for make-up inflow)
ISRU_MAKEUP_SUPPLY_L_PER_SOL = None    # steady-state make-up; sized by the live run.
_ISRU_MAKEUP_DEFAULT = 55.0            # covers ~30 L/sol crew net loss + other losses
_INITIAL_WATER_DEFAULT = 28500.0
# -----------------------------------------------------------------------------


def isru_makeup() -> float:
    return ISRU_MAKEUP_SUPPLY_L_PER_SOL or _ISRU_MAKEUP_DEFAULT


def initial_water() -> float:
    return INITIAL_WATER_INVENTORY_L or _INITIAL_WATER_DEFAULT


# =============================================================================
# CROP MAPPING
# BioSim models exactly 9 plant types (PlantType.java):
#   WHEAT, DRY_BEAN, LETTUCE, PEANUT, RICE, SOYBEAN, SWEET_POTATO,
#   TOMATO, WHITE_POTATO
# LunaGrow grows more species than BioSim represents, so each LunaGrow crop is
# mapped onto its nearest BioSim analogue. Eight of BioSim's nine types are used.
# =============================================================================

@dataclass
class Shelf:
    crop_type: str      # BioSim PlantType
    area_m2: float      # cultivated area
    represents: str     # LunaGrow crops mapped onto this type


LUNAGROW_SHELVES: List[Shelf] = [
    Shelf("SWEET_POTATO", 96.0, "Sweet potato — dominant caloric crop, four-tier racks"),
    Shelf("RICE",         44.0, "Purple rice (canopy-height limited to two tiers)"),
    Shelf("SOYBEAN",      56.0, "Soy — milk, tofu, tempeh, miso, tamari, yogurt, edamame, isolate"),
    Shelf("WHEAT",        50.0, "Durum wheat + oats, quinoa, amaranth (grain proxy)"),
    Shelf("DRY_BEAN",     34.0, "Chickpea, cannellini, adzuki, lentil, fava, black bean"),
    Shelf("PEANUT",       16.0, "Peanuts — in-situ oil press + peanut butter; N-fixing"),
    Shelf("LETTUCE",      18.0, "Leafy greens — kale, chard, mizuna, bok choy, amaranth greens"),
    Shelf("TOMATO",        6.0, "Tomato + tomatillo + sweet mini peppers (fruiting veg proxy)"),
]

# Systems BioSim does not model — handled outside the sim, noted for the record:
#   tilapia aquaponics, algae photobioreactors (spirulina/chlorella),
#   saline macroalgae, mushroom/vermiculture, Shire fermentation.
# These supply protein/micronutrients and are accounted for in the menu workbook.
OUT_OF_SCOPE = [
    "Tilapia aquaponics (Dome B, Bay 2)",
    "Algae photobioreactors — Spirulina/Chlorella (Dome A, Bay 4)",
    "Warm saline macroalgae — wakame, umi-budo (Dome B, Bay 3)",
    "Mushroom farm / vermiculture (Central Hub, Bay 6)",
    "The Shire fermentation arts (Dome B, Bay 5)",
]


# =============================================================================
# CREW SCHEDULE
# BioSim activity intensities: 0 = sleep .. 5 = heavy exercise.
# =============================================================================

@dataclass
class Activity:
    name: str
    length: int      # hours
    intensity: int


NOMINAL_SCHEDULE = [
    Activity("sleep", 8, 0),
    Activity("leisure", 4, 2),
    Activity("work", 10, 3),
    Activity("exercise", 2, 5),
]

EVA_SCHEDULE = [
    Activity("sleep", 8, 0),
    Activity("leisure", 2, 2),
    Activity("work", 8, 3),
    Activity("eva", 6, 5),      # EVA sols 5 & 13 — 3,502 kcal
]


@dataclass
class CrewPerson:
    name: str
    age: int
    weight: float
    sex: str
    schedule: List[Activity] = field(default_factory=lambda: list(NOMINAL_SCHEDULE))


def default_crew(n: int = CREW_SIZE) -> List[CrewPerson]:
    """15 crew, mixed demographics."""
    out = []
    for i in range(n):
        sex = "MALE" if i % 2 == 0 else "FEMALE"
        weight = 78.0 if sex == "MALE" else 65.0
        out.append(CrewPerson(f"Crew_{i+1:02d}", 30 + (i % 15), weight, sex))
    return out


# =============================================================================
# XML GENERATION
# =============================================================================

def _flow(tag: str, rate: float, store: str, direction: str = "inputs") -> str:
    return (f'<{tag} desiredFlowRates="{rate}" maxFlowRates="{rate}" '
            f'{direction}="{store}"/>')


def build_config(
    crew: List[CrewPerson] = None,
    shelves: List[Shelf] = None,
    power_kw: float = HABITAT_POWER_KW,
    run_till_crew_death: bool = True,
) -> str:
    """Build the LunaGrow BioSim XML configuration."""
    crew = crew if crew is not None else default_crew()
    shelves = shelves if shelves is not None else LUNAGROW_SHELVES

    power_w = power_kw * 1000.0
    # Dome A + Dome B + Hub free volume (m^3 -> litres for SimEnvironment)
    env_volume_l = 396.0 * 4.0 * 1000.0

    crew_xml = []
    for p in crew:
        acts = "".join(
            f'<activity name="{escape(a.name)}" length="{a.length}" intensity="{a.intensity}"/>'
            for a in p.schedule
        )
        crew_xml.append(
            f'<crewPerson name="{escape(p.name)}" age="{p.age}" '
            f'weight="{p.weight}" sex="{p.sex}"><schedule>{acts}</schedule></crewPerson>'
        )

    shelf_xml = "".join(
        f'<!-- {escape(s.represents)} -->'
        f'<shelf cropType="{s.crop_type}" cropArea="{s.area_m2}"/>'
        for s in shelves
    )

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<biosim xmlns="http://www.traclabs.com/biosim"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <!-- ================================================================
       LUNAGROW — Closed-Loop Bioregenerative Food System for Mars
       {CREW_SIZE} crew · {MISSION_SOLS} sols · {KCAL_PER_CREW_SOL} kcal/crew/sol
       Total demand: {KCAL_TOTAL_PER_SOL:,} kcal/sol
       IP: Mary Lee Tupling Bergman, DAOM, AP, CNC
       ================================================================ -->
  <Globals driverStutterLength="500" crewsToWatch="LunaGrow_Crew"
           runTillCrewDeath="{str(run_till_crew_death).lower()}"
           tickLength="1" startPaused="false"/>
  <SimBioModules>

    <environment>
      <SimEnvironment moduleName="LunaGrow_Habitat" initialVolume="{env_volume_l:.0f}"/>
    </environment>

    <air>
      <CO2Store capacity="5000" moduleName="CO2_Store" level="0"/>
      <O2Store  capacity="20000" moduleName="O2_Store"  level="5000"/>
      <H2Store  capacity="10000" moduleName="H2_Store"  level="0"/>
      <NitrogenStore capacity="5000" moduleName="Nitrogen_Store" level="1000"/>
      <MethaneStore  capacity="1000" moduleName="Methane_Store"  level="0"/>

      <!-- CO2 removal -->
      <VCCR moduleName="VCCR">
        {_flow("powerConsumer", 1500, "Habitat_Power_Store")}
        {_flow("airConsumer", 1000.0, "LunaGrow_Habitat")}
        {_flow("airProducer", 1000.0, "LunaGrow_Habitat", "outputs")}
        {_flow("CO2Producer", 1000.0, "CO2_Store", "outputs")}
      </VCCR>

      <!-- O2 generation (electrolysis) -->
      <OGS moduleName="OGS">
        {_flow("powerConsumer", 1500, "Habitat_Power_Store")}
        {_flow("potableWaterConsumer", 20, "Potable_Water_Store")}
        {_flow("O2Producer", 1000, "O2_Store", "outputs")}
        {_flow("H2Producer", 1000, "H2_Store", "outputs")}
      </OGS>
    </air>

    <water>
      <!-- Initial inventory: PENDING ENGINEER CONFIRMATION -->
      <PotableWaterStore capacity="30000" moduleName="Potable_Water_Store"
                         level="{initial_water():.0f}"/>
      <GreyWaterStore  capacity="15000" moduleName="Grey_Water_Store"  level="2000"/>
      <DirtyWaterStore capacity="15000" moduleName="Dirty_Water_Store" level="0"/>

      <!-- Water recovery: {WATER_RECLAMATION_PCT}% reclamation, ~{WATER_THROUGHPUT_L_PER_SOL} L/sol -->
      <WaterRS moduleName="WaterRS">
        {_flow("powerConsumer", 1200, "Habitat_Power_Store")}
        {_flow("dirtyWaterConsumer", 300, "Dirty_Water_Store")}
        {_flow("greyWaterConsumer", 300, "Grey_Water_Store")}
        {_flow("potableWaterProducer", 550, "Potable_Water_Store", "outputs")}
      </WaterRS>
    </water>

    <power>
      <PowerStore capacity="{power_w * 4:.0f}" moduleName="Habitat_Power_Store"
                  level="{power_w * 2:.0f}"/>
      <PowerPS moduleName="Nuclear_Source" generationType="NUCLEAR">
        {_flow("powerProducer", power_w, "Habitat_Power_Store", "outputs")}
      </PowerPS>
    </power>

    <food>
      <FoodStore    capacity="200000" level="60000" moduleName="Food_Store"/>
      <BiomassStore capacity="100000" level="20000" moduleName="Biomass_Store"/>

      <!-- LunaGrow grow systems: {GROW_AREA_M2} m2 across four vertical tiers.
           BioSim models 9 plant types; LunaGrow crops are mapped to the nearest. -->
      <BiomassPS moduleName="LunaGrow_Biomass" autoHarvestAndReplant="true">
        {shelf_xml}
        {_flow("powerConsumer", 12000, "Habitat_Power_Store")}
        {_flow("potableWaterConsumer", 400, "Potable_Water_Store")}
        {_flow("greyWaterConsumer", 200, "Grey_Water_Store")}
        {_flow("airConsumer", 500, "LunaGrow_Habitat")}
        {_flow("dirtyWaterProducer", 200, "Dirty_Water_Store", "outputs")}
        {_flow("biomassProducer", 400, "Biomass_Store", "outputs")}
        {_flow("airProducer", 500, "LunaGrow_Habitat", "outputs")}
      </BiomassPS>

      <!-- Cookoon Kitchen: biomass -> edible food -->
      <FoodProcessor moduleName="Cookoon_Kitchen">
        {_flow("powerConsumer", 800, "Habitat_Power_Store")}
        {_flow("biomassConsumer", 400, "Biomass_Store")}
        {_flow("foodProducer", 400, "Food_Store", "outputs")}
        {_flow("dryWasteProducer", 40, "Dry_Waste_Store", "outputs")}
        {_flow("waterProducer", 50, "Dirty_Water_Store", "outputs")}
      </FoodProcessor>
    </food>

    <waste>
      <DryWasteStore capacity="500000" moduleName="Dry_Waste_Store" level="0"/>
      <!-- Vermiculture analogue: returns N/P to the grow loop -->
      <Incinerator moduleName="Vermiculture_Bay6">
        {_flow("powerConsumer", 300, "Habitat_Power_Store")}
        {_flow("O2Consumer", 10, "O2_Store")}
        {_flow("dryWasteConsumer", 40, "Dry_Waste_Store")}
        {_flow("CO2Producer", 10, "CO2_Store", "outputs")}
      </Incinerator>
    </waste>

    <crew>
      <CrewGroup moduleName="LunaGrow_Crew">
        {_flow("potableWaterConsumer", CREW_SIZE * CREW_WATER_L_PER_SOL, "Potable_Water_Store")}
        {_flow("airConsumer", 0, "LunaGrow_Habitat")}
        {_flow("foodConsumer", CREW_SIZE * 2.5, "Food_Store")}
        {_flow("dirtyWaterProducer", CREW_SIZE * 8.0, "Dirty_Water_Store", "outputs")}
        {_flow("greyWaterProducer", CREW_SIZE * 22.0, "Grey_Water_Store", "outputs")}
        {_flow("airProducer", 0, "LunaGrow_Habitat", "outputs")}
        {_flow("dryWasteProducer", CREW_SIZE * 0.5, "Dry_Waste_Store", "outputs")}
        {"".join(crew_xml)}
      </CrewGroup>
    </crew>

  </SimBioModules>
</biosim>'''


if __name__ == "__main__":
    xml = build_config()
    print(xml)
    print(f"\n<!-- {len(xml)} chars · {CREW_SIZE} crew · "
          f"{sum(s.area_m2 for s in LUNAGROW_SHELVES)} m2 planted -->")
