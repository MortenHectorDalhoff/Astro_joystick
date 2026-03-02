#!/usr/bin/env python3
"""
Joystick-driven ASCOM telescope controller with a modern Tkinter UI.

This tool lets Windows users pick a joystick, map buttons for slew speed
control, connect to an ASCOM-compatible mount, monitor RA/Dec, set targets,
see distance to target, and toggle tracking. The UI degrades gracefully when
pygame or ASCOM components are unavailable by falling back to a mock
simulator so the interface can still be demonstrated.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional, Tuple

# Optional third-party modules
try:
    import pygame

    PYGAME_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    pygame = None
    PYGAME_AVAILABLE = False

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

try:
    from PIL import ImageGrab

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    ImageGrab = None
    PIL_AVAILABLE = False


POPULAR_TARGETS: Dict[str, Tuple[float, float]] = {
    "Andromeda Galaxy (M31)": (0.7122, 41.2692),
    "Orion Nebula (M42)": (5.5881, -5.3911),
    "Pleiades (M45)": (3.7883, 24.1167),
    "Polaris": (2.5303, 89.2641),
    "Vega": (18.6156, 38.7837),
    "Betelgeuse": (5.9195, 7.4071),
    "Sirius": (6.7525, -16.7161),
    "Altair": (19.8464, 8.8683),
}

SLEW_SPEED_LEVELS = [0.25, 0.5, 1.0, 2.0, 4.0]  # degrees per second


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def ra_hours_to_deg(hours: float) -> float:
    return (hours % 24.0) * 15.0


def deg_to_ra_hours(deg: float) -> float:
    return (deg / 15.0) % 24.0


def parse_sexagesimal(value: str, *, hours: bool = False) -> float:
    """Parse sexagesimal strings like '12:30:00' or '-05 23 28'."""
    text = value.strip()
    if not text:
        raise ValueError("Empty value")
    sign = -1 if text.startswith("-") else 1
    cleaned = text.lstrip("+-")
    cleaned = (
        cleaned.replace("h", " ")
        .replace("d", " ")
        .replace("m", " ")
        .replace("s", " ")
        .replace("°", " ")
        .replace("'", " ")
        .replace('"', " ")
        .replace(":", " ")
    )
    parts = cleaned.split()
    numbers = [abs(float(p)) for p in parts]
    base = numbers[0] if numbers else 0.0
    minutes = numbers[1] / 60.0 if len(numbers) > 1 else 0.0
    seconds = numbers[2] / 3600.0 if len(numbers) > 2 else 0.0
    total = sign * (base + minutes + seconds)
    if hours:
        return total % 24.0 if total >= 0 else total
    return total


def format_ra(hours: float) -> str:
    hours = hours % 24.0
    h = int(hours)
    m_float = (hours - h) * 60
    m = int(m_float)
    s = (m_float - m) * 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def format_dec(deg: float) -> str:
    sign = "-" if deg < 0 else "+"
    deg_abs = abs(deg)
    d = int(deg_abs)
    m_float = (deg_abs - d) * 60
    m = int(m_float)
    s = (m_float - m) * 60
    return f"{sign}{d:02d}:{m:02d}:{s:05.1f}"


def angular_distance(ra1_hours: float, dec1_deg: float, ra2_hours: float, dec2_deg: float) -> float:
    ra1 = math.radians(ra_hours_to_deg(ra1_hours))
    ra2 = math.radians(ra_hours_to_deg(ra2_hours))
    dec1 = math.radians(dec1_deg)
    dec2 = math.radians(dec2_deg)
    cos_d = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)
    cos_d = clamp(cos_d, -1.0, 1.0)
    return math.degrees(math.acos(cos_d))


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
        # Try comtypes profile first
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

        # Add simulator option if an ASCOM install is present
        if "ASCOM.Simulator.Telescope" not in mounts:
            mounts.append("ASCOM.Simulator.Telescope")
        # Remove duplicates while keeping order
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
            # Hardware-specific failures should not kill the UI
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
            # Fallback names for simulator
            ra = getattr(self.telescope, "right_ascension", 0.0)
            dec = getattr(self.telescope, "declination", 0.0)
            tracking = getattr(self.telescope, "tracking", False)
        return TelescopeStatus(ra_hours=ra, dec_deg=dec, tracking=tracking)


class JoystickManager:
    """Small wrapper around pygame joystick handling with assignment support."""

    def __init__(
        self,
        on_speed_change: Callable[[int], None],
        on_axis: Callable[[List[float]], None],
    ) -> None:
        self.on_speed_change = on_speed_change
        self.on_axis = on_axis
        self.joystick: Optional[object] = None
        self.pending_assignment: Optional[str] = None
        self.bindings: Dict[str, Optional[int]] = {"increase": None, "decrease": None}
        if PYGAME_AVAILABLE:
            pygame.init()
            pygame.joystick.init()

    def list_devices(self) -> List[str]:
        if not PYGAME_AVAILABLE:
            return []
        return [pygame.joystick.Joystick(i).get_name() for i in range(pygame.joystick.get_count())]  # type: ignore[attr-defined]

    def select(self, index: int) -> bool:
        if not PYGAME_AVAILABLE:
            return False
        try:
            self.joystick = pygame.joystick.Joystick(index)  # type: ignore[attr-defined]
            self.joystick.init()  # type: ignore[attr-defined]
            return True
        except Exception:
            return False

    def request_assignment(self, kind: str) -> None:
        self.pending_assignment = kind

    def process(self) -> None:
        if not PYGAME_AVAILABLE or not self.joystick:
            return
        for event in pygame.event.get():  # type: ignore[attr-defined]
            if event.type == pygame.JOYBUTTONDOWN:  # type: ignore[attr-defined]
                button = event.button
                if self.pending_assignment:
                    self.bindings[self.pending_assignment] = button
                    self.pending_assignment = None
                else:
                    if button == self.bindings.get("increase"):
                        self.on_speed_change(1)
                    if button == self.bindings.get("decrease"):
                        self.on_speed_change(-1)
        axes: List[float] = []
        for idx in range(self.joystick.get_numaxes()):  # type: ignore[attr-defined]
            axes.append(self.joystick.get_axis(idx))  # type: ignore[attr-defined]
        if axes:
            self.on_axis(axes)


class TelescopeJoystickApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Telescope Joystick Control")
        self.root.geometry("1100x700")
        self.root.configure(bg="#0f111a")

        self.mount = MountController()
        self.slew_speed_index = 2  # default SLEW_SPEED_LEVELS index
        self.current_target: Optional[Tuple[float, float]] = None

        self.joystick = JoystickManager(self.adjust_slew_speed, self.handle_axis_motion)

        self.tracking_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Not connected")
        self.target_var = tk.StringVar(value="No target set")
        self.distance_var = tk.StringVar(value="Distance: --")
        self.speed_var = tk.StringVar(value=self._format_speed())
        self.increase_binding_var = tk.StringVar(value="Unassigned")
        self.decrease_binding_var = tk.StringVar(value="Unassigned")

        self.waiting_label_var = tk.StringVar(value="")

        self._setup_style()
        self._build_ui()
        self._refresh_devices()
        self._refresh_mounts()
        self._update_loop()

    def _setup_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        bg = "#0f111a"
        panel = "#161a25"
        accent = "#4aa3ff"
        text = "#e5e7eb"
        style.configure("TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel, relief="raised", borderwidth=1)
        style.configure("TLabel", background=bg, foreground=text, font=("Segoe UI", 11))
        style.configure("Panel.TLabel", background=panel, foreground=text, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=bg, foreground=text, font=("Segoe UI", 16, "bold"))
        style.configure("TButton", padding=8, font=("Segoe UI", 10))
        style.configure("Accent.TButton", background=accent, foreground="white", padding=8, font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#6bb4ff")])
        style.configure("TCheckbutton", background=bg, foreground=text, font=("Segoe UI", 10))
        style.configure("TCombobox", padding=4, fieldbackground=panel, background=panel, foreground=text)

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self.root)
        root_frame.pack(fill="both", expand=True, padx=16, pady=16)

        header = ttk.Label(root_frame, text="Joystick Telescope Control", style="Title.TLabel")
        header.pack(anchor="w")
        subheader = ttk.Label(
            root_frame,
            text="Select joystick, map speed buttons, connect to mount, set a target, and monitor RA/Dec.",
        )
        subheader.pack(anchor="w", pady=(0, 12))

        top_frame = ttk.Frame(root_frame)
        top_frame.pack(fill="x", pady=(0, 12))

        self._build_joystick_panel(top_frame)
        self._build_mount_panel(top_frame)
        self._build_target_panel(root_frame)
        self._build_status_panel(root_frame)

    def _build_joystick_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

        ttk.Label(frame, text="Joystick", style="Panel.TLabel", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=8)

        row = ttk.Frame(frame, style="Panel.TFrame")
        row.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(row, text="Device", style="Panel.TLabel").pack(side="left")
        self.joystick_combo = ttk.Combobox(row, state="readonly", width=32)
        self.joystick_combo.pack(side="left", padx=6)
        ttk.Button(row, text="Refresh", command=self._refresh_devices).pack(side="left")
        ttk.Button(row, text="Select", command=self._select_joystick, style="Accent.TButton").pack(side="left", padx=(6, 0))

        assignment_frame = ttk.Frame(frame, style="Panel.TFrame")
        assignment_frame.pack(fill="x", padx=12, pady=4)
        ttk.Label(assignment_frame, text="Speed buttons:", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Button(assignment_frame, text="Assign Increase", command=lambda: self._begin_assignment("increase")).grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(assignment_frame, textvariable=self.increase_binding_var, style="Panel.TLabel").grid(row=1, column=1, sticky="w", padx=8)
        ttk.Button(assignment_frame, text="Assign Decrease", command=lambda: self._begin_assignment("decrease")).grid(row=2, column=0, sticky="w", pady=2)
        ttk.Label(assignment_frame, textvariable=self.decrease_binding_var, style="Panel.TLabel").grid(row=2, column=1, sticky="w", padx=8)
        ttk.Label(assignment_frame, textvariable=self.waiting_label_var, style="Panel.TLabel", foreground="#f8d568").grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        speed_frame = ttk.Frame(frame, style="Panel.TFrame")
        speed_frame.pack(fill="x", padx=12, pady=6)
        ttk.Label(speed_frame, text="Current slew speed:", style="Panel.TLabel").pack(side="left")
        self.speed_label = ttk.Label(speed_frame, textvariable=self.speed_var, style="Panel.TLabel", font=("Segoe UI", 12, "bold"))
        self.speed_label.pack(side="left", padx=6)

        if not PYGAME_AVAILABLE:
            warning = ttk.Label(
                frame,
                text="pygame not available. Joystick input will be disabled.\nInstall pygame on Windows for full functionality.",
                style="Panel.TLabel",
                foreground="#f87171",
            )
            warning.pack(fill="x", padx=12, pady=(8, 12))

    def _build_mount_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(frame, text="Mount", style="Panel.TLabel", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=8)

        row = ttk.Frame(frame, style="Panel.TFrame")
        row.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(row, text="Driver", style="Panel.TLabel").pack(side="left")
        self.mount_combo = ttk.Combobox(row, state="readonly", width=40)
        self.mount_combo.pack(side="left", padx=6)
        ttk.Button(row, text="Refresh", command=self._refresh_mounts).pack(side="left")
        ttk.Button(row, text="Connect", command=self._connect_mount, style="Accent.TButton").pack(side="left", padx=(6, 0))

        status_row = ttk.Frame(frame, style="Panel.TFrame")
        status_row.pack(fill="x", padx=12, pady=4)
        ttk.Label(status_row, text="Status:", style="Panel.TLabel").pack(side="left")
        ttk.Label(status_row, textvariable=self.status_var, style="Panel.TLabel", font=("Segoe UI", 11, "bold")).pack(side="left", padx=6)

        tracking_row = ttk.Frame(frame, style="Panel.TFrame")
        tracking_row.pack(fill="x", padx=12, pady=4)
        ttk.Label(tracking_row, text="Tracking", style="Panel.TLabel").pack(side="left")
        tracking_toggle = ttk.Checkbutton(
            tracking_row,
            variable=self.tracking_var,
            command=self._toggle_tracking,
            style="TCheckbutton",
        )
        tracking_toggle.pack(side="left", padx=8)

        coords_frame = ttk.Frame(frame, style="Panel.TFrame")
        coords_frame.pack(fill="x", padx=12, pady=(10, 6))
        ttk.Label(coords_frame, text="RA (hms):", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=2)
        self.ra_label = ttk.Label(coords_frame, text="--", style="Panel.TLabel", font=("Segoe UI", 12, "bold"))
        self.ra_label.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(coords_frame, text="Dec (dms):", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=2)
        self.dec_label = ttk.Label(coords_frame, text="--", style="Panel.TLabel", font=("Segoe UI", 12, "bold"))
        self.dec_label.grid(row=1, column=1, sticky="w", padx=6)

    def _build_target_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="x", pady=(0, 12))
        ttk.Label(frame, text="Target", style="Panel.TLabel", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=8)

        entry_row = ttk.Frame(frame, style="Panel.TFrame")
        entry_row.pack(fill="x", padx=12, pady=4)
        ttk.Label(entry_row, text="Target RA (hms):", style="Panel.TLabel").pack(side="left")
        self.target_ra_entry = ttk.Entry(entry_row, width=18)
        self.target_ra_entry.pack(side="left", padx=6)
        ttk.Label(entry_row, text="Dec (dms):", style="Panel.TLabel").pack(side="left")
        self.target_dec_entry = ttk.Entry(entry_row, width=18)
        self.target_dec_entry.pack(side="left", padx=6)
        ttk.Button(entry_row, text="Set Target", command=self._set_target_from_entries, style="Accent.TButton").pack(side="left", padx=(8, 0))

        popular_row = ttk.Frame(frame, style="Panel.TFrame")
        popular_row.pack(fill="x", padx=12, pady=4)
        ttk.Label(popular_row, text="Popular targets:", style="Panel.TLabel").pack(side="left")
        self.popular_combo = ttk.Combobox(popular_row, state="readonly", values=list(POPULAR_TARGETS.keys()), width=40)
        self.popular_combo.pack(side="left", padx=6)
        ttk.Button(popular_row, text="Use Selection", command=self._set_target_from_list).pack(side="left")

        readout_row = ttk.Frame(frame, style="Panel.TFrame")
        readout_row.pack(fill="x", padx=12, pady=(8, 4))
        ttk.Label(readout_row, text="Current:", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.current_readout = ttk.Label(readout_row, text="RA -- / Dec --", style="Panel.TLabel", font=("Segoe UI", 11, "bold"))
        self.current_readout.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(readout_row, text="Target:", style="Panel.TLabel").grid(row=1, column=0, sticky="w")
        self.target_readout = ttk.Label(readout_row, textvariable=self.target_var, style="Panel.TLabel", font=("Segoe UI", 11, "bold"))
        self.target_readout.grid(row=1, column=1, sticky="w", padx=6)
        self.distance_label = ttk.Label(readout_row, textvariable=self.distance_var, style="Panel.TLabel", font=("Segoe UI", 11, "bold"))
        self.distance_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        crosshair_frame = ttk.Frame(frame, style="Panel.TFrame")
        crosshair_frame.pack(fill="both", padx=12, pady=(10, 12))
        ttk.Label(crosshair_frame, text="Pointing helper", style="Panel.TLabel").pack(anchor="w")
        self.crosshair = tk.Canvas(crosshair_frame, width=260, height=260, bg="#0f111a", highlightthickness=0)
        self.crosshair.pack(pady=6)
        self.direction_text = ttk.Label(crosshair_frame, text="", style="Panel.TLabel")
        self.direction_text.pack(anchor="w", pady=(2, 0))

    def _build_status_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="x")
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=6)
        ttk.Label(frame, text="Tip: click Assign Increase/Decrease, then press a joystick button to map speed controls.", style="TLabel").pack(anchor="w")
        ttk.Label(frame, text="Distance text turns green within 1 arc-minute of your target.", style="TLabel").pack(anchor="w", pady=(0, 4))

    def _refresh_devices(self) -> None:
        names = self.joystick.list_devices()
        self.joystick_combo["values"] = names or ["(no joystick found)"]
        if names:
            self.joystick_combo.current(0)
        else:
            self.joystick_combo.set("(no joystick found)")

    def _refresh_mounts(self) -> None:
        mounts = self.mount.available_mounts()
        self.mount_combo["values"] = mounts
        if mounts:
            self.mount_combo.current(0)

    def _select_joystick(self) -> None:
        if not PYGAME_AVAILABLE:
            messagebox.showwarning("Joystick unavailable", "Install pygame to enable joystick support.")
            return
        selection = self.joystick_combo.current()
        if selection < 0:
            return
        if self.joystick.select(selection):
            messagebox.showinfo("Joystick selected", "Joystick ready for input.")
        else:
            messagebox.showerror("Selection failed", "Unable to initialize the selected joystick.")

    def _begin_assignment(self, kind: str) -> None:
        self.joystick.request_assignment(kind)
        self.waiting_label_var.set("Waiting for joystick button...")

    def _connect_mount(self) -> None:
        value = self.mount_combo.get()
        if not value:
            return
        ok, msg = self.mount.connect(value)
        self.status_var.set(msg)
        if not ok:
            messagebox.showwarning("Mount connection", msg)
        self.tracking_var.set(bool(self.mount.status().tracking if self.mount.status() else False))

    def _toggle_tracking(self) -> None:
        self.mount.set_tracking(self.tracking_var.get())

    def _set_target_from_entries(self) -> None:
        try:
            ra_hours = parse_sexagesimal(self.target_ra_entry.get(), hours=True)
            dec_deg = parse_sexagesimal(self.target_dec_entry.get(), hours=False)
        except Exception as exc:
            messagebox.showerror("Invalid target", f"Could not parse RA/Dec: {exc}")
            return
        self.current_target = (ra_hours % 24.0, dec_deg)
        self.target_var.set(f"RA {format_ra(ra_hours)}  |  Dec {format_dec(dec_deg)}")

    def _set_target_from_list(self) -> None:
        name = self.popular_combo.get()
        if name in POPULAR_TARGETS:
            ra_hours, dec_deg = POPULAR_TARGETS[name]
            self.target_ra_entry.delete(0, tk.END)
            self.target_ra_entry.insert(0, format_ra(ra_hours))
            self.target_dec_entry.delete(0, tk.END)
            self.target_dec_entry.insert(0, format_dec(dec_deg))
            self.current_target = (ra_hours, dec_deg)
            self.target_var.set(f"{name} — RA {format_ra(ra_hours)} | Dec {format_dec(dec_deg)}")

    def _format_speed(self) -> str:
        return f"{SLEW_SPEED_LEVELS[self.slew_speed_index]:.2f}°/s"

    def adjust_slew_speed(self, delta: int) -> None:
        self.slew_speed_index = int(clamp(self.slew_speed_index + delta, 0, len(SLEW_SPEED_LEVELS) - 1))
        self.speed_var.set(self._format_speed())

    def handle_axis_motion(self, axes: List[float]) -> None:
        if not axes:
            return
        # Map axis 0 to RA, axis 1 to Dec
        ra_raw = axes[0] if len(axes) > 0 else 0.0
        dec_raw = axes[1] if len(axes) > 1 else 0.0
        deadband = 0.12
        if abs(ra_raw) < deadband:
            ra_raw = 0.0
        if abs(dec_raw) < deadband:
            dec_raw = 0.0
        speed = SLEW_SPEED_LEVELS[self.slew_speed_index]
        ra_rate = ra_raw * speed
        dec_rate = -dec_raw * speed
        self.mount.move(ra_rate, dec_rate)

    def _update_loop(self) -> None:
        # Process joystick input and bindings
        self.joystick.process()
        if self.joystick.pending_assignment is None:
            self.waiting_label_var.set("")
            inc = self.joystick.bindings.get("increase")
            dec = self.joystick.bindings.get("decrease")
            self.increase_binding_var.set(f"Button {inc}" if inc is not None else "Unassigned")
            self.decrease_binding_var.set(f"Button {dec}" if dec is not None else "Unassigned")

        status = self.mount.status()
        if status:
            self.ra_label.config(text=format_ra(status.ra_hours))
            self.dec_label.config(text=format_dec(status.dec_deg))
            self.current_readout.config(text=f"RA {format_ra(status.ra_hours)} | Dec {format_dec(status.dec_deg)}")
            if self.tracking_var.get() != status.tracking:
                self.tracking_var.set(status.tracking)
            self._update_target_info(status)

        self.root.after(120, self._update_loop)

    def _update_target_info(self, status: TelescopeStatus) -> None:
        if not self.current_target:
            self.distance_var.set("Distance: --")
            self.distance_label.config(foreground="#e5e7eb")
            self._draw_crosshair(0.0, 0.0, False)
            return

        target_ra, target_dec = self.current_target
        distance_deg = angular_distance(status.ra_hours, status.dec_deg, target_ra, target_dec)
        arcmin = distance_deg * 60.0
        arcsec = arcmin * 60.0
        self.distance_var.set(f"Distance: {distance_deg:.3f}° / {arcmin:.2f}' / {arcsec:.1f}\"")
        close = arcmin <= 1.0
        self.distance_label.config(foreground="#6ee7b7" if close else "#e5e7eb")

        # Direction for crosshair helper
        delta_ra_deg = (ra_hours_to_deg(target_ra) - ra_hours_to_deg(status.ra_hours))
        # Normalize to [-180, 180]
        delta_ra_deg = (delta_ra_deg + 180) % 360 - 180
        delta_dec_deg = target_dec - status.dec_deg
        self._draw_crosshair(delta_ra_deg, delta_dec_deg, close)

    def _draw_crosshair(self, delta_ra_deg: float, delta_dec_deg: float, close: bool) -> None:
        canvas = self.crosshair
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        cx, cy = w // 2, h // 2
        canvas.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, outline="#2dd4bf", width=2)
        canvas.create_line(cx, 10, cx, h - 10, fill="#334155", dash=(4, 4))
        canvas.create_line(10, cy, w - 10, cy, fill="#334155", dash=(4, 4))
        scale = 2.0  # pixels per degree for the hint vector
        dx = clamp(delta_ra_deg * scale, -w / 2 + 20, w / 2 - 20)
        dy = clamp(-delta_dec_deg * scale, -h / 2 + 20, h / 2 - 20)
        canvas.create_line(cx, cy, cx + dx, cy + dy, fill="#4aa3ff", width=3, arrow=tk.LAST)
        if close:
            canvas.create_oval(cx - 12, cy - 12, cx + 12, cy + 12, outline="#6ee7b7", width=3)
            self.direction_text.config(text="On target: within 1 arc-minute", foreground="#6ee7b7")
        else:
            text = []
            if delta_dec_deg > 0.05:
                text.append("Move North")
            elif delta_dec_deg < -0.05:
                text.append("Move South")
            if delta_ra_deg > 0.05:
                text.append("Move East")
            elif delta_ra_deg < -0.05:
                text.append("Move West")
            self.direction_text.config(text=" | ".join(text) or "Centered", foreground="#e5e7eb")

    def save_screenshot(self, path: str) -> None:
        """Save a screenshot of the current UI if Pillow is available."""
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow not installed; cannot capture screenshot.")
        self.root.update_idletasks()
        x = self.root.winfo_rootx()
        y = self.root.winfo_rooty()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        bbox = (x, y, x + w, y + h)
        image = ImageGrab.grab(bbox=bbox)  # type: ignore[arg-type]
        image.save(path)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Joystick telescope controller")
    parser.add_argument("--screenshot", metavar="PATH", help="Save a UI screenshot to PATH and exit.")
    args = parser.parse_args(argv)

    root = tk.Tk()
    app = TelescopeJoystickApp(root)

    if args.screenshot:
        def capture_and_exit() -> None:
            try:
                app.save_screenshot(args.screenshot)
                print(f"Saved screenshot to {args.screenshot}")
            except Exception as exc:  # pragma: no cover - environment dependent
                print(f"Unable to save screenshot: {exc}", file=sys.stderr)
            finally:
                root.destroy()

        root.after(1200, capture_and_exit)
        root.mainloop()
        return 0

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
