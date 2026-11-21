"""Реестр устройств моделирования (rcad.core.devices).

Предоставляет `registry` с методами `names()` и `symbol_for(name)`
для интеграции с UI и сервисами (S2, T9).
"""

from __future__ import annotations

from rcad.core.devices.mna_devices import DeviceModel, device_for, _DEVICE_REGISTRY


class DeviceRegistry:
    def names(self) -> list[str]:
        """Имена всех зарегистрированных приборов."""
        return sorted(_DEVICE_REGISTRY.keys())

    def symbol_for(self, name: str):
        """Вернуть символ устройства (или None)."""
        from rcad.services.model_manager import ModelManager

        mm = ModelManager()
        return mm.symbol_for(name)

    def get_device(self, card: str, model: str | None, params: dict, tstep: float) -> DeviceModel:
        return device_for(card, model, params, tstep)


registry = DeviceRegistry()

__all__ = ["registry", "DeviceRegistry", "DeviceModel", "device_for"]
