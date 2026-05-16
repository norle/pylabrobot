import json
import unittest

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import (
  LiquidHandlerChatterboxBackend,
)
from pylabrobot.resources import (
  Coordinate,
  Cor_96_wellplate_360ul_Fb,
  hamilton_96_tiprack_1000uL_filter,
)
from pylabrobot.resources.hamilton import STARLetDeck


class ChatterboxBackendTests(unittest.IsolatedAsyncioTestCase):
  """Tests for chatterbox backend"""

  def setUp(self) -> None:
    self.deck = STARLetDeck()
    self.backend = LiquidHandlerChatterboxBackend(num_channels=8)
    self.lh = LiquidHandler(self.backend, deck=self.deck)
    self.tip_rack = hamilton_96_tiprack_1000uL_filter(name="tip_rack")
    self.deck.assign_child_resource(self.tip_rack, rails=3)
    self.plate = Cor_96_wellplate_360ul_Fb(name="plate")
    self.deck.assign_child_resource(self.plate, rails=9)

  async def asyncSetUp(self) -> None:
    await super().asyncSetUp()
    await self.lh.setup()

  async def asyncTearDown(self) -> None:
    await self.lh.stop()
    await super().asyncTearDown()

  async def test_pick_up_tips(self):
    await self.lh.pick_up_tips(self.tip_rack["A1"])

  async def test_drop_tips(self):
    await self.lh.pick_up_tips(self.tip_rack["A1"])
    await self.lh.drop_tips(self.tip_rack["A1"])

  async def test_pick_up_tips96(self):
    await self.lh.pick_up_tips96(self.tip_rack)

  async def test_drop_tips96(self):
    await self.lh.pick_up_tips96(self.tip_rack)
    await self.lh.drop_tips96(self.tip_rack)

  async def test_aspirate(self):
    await self.lh.pick_up_tips(self.tip_rack["A1"])
    await self.lh.aspirate(self.plate["A1"], vols=[10])

  async def test_dispense(self):
    await self.lh.pick_up_tips(self.tip_rack["A1"])
    await self.lh.dispense(self.plate["A1"], vols=[10])

  async def test_aspirate96(self):
    await self.lh.pick_up_tips96(self.tip_rack)
    await self.lh.aspirate96(self.plate, volume=10)

  async def test_dispense96(self):
    await self.lh.pick_up_tips96(self.tip_rack)
    await self.lh.aspirate96(self.plate, volume=10)
    await self.lh.dispense96(self.plate, volume=10)

  async def test_move(self):
    await self.lh.move_resource(self.plate, Coordinate(0, 0, 0))

  async def test_export_for_simulation(self):
    await self.lh.pick_up_tips(self.tip_rack["A1"])
    await self.lh.aspirate(self.plate["A1"], vols=[10])

    export = self.backend.export_for_simulation()
    json.dumps(export)

    self.assertEqual(export["deck"]["name"], "deck")
    child_names = [child["name"] for child in export["deck"]["children"]]
    self.assertIn("tip_rack", child_names)
    self.assertIn("plate", child_names)

    operation_events = [event for event in export["events"] if event["event"] == "operation"]
    self.assertTrue(any(event["action"] == "pick_up_tips" for event in operation_events))
    self.assertTrue(any(event["action"] == "aspirate" for event in operation_events))

    instruction_events = [event for event in export["events"] if event["event"] == "instruction"]
    self.assertTrue(any(event["instruction"] == "move_xy" for event in instruction_events))
    self.assertTrue(any(event["instruction"] == "aspirate" for event in instruction_events))

  async def test_compact_export_for_simulation(self):
    await self.lh.pick_up_tips(self.tip_rack["A1"])
    await self.lh.aspirate(self.plate["A1"], vols=[10])

    export = self.backend.export_for_simulation(compact=True)
    json.dumps(export)

    self.assertEqual(export["deck"]["root"], "deck")
    self.assertIn("tip_rack", export["deck"]["resources"])
    self.assertIn("plate_well_A1", export["deck"]["resources"])

    operation_events = [event for event in export["events"] if event["event"] == "operation"]
    aspiration = next(event for event in operation_events if event["action"] == "aspirate")
    self.assertEqual(aspiration["channels"][0]["resource"], "plate_well_A1")
    self.assertEqual(len(aspiration["channels"][0]["target"]), 3)
    self.assertNotIn("resource_origin", aspiration["channels"][0])

  async def test_liquid_tracking_composition_transfer(self):
    self.backend.enable_liquid_tracking(True)
    self.backend.set_liquid_tracking_state(
      self.plate["A1"],
      components={"dye": 20, "water": 80},
      total_volume=100,
    )
    self.backend.set_liquid_tracking_state(
      self.plate["A2"],
      components={"water": 50},
      total_volume=50,
    )

    await self.lh.pick_up_tips(self.tip_rack["A1"])
    await self.lh.aspirate(self.plate["A1"], vols=[10])
    await self.lh.dispense(self.plate["A2"], vols=[10])

    state = self.backend.get_liquid_tracking_state()
    source = state["resources"]["plate_well_A1"]
    destination = state["resources"]["plate_well_A2"]
    tip = state["tips"]["channel:0"]

    self.assertAlmostEqual(source["total_volume"], 90.0)
    self.assertAlmostEqual(source["components"]["dye"], 18.0)
    self.assertAlmostEqual(source["components"]["water"], 72.0)
    self.assertAlmostEqual(source["concentrations"]["dye"], 0.2)

    self.assertAlmostEqual(destination["total_volume"], 60.0)
    self.assertAlmostEqual(destination["components"]["dye"], 2.0)
    self.assertAlmostEqual(destination["components"]["water"], 58.0)
    self.assertAlmostEqual(destination["concentrations"]["dye"], 2.0 / 60.0)

    self.assertAlmostEqual(tip["total_volume"], 0.0)

    export = self.backend.export_for_simulation(compact=True)
    self.assertIn("liquid_tracking", export)
    self.assertFalse(self._contains_key(export["events"], "liquid_transfer"))

    transfer_export = self.backend.export_for_simulation(
      compact=True,
      liquid_tracking="transfers",
    )
    self.assertNotIn("liquid_tracking", transfer_export)
    self.assertTrue(self._contains_key(transfer_export["events"], "liquid_transfer"))

    omitted_export = self.backend.export_for_simulation(
      compact=True,
      liquid_tracking="none",
    )
    self.assertNotIn("liquid_tracking", omitted_export)
    self.assertFalse(self._contains_key(omitted_export["events"], "liquid_transfer"))

  def _contains_key(self, value, key: str) -> bool:
    if isinstance(value, dict):
      return key in value or any(self._contains_key(item, key) for item in value.values())
    if isinstance(value, list):
      return any(self._contains_key(item, key) for item in value)
    return False
