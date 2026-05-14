from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence, Union

from pylabrobot.liquid_handling.standard import (
  Drop,
  DropTipRack,
  MultiHeadAspirationContainer,
  MultiHeadAspirationPlate,
  MultiHeadDispenseContainer,
  MultiHeadDispensePlate,
  Pickup,
  PickupTipRack,
  SingleChannelAspiration,
  SingleChannelDispense,
)
from pylabrobot.resources import Container, Coordinate, Resource
from pylabrobot.resources.rotation import Rotation

PipettingOp = Union[Pickup, Drop, SingleChannelAspiration, SingleChannelDispense]
Head96Op = Union[
  PickupTipRack,
  DropTipRack,
  MultiHeadAspirationPlate,
  MultiHeadAspirationContainer,
  MultiHeadDispensePlate,
  MultiHeadDispenseContainer,
]


class ChatterboxTraceMixin:
  """Helpers for exposing deck geometry and execution traces for simulation."""

  def _init_trace(self) -> None:
    self._command_log: List[Dict[str, Any]] = []

  def clear_trace(self) -> None:
    self._command_log.clear()

  def clear_command_log(self) -> None:
    self.clear_trace()

  def get_trace(self) -> List[Dict[str, Any]]:
    return copy.deepcopy(self._command_log)

  def get_command_log(self) -> List[Dict[str, Any]]:
    return self.get_trace()

  def export_simulation_trace(
    self,
    include_deck_layout: bool = True,
    compact: bool = False,
    include_firmware_commands: bool = False,
  ) -> Dict[str, Any]:
    events = self.get_trace()
    if compact:
      events = self._compact_events(events, include_firmware_commands=include_firmware_commands)
    elif not include_firmware_commands:
      events = [event for event in events if event.get("event") != "firmware_command"]

    data: Dict[str, Any] = {"events": events}
    if include_deck_layout:
      if compact:
        data["deck"] = {
          "root": self.deck.name,
          "resources": self.get_compact_deck_layout(),
        }
      else:
        data["deck"] = self.get_deck_layout()
    return data

  def export_for_simulation(
    self,
    include_deck_layout: bool = True,
    compact: bool = False,
    include_firmware_commands: bool = False,
  ) -> Dict[str, Any]:
    return self.export_simulation_trace(
      include_deck_layout=include_deck_layout,
      compact=compact,
      include_firmware_commands=include_firmware_commands,
    )

  def get_deck_layout(self, include_children: bool = True) -> Dict[str, Any]:
    return self._resource_to_dict(self.deck, include_children=include_children)

  def get_compact_deck_layout(self) -> Dict[str, Dict[str, Any]]:
    resources = [self.deck, *self.deck.get_all_resources()]
    return {resource.name: self._resource_to_compact_dict(resource) for resource in resources}

  def _record_event(self, event: str, **data: Any) -> None:
    self._command_log.append({"event": event, **self._json_safe(data)})

  def _record_setup_event(self) -> None:
    self._record_event("lifecycle", action="setup")

  def _record_stop_event(self) -> None:
    self._record_event("lifecycle", action="stop")

  def _record_liquid_handler_operation(
    self,
    action: str,
    ops: Sequence[PipettingOp],
    use_channels: Sequence[int],
    backend_kwargs: Optional[Dict[str, Any]] = None,
  ) -> None:
    channels = [
      self._op_to_channel_payload(op=op, channel=channel) for op, channel in zip(ops, use_channels)
    ]
    self._record_event(
      "operation",
      action=action,
      channels=channels,
      backend_kwargs=backend_kwargs or {},
    )
    self._record_simulated_channel_instructions(action=action, channels=channels)

  def _record_head96_operation(
    self,
    action: str,
    op: Head96Op,
    resource: Resource,
    extra: Optional[Dict[str, Any]] = None,
  ) -> None:
    target = self._resource_target(resource=resource, offset=op.offset)
    self._record_event(
      "operation",
      action=action,
      head="head96",
      resource=self._resource_brief(resource),
      offset=self._coordinate_to_dict(op.offset),
      target=self._coordinate_to_dict(target),
      extra=extra or {},
    )

    safe_z = self._safe_travel_z()
    self._record_event(
      "instruction",
      instruction="move_z",
      head="head96",
      phase="raise",
      simulated=True,
      target={"z": safe_z},
    )
    self._record_event(
      "instruction",
      instruction="move_xy",
      head="head96",
      simulated=True,
      target={"x": target.x, "y": target.y},
    )
    self._record_event(
      "instruction",
      instruction="move_z",
      head="head96",
      phase="lower",
      simulated=True,
      target={"z": target.z},
    )
    self._record_event(
      "instruction",
      instruction=action,
      head="head96",
      simulated=True,
      target=self._coordinate_to_dict(target),
      extra=extra or {},
    )
    self._record_event(
      "instruction",
      instruction="move_z",
      head="head96",
      phase="raise",
      simulated=True,
      target={"z": safe_z},
    )

  def _record_simulated_channel_instructions(
    self,
    action: str,
    channels: Sequence[Dict[str, Any]],
  ) -> None:
    safe_z = self._safe_travel_z()
    for channel_payload in channels:
      target = channel_payload["target"]
      channel = channel_payload["channel"]
      self._record_event(
        "instruction",
        instruction="move_z",
        channel=channel,
        phase="raise",
        simulated=True,
        target={"z": safe_z},
      )
      self._record_event(
        "instruction",
        instruction="move_xy",
        channel=channel,
        simulated=True,
        target={"x": target["x"], "y": target["y"]},
      )
      self._record_event(
        "instruction",
        instruction="move_z",
        channel=channel,
        phase="lower",
        simulated=True,
        target={"z": target["z"]},
      )
      execute_payload = {
        "instruction": action.rstrip("s"),
        "channel": channel,
        "simulated": True,
        "target": target,
      }
      if "volume" in channel_payload:
        execute_payload["volume"] = channel_payload["volume"]
      self._record_event("instruction", **execute_payload)
      self._record_event(
        "instruction",
        instruction="move_z",
        channel=channel,
        phase="raise",
        simulated=True,
        target={"z": safe_z},
      )

  def _op_to_channel_payload(self, op: PipettingOp, channel: int) -> Dict[str, Any]:
    resource = op.resource
    payload: Dict[str, Any] = {
      "channel": channel,
      "resource": self._resource_brief(resource),
      "offset": self._coordinate_to_dict(op.offset),
      "resource_origin": self._coordinate_to_dict(resource.get_absolute_location()),
      "resource_center": self._coordinate_to_dict(
        resource.get_absolute_location(x="c", y="c", z="c")
      ),
      "target": self._coordinate_to_dict(self._op_target(op)),
    }

    if isinstance(op, (SingleChannelAspiration, SingleChannelDispense)):
      payload["volume"] = op.volume
      payload["flow_rate"] = op.flow_rate
      payload["liquid_height"] = op.liquid_height
      payload["blow_out_air_volume"] = op.blow_out_air_volume

    return payload

  def _op_target(self, op: PipettingOp) -> Coordinate:
    target = self._resource_target(resource=op.resource, offset=op.offset)

    if isinstance(op, (SingleChannelAspiration, SingleChannelDispense)):
      material_z_thickness = (
        op.resource._material_z_thickness if isinstance(op.resource, Container) else None
      )
      if material_z_thickness is not None:
        target = target + Coordinate(z=material_z_thickness)
      if op.liquid_height is not None:
        target = target + Coordinate(z=op.liquid_height)

    return target

  def _resource_target(self, resource: Resource, offset: Coordinate) -> Coordinate:
    return resource.get_absolute_location(x="c", y="c", z="b") + offset

  def _safe_travel_z(self, clearance: float = 10.0) -> float:
    top_zs = [resource.get_absolute_location(z="top").z for resource in self.deck.get_all_resources()]
    top_zs.append(0.0)
    return round(max(top_zs) + clearance, 4)

  def _resource_to_dict(self, resource: Resource, include_children: bool = True) -> Dict[str, Any]:
    data: Dict[str, Any] = {
      "name": resource.name,
      "type": resource.__class__.__name__,
      "category": resource.category,
      "model": resource.model,
      "parent_name": resource.parent.name if resource.parent is not None else None,
      "size": {
        "x": resource.get_size_x(),
        "y": resource.get_size_y(),
        "z": resource.get_size_z(),
      },
      "absolute_size": {
        "x": resource.get_absolute_size_x(),
        "y": resource.get_absolute_size_y(),
        "z": resource.get_absolute_size_z(),
      },
      "location": self._coordinate_to_dict(resource.location) if resource.location is not None else None,
      "absolute_location": self._coordinate_or_none(resource, x="l", y="f", z="b"),
      "absolute_center": self._coordinate_or_none(resource, x="c", y="c", z="c"),
      "rotation": self._rotation_to_dict(resource.rotation),
      "absolute_rotation": self._rotation_to_dict(resource.get_absolute_rotation()),
    }

    if isinstance(resource, Container):
      data["material_z_thickness"] = resource._material_z_thickness

    if include_children:
      data["children"] = [
        self._resource_to_dict(child, include_children=True) for child in resource.children
      ]

    return data

  def _resource_to_compact_dict(self, resource: Resource) -> Dict[str, Any]:
    data: Dict[str, Any] = {
      "type": resource.__class__.__name__,
      "category": resource.category,
      "parent": resource.parent.name if resource.parent is not None else None,
      "size": self._coordinate_values(
        Coordinate(resource.get_size_x(), resource.get_size_y(), resource.get_size_z())
      ),
      "absolute_size": self._coordinate_values(
        Coordinate(
          resource.get_absolute_size_x(),
          resource.get_absolute_size_y(),
          resource.get_absolute_size_z(),
        )
      ),
      "absolute_location": self._compact_coordinate_or_none(resource, x="l", y="f", z="b"),
      "absolute_center": self._compact_coordinate_or_none(resource, x="c", y="c", z="c"),
    }
    if resource.model is not None:
      data["model"] = resource.model
    if isinstance(resource, Container) and resource._material_z_thickness is not None:
      data["material_z_thickness"] = resource._material_z_thickness
    return data

  def _coordinate_or_none(self, resource: Resource, x: str, y: str, z: str) -> Optional[Dict[str, float]]:
    try:
      return self._coordinate_to_dict(resource.get_absolute_location(x=x, y=y, z=z))
    except Exception:
      return None

  def _compact_coordinate_or_none(
    self, resource: Resource, x: str, y: str, z: str
  ) -> Optional[List[float]]:
    try:
      return self._coordinate_values(resource.get_absolute_location(x=x, y=y, z=z))
    except Exception:
      return None

  def _resource_brief(self, resource: Resource) -> Dict[str, Any]:
    return {
      "name": resource.name,
      "type": resource.__class__.__name__,
      "category": resource.category,
    }

  def _coordinate_to_dict(self, coordinate: Coordinate) -> Dict[str, float]:
    return {
      "x": coordinate.x,
      "y": coordinate.y,
      "z": coordinate.z,
    }

  def _coordinate_values(self, coordinate: Coordinate) -> List[float]:
    return [coordinate.x, coordinate.y, coordinate.z]

  def _rotation_to_dict(self, rotation: Rotation) -> Dict[str, float]:
    return {
      "x": rotation.x,
      "y": rotation.y,
      "z": rotation.z,
    }

  def _json_safe(self, value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
      return value
    if isinstance(value, Coordinate):
      return self._coordinate_to_dict(value)
    if isinstance(value, Rotation):
      return self._rotation_to_dict(value)
    if isinstance(value, Resource):
      return self._resource_brief(value)
    if isinstance(value, dict):
      return {str(key): self._json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
      return [self._json_safe(item) for item in value]
    return repr(value)

  def _compact_events(
    self,
    events: List[Dict[str, Any]],
    include_firmware_commands: bool,
  ) -> List[Dict[str, Any]]:
    compact_events = []
    for event in events:
      event_type = event.get("event")
      if event_type == "firmware_command":
        if include_firmware_commands:
          compact_events.append(
            {
              "event": "firmware_command",
              "command": event["command"],
              **({"id": event["id"]} if event.get("id") is not None else {}),
            }
          )
        continue
      if event_type == "operation":
        compact_events.append(self._compact_operation_event(event))
      elif event_type == "instruction":
        compact_events.append(self._compact_instruction_event(event))
      else:
        compact_events.append(copy.deepcopy(event))
    return compact_events

  def _compact_operation_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {
      "event": "operation",
      "action": event["action"],
    }

    if "head" in event:
      compact["head"] = event["head"]
    if "resource" in event:
      compact["resource"] = event["resource"]["name"]
    if "target" in event:
      compact["target"] = self._compact_target(event["target"])
    if "offset" in event:
      compact["offset"] = self._compact_target(event["offset"])
    if event.get("extra"):
      compact["extra"] = event["extra"]
    if "backend_kwargs" in event and event["backend_kwargs"]:
      compact["backend_kwargs"] = event["backend_kwargs"]

    if "channels" in event:
      compact["channels"] = [
        self._compact_channel_payload(channel_payload) for channel_payload in event["channels"]
      ]

    return compact

  def _compact_channel_payload(self, channel_payload: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {
      "channel": channel_payload["channel"],
      "resource": channel_payload["resource"]["name"],
      "target": self._compact_target(channel_payload["target"]),
    }
    if channel_payload.get("offset") != {"x": 0, "y": 0, "z": 0}:
      compact["offset"] = self._compact_target(channel_payload["offset"])
    for key in ("volume", "flow_rate", "liquid_height", "blow_out_air_volume"):
      if channel_payload.get(key) is not None:
        compact[key] = channel_payload[key]
    return compact

  def _compact_instruction_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {
      "event": "instruction",
      "instruction": event["instruction"],
    }
    for key in ("channel", "head", "phase", "simulated", "volume"):
      if key in event:
        compact[key] = event[key]
    if "target" in event:
      compact["target"] = self._compact_target(event["target"])
    if "targets" in event:
      compact["targets"] = {
        str(key): self._compact_target(target) for key, target in event["targets"].items()
      }
    if event.get("extra"):
      compact["extra"] = event["extra"]
    if "make_space" in event:
      compact["make_space"] = event["make_space"]
    return compact

  def _compact_target(self, target: Any) -> Any:
    if not isinstance(target, dict):
      return target
    if set(target.keys()) == {"x", "y", "z"}:
      return [target["x"], target["y"], target["z"]]
    return {key: target[key] for key in sorted(target.keys())}
