"""Write a chatterbox simulation trace to JSON.

Examples:
  python tools/chatterbox_export_example.py
  python tools/chatterbox_export_example.py --backend star
  python tools/chatterbox_export_example.py --full
  python tools/chatterbox_export_example.py --output /tmp/plr_trace.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from pylabrobot.liquid_handling import LiquidHandler  # noqa: E402
from pylabrobot.liquid_handling.backends.chatterbox import (  # noqa: E402
  LiquidHandlerChatterboxBackend,
)
from pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox import (  # noqa: E402
  STARChatterboxBackend,
)
from pylabrobot.resources import (  # noqa: E402
  Coordinate,
  Cor_96_wellplate_360ul_Fb,
  hamilton_96_tiprack_1000uL_filter,
)
from pylabrobot.resources.hamilton import STARLetDeck  # noqa: E402


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Export a chatterbox deck layout and trace to JSON.")
  parser.add_argument(
    "--backend",
    choices=["generic", "star"],
    default="generic",
    help="Which chatterbox backend to use.",
  )
  parser.add_argument(
    "--output",
    type=Path,
    default=Path("test_logs/chatterbox_trace.json"),
    help="Path to the output JSON file.",
  )
  parser.add_argument(
    "--full",
    action="store_true",
    help="Write the verbose debug export instead of the compact simulation export.",
  )
  parser.add_argument(
    "--include-firmware-commands",
    action="store_true",
    help="Include raw STAR firmware commands in compact output.",
  )
  return parser.parse_args()


async def run(
  backend_name: str,
  output: Path,
  compact: bool,
  include_firmware_commands: bool,
) -> None:
  deck = STARLetDeck()
  if backend_name == "star":
    backend = STARChatterboxBackend()
  else:
    backend = LiquidHandlerChatterboxBackend(num_channels=8)

  lh = LiquidHandler(backend=backend, deck=deck)

  tip_rack = hamilton_96_tiprack_1000uL_filter(name="tip_rack")
  plate = Cor_96_wellplate_360ul_Fb(name="plate")
  deck.assign_child_resource(tip_rack, rails=3)
  deck.assign_child_resource(plate, rails=9)

  await lh.setup()
  try:
    await lh.pick_up_tips(tip_rack["A1"])
    await lh.aspirate(plate["A1"], vols=[10])
    await lh.dispense(plate["B1"], vols=[10], offsets=[Coordinate.zero()])
    payload = backend.export_for_simulation(
      compact=compact,
      include_firmware_commands=include_firmware_commands,
    )
  finally:
    await lh.stop()

  output.parent.mkdir(parents=True, exist_ok=True)
  output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

  print(f"Wrote {output}")
  print(f"Backend: {backend_name}")
  print(f"Compact: {compact}")
  if compact:
    print(f"Deck resources: {len(payload['deck']['resources'])}")
  else:
    print(f"Top-level deck children: {[child['name'] for child in payload['deck']['children']]}")
  print(f"Event count: {len(payload['events'])}")


def main() -> None:
  args = parse_args()
  asyncio.run(
    run(
      backend_name=args.backend,
      output=args.output,
      compact=not args.full,
      include_firmware_commands=args.include_firmware_commands,
    )
  )


if __name__ == "__main__":
  main()
