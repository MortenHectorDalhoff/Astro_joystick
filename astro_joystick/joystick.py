"""Pygame joystick wrapper with button assignment support."""

from typing import Callable, Dict, List, Optional

try:
    import pygame

    PYGAME_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    pygame = None
    PYGAME_AVAILABLE = False


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
