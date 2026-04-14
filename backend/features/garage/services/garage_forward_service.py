from __future__ import annotations

from backend.features.garage.services.garage_forward_config import GarageForwardConfigMixin
from backend.features.garage.services.garage_forward_runtime import GarageForwardRuntimeMixin


class GarageForwardService(GarageForwardConfigMixin, GarageForwardRuntimeMixin):
    pass
