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

CHATTERBOX_TRACE_SCHEMA_VERSION = "0.1.0"
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
  """Record planned chatterbox operations for visualization and run reports."""

  def _init_trace(self) -> None:
    self._trace_events: List[Dict[str, Any]] = []

  def clear_trace(self) -> None:
    """Clear recorded chatterbox trace events."""
    self._trace_events.clear()

  def get_trace(self) -> List[Dict[str, Any]]:
    """Return a JSON-serializable copy of recorded chatterbox trace events."""
    return copy.deepcopy(self._trace_events)

  def get_deck_snapshot(self) -> Dict[str, Any]:
    """Return a JSON-serializable snapshot of the current deck layout."""
    return {
      "name": self.deck.name,
      "coordinate_frame": "deck",
      "resources": self.get_compact_deck_layout(),
    }

  def get_simulation(self) -> Dict[str, Any]:
    """Return stable trace and deck data for downstream simulators."""
    return self.export_for_simulation(include_deck_layout=True)

  def export_for_simulation(self, include_deck_layout: bool = True) -> Dict[str, Any]:
    """Export planned operation targets and optional deck geometry.

    Coordinates are PLR planned destinations in deck coordinates. They are not measured hardware
    positions.
    """
    payload: Dict[str, Any] = {
      "schema_version": CHATTERBOX_TRACE_SCHEMA_VERSION,
      "coordinate_frame": "deck",
      "events": self.get_trace(),
    }
    if include_deck_layout:
      payload["deck"] = {
        "root": self.deck.name,
        "resources": self.get_compact_deck_layout(),
      }
    return payload

  def get_compact_deck_layout(self) -> Dict[str, Dict[str, Any]]:
    resources = [self.deck, *self.deck.get_all_resources()]
    return {resource.name: self._resource_to_compact_dict(resource) for resource in resources}

  def _record_setup_event(self) -> None:
    self._record_event("lifecycle", action="setup")

  def _record_stop_event(self) -> None:
    self._record_event("lifecycle", action="stop")

  def _record_event(self, event: str, **data: Any) -> None:
    self._trace_events.append({"event": event, **self._json_safe(data)})

  def _record_liquid_handler_operation(
    self,
    action: str,
    ops: Sequence[PipettingOp],
    use_channels: Sequence[int],
    backend_kwargs: Optional[Dict[str, Any]] = None,
  ) -> None:
    self._record_event(
      "operation",
      action=action,
      coordinate_source="planned_destination",
      channel_states=self._channel_tip_states(use_channels),
      active_channels=len(use_channels),
      channels=[
        self._op_to_channel_payload(op=op, channel=channel)
        for op, channel in zip(ops, use_channels)
      ],
      backend_kwargs=backend_kwargs or {},
    )

  def _record_head96_operation(
    self,
    action: str,
    op: Head96Op,
    resource: Resource,
    extra: Optional[Dict[str, Any]] = None,
  ) -> None:
    self._record_event(
      "operation",
      action=action,
      head="head96",
      coordinate_source="planned_destination",
      channel_states=self._head96_tip_states(),
      active_channels=sum(state["has_tip"] for state in self._head96_tip_states()),
      resource=self._resource_brief(resource),
      offset=self._coordinate_values(op.offset),
      target=self._coordinate_values(self._resource_target(resource=resource, offset=op.offset)),
      extra=extra or {},
    )

  def _channel_tip_states(self, channels: Sequence[int]) -> List[Dict[str, Any]]:
    """Return PLR's current tip state for the channels in an operation."""
    return [
      {"channel": channel, "has_tip": bool(self.head[channel].has_tip)}
      for channel in channels
    ]

  def _head96_tip_states(self) -> List[Dict[str, Any]]:
    """Return PLR's current tip state for every 96-head channel."""
    return [
      {"channel": channel, "has_tip": bool(self.head96[channel].has_tip)}
      for channel in range(96)
    ]

  def _op_to_channel_payload(self, op: PipettingOp, channel: int) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
      "channel": channel,
      "resource": op.resource.name,
      "target": self._coordinate_values(self._op_target(op)),
      "coordinate_source": "planned_destination",
    }

    if op.offset != Coordinate.zero():
      payload["offset"] = self._coordinate_values(op.offset)

    if isinstance(op, (SingleChannelAspiration, SingleChannelDispense)):
      payload["volume"] = op.volume
      if op.flow_rate is not None:
        payload["flow_rate"] = op.flow_rate
      if op.liquid_height is not None:
        payload["liquid_height"] = op.liquid_height
      if op.blow_out_air_volume is not None:
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

  def _resource_to_compact_dict(self, resource: Resource) -> Dict[str, Any]:
    data: Dict[str, Any] = {
      "type": resource.__class__.__name__,
      "category": resource.category,
      "parent": resource.parent.name if resource.parent is not None else None,
      "size": self._coordinate_values(
        Coordinate(resource.get_size_x(), resource.get_size_y(), resource.get_size_z())
      ),
      "absolute_location": self._coordinate_or_none(resource, x="l", y="f", z="b"),
      "absolute_center": self._coordinate_or_none(resource, x="c", y="c", z="c"),
    }
    if resource.model is not None:
      data["model"] = resource.model
    if isinstance(resource, Container) and resource._material_z_thickness is not None:
      data["material_z_thickness"] = resource._material_z_thickness
    return data

  def _coordinate_or_none(self, resource: Resource, x: str, y: str, z: str) -> Optional[List[float]]:
    try:
      return self._coordinate_values(resource.get_absolute_location(x=x, y=y, z=z))
    except Exception:
      return None

  def _coordinate_values(self, coordinate: Coordinate) -> List[float]:
    return [coordinate.x, coordinate.y, coordinate.z]

  def _resource_brief(self, resource: Resource) -> Dict[str, Any]:
    return {
      "name": resource.name,
      "type": resource.__class__.__name__,
      "category": resource.category,
    }

  def _json_safe(self, value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
      return value
    if isinstance(value, Coordinate):
      return self._coordinate_values(value)
    if isinstance(value, Resource):
      return self._resource_brief(value)
    if isinstance(value, dict):
      return {str(key): self._json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
      return [self._json_safe(item) for item in value]
    return repr(value)
