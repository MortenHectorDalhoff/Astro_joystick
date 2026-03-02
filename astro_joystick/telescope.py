"""ASCOM mount integration with a simulator fallback."""

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .utils import clamp

try:
    import comtypes.client

    COMTYPES_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    comtypes = None
    COMTYPES_AVAILABLE = False

try:
    import win32com.client  # type: ignore

    WIN32_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    win32com = None
    WIN32_AVAILABLE = False


@dataclass
class TelescopeStatus:
    ra_hours: float
    dec_deg: float
    tracking: bool


class MockTelescope:
    """A lightweight simulator to keep the UI functional without ASCOM hardware."""

    def __init__(self) -> None:
        self.connected = False
        self.right_ascension = 0.0
        self.declination = 0.0
        self.tracking = False
        self._ra_rate = 0.0
        self._dec_rate = 0.0
        self._last_update = time.time()

    def connect(self) -> None:
        self.connected = True
        self._last_update = time.time()

    def disconnect(self) -> None:
        self.connected = False

    def set_tracking(self, enabled: bool) -> None:
        self.tracking = bool(enabled)

    def move_axis(self, ra_rate_deg: float, dec_rate_deg: float) -> None:
        self._ra_rate = ra_rate_deg
        self._dec_rate = dec_rate_deg

    def slew_to(self, ra_hours: float, dec_deg: float) -> None:
        self.right_ascension = ra_hours % 24.0
        self.declination = clamp(dec_deg, -89.999, 89.999)
        self._ra_rate = 0.0
        self._dec_rate = 0.0

    def tick(self) -> None:
        now = time.time()
        dt = now - self._last_update
        self._last_update = now
        self.right_ascension = (self.right_ascension + (self._ra_rate * dt) / 15.0) % 24.0
        self.declination = clamp(self.declination + self._dec_rate * dt, -89.999, 89.999)

    # Properties that mimic ASCOM names
    @property
    def RightAscension(self) -> float:
        return self.right_ascension

    @property
    def Declination(self) -> float:
        return self.declination

    @property
    def Tracking(self) -> bool:
        return self.tracking

    @Tracking.setter
    def Tracking(self, value: bool) -> None:
        self.tracking = bool(value)


class MountController:
    """Encapsulates ASCOM connectivity with a simulator fallback."""

    def __init__(self) -> None:
        self.driver_name: Optional[str] = None
        self.telescope: Optional[object] = None
        self.simulated = True
        self.mock = MockTelescope()

    def available_mounts(self) -> List[str]:
        mounts: List[str] = ["Mock Simulator (offline)"]
        if COMTYPES_AVAILABLE:
            try:
                profile = comtypes.client.CreateObject("ASCOM.Utilities.Profile")  # type: ignore[attr-defined]
                profile.DeviceType = "Telescope"
                for device in profile.RegisteredDevices:  # type: ignore[attr-defined]
                    mounts.append(str(device))
            except Exception:
                pass
        elif WIN32_AVAILABLE:
            try:
                profile = win32com.client.Dispatch("ASCOM.Utilities.Profile")  # type: ignore[union-attr]
                profile.DeviceType = "Telescope"
                for device in profile.RegisteredDevices:  # type: ignore[attr-defined]
                    mounts.append(str(device))
            except Exception:
                pass

        if "ASCOM.Simulator.Telescope" not in mounts:
            mounts.append("ASCOM.Simulator.Telescope")

        seen = set()
        unique: List[str] = []
        for item in mounts:
            if item not in seen and item:
                seen.add(item)
                unique.append(item)
        return unique

    def connect(self, driver: str) -> Tuple[bool, str]:
        self.disconnect()
        if driver == "Mock Simulator (offline)":
            self.telescope = self.mock
            self.mock.connect()
            self.driver_name = driver
            self.simulated = True
            return True, "Connected to mock simulator."

        try:
            if COMTYPES_AVAILABLE:
                scope = comtypes.client.CreateObject(driver)  # type: ignore[attr-defined]
            elif WIN32_AVAILABLE:
                scope = win32com.client.Dispatch(driver)  # type: ignore[union-attr]
            else:
                raise RuntimeError("ASCOM components not available on this system.")
            scope.Connected = True  # type: ignore[attr-defined]
            self.telescope = scope
            self.driver_name = driver
            self.simulated = False
            return True, f"Connected to {driver}"
        except Exception as exc:  # pragma: no cover - hardware dependent
            self.telescope = self.mock
            self.mock.connect()
            self.driver_name = "Mock Simulator (offline)"
            self.simulated = True
            return False, f"Failed to connect to {driver}: {exc}\nFalling back to mock simulator."

    def disconnect(self) -> None:
        try:
            if self.telescope and not self.simulated:
                self.telescope.Connected = False  # type: ignore[attr-defined]
        finally:
            self.telescope = None
            self.driver_name = None

    def set_tracking(self, enabled: bool) -> None:
        if not self.telescope:
            return
        try:
            self.telescope.Tracking = bool(enabled)  # type: ignore[attr-defined]
        except Exception:
            pass
        if self.simulated:
            self.mock.set_tracking(enabled)

    def move(self, ra_rate_deg: float, dec_rate_deg: float) -> None:
        if not self.telescope:
            return
        if self.simulated:
            self.mock.move_axis(ra_rate_deg, dec_rate_deg)
            return
        try:  # pragma: no cover - hardware dependent
            if hasattr(self.telescope, "MoveAxis"):
                self.telescope.MoveAxis(0, ra_rate_deg)  # type: ignore[attr-defined]
                self.telescope.MoveAxis(1, dec_rate_deg)  # type: ignore[attr-defined]
        except Exception:
            pass

    def slew_to(self, ra_hours: float, dec_deg: float) -> None:
        if not self.telescope:
            return
        if self.simulated:
            self.mock.slew_to(ra_hours, dec_deg)
            return
        try:  # pragma: no cover - hardware dependent
            if hasattr(self.telescope, "SlewToCoordinatesAsync"):
                self.telescope.SlewToCoordinatesAsync(ra_hours, dec_deg)  # type: ignore[attr-defined]
            elif hasattr(self.telescope, "SlewToCoordinates"):
                self.telescope.SlewToCoordinates(ra_hours, dec_deg)  # type: ignore[attr-defined]
        except Exception:
            pass

    def status(self) -> Optional[TelescopeStatus]:
        if not self.telescope:
            return None
        if self.simulated:
            self.mock.tick()
        try:
            ra = float(self.telescope.RightAscension)  # type: ignore[attr-defined]
            dec = float(self.telescope.Declination)  # type: ignore[attr-defined]
            tracking = bool(self.telescope.Tracking)  # type: ignore[attr-defined]
        except Exception:
            ra = getattr(self.telescope, "right_ascension", 0.0)
            dec = getattr(self.telescope, "declination", 0.0)
            tracking = getattr(self.telescope, "tracking", False)
        return TelescopeStatus(ra_hours=ra, dec_deg=dec, tracking=tracking)
