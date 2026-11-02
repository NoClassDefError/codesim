"""VSG with cascaded voltage/current control connected to an infinite bus."""

from typing import Any

from .vsg_smib_system import VSGSMIBSystem


class VSGSMIBAVCSystem(VSGSMIBSystem):
    """SMIB fault-study system using :class:`VSGCCAVC`."""

    @staticmethod
    def defaultParameters(overrides=None):
        parameters = {"deviceModel": "VSGCCAVC"}
        parameters.update(overrides or {})
        return VSGSMIBSystem.defaultParameters(parameters)

    def __init__(self, p: dict[str, Any]) -> None:
        super().__init__(p)
        self.name = "VSGSMIBAVCSystem"
        self.rlGrid.systemName = self.name
