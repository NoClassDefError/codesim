"""VSG with cascaded voltage/current control connected to an infinite bus."""

from typing import Any

from .vsg_smib_system import VSGSMIBSystem


class VSGSMIBAVCSystem(VSGSMIBSystem):
    """SMIB fault-study system using :class:`VSGCCAVC`."""

    def __init__(self, p: dict[str, Any], *, ClearingState: str = "delta") -> None:
        super().__init__(p, DeviceModel="VSGCCAVC", ClearingState=ClearingState)
        self.name = "VSGSMIBAVCSystem"
        self.rlGrid.systemName = self.name
