"""Tkinter UI for joystick telescope control."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional, Tuple

from .constants import POPULAR_TARGETS, SLEW_SPEED_LEVELS
from .joystick import JoystickManager, PYGAME_AVAILABLE
from .telescope import MountController, TelescopeStatus
from .utils import angular_distance, clamp, direction_hint, format_dec, format_ra, parse_sexagesimal

try:
    from PIL import ImageGrab

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    ImageGrab = None
    PIL_AVAILABLE = False


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
        status = self.mount.status()
        if status:
            self.tracking_var.set(bool(status.tracking))

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
        idx = int(clamp(self.slew_speed_index, 0, len(SLEW_SPEED_LEVELS) - 1))
        return f"{SLEW_SPEED_LEVELS[idx]:.2f}°/s"

    def adjust_slew_speed(self, delta: int) -> None:
        self.slew_speed_index = int(clamp(self.slew_speed_index + delta, 0, len(SLEW_SPEED_LEVELS) - 1))
        self.speed_var.set(self._format_speed())

    def handle_axis_motion(self, axes: List[float]) -> None:
        if not axes:
            return
        ra_raw = axes[0] if len(axes) > 0 else 0.0
        dec_raw = axes[1] if len(axes) > 1 else 0.0
        deadband = 0.12
        if abs(ra_raw) < deadband:
            ra_raw = 0.0
        if abs(dec_raw) < deadband:
            dec_raw = 0.0
        speed = SLEW_SPEED_LEVELS[int(clamp(self.slew_speed_index, 0, len(SLEW_SPEED_LEVELS) - 1))]
        ra_rate = ra_raw * speed
        dec_rate = -dec_raw * speed
        self.mount.move(ra_rate, dec_rate)

    def _update_loop(self) -> None:
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

        delta_ra_deg, delta_dec_deg = direction_hint(status.ra_hours, status.dec_deg, target_ra, target_dec)
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
