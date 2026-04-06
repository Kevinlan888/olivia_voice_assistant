"""Push-to-talk (PTT) button via Raspberry Pi GPIO.

Uses gpiozero.DigitalInputDevice so the caller only needs to call
``wait_for_press()`` and ``wait_for_release()`` — both block until the
button transitions.

When PTT_GPIO_PIN is -1 in settings this module is not used.
"""

import logging
from .config import settings

logger = logging.getLogger(__name__)


class PTTButton:
    """Wraps a gpiozero DigitalInputDevice as a push-to-talk button.

    With pull_up=True (default), the button should connect the GPIO pin to
    GND.  Pressing pulls the pin low → value becomes 0 = pressed.
    """

    def __init__(self):
        from gpiozero import DigitalInputDevice  # imported lazily; not on PC
        self._pin = DigitalInputDevice(
            pin=settings.PTT_GPIO_PIN,
            pull_up=settings.PTT_PULL_UP,
        )
        logger.info(
            "PTT button ready on BCM pin %d (pull_up=%s)",
            settings.PTT_GPIO_PIN,
            settings.PTT_PULL_UP,
        )

    def is_pressed(self) -> bool:
        """Return True while the button is held down."""
        # pull_up=True → pressed = pin low → value == 0
        return self._pin.value == 0

    def wait_for_press(self) -> None:
        """Block until the button is pressed (pin goes low)."""
        logger.info("Waiting for PTT button press …")
        # gpiozero events fire on rising/falling edges.
        # When pull_up=True, pressing → falling edge (1→0).
        self._pin.wait_for_inactive()  # waits for value == 0

    def wait_for_release(self) -> None:
        """Block until the button is released (pin goes high)."""
        self._pin.wait_for_active()    # waits for value == 1

    def close(self) -> None:
        self._pin.close()
