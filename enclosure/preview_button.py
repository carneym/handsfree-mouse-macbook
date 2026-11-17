"""Render a proposed button location. Dimensions await switch selection."""
from build_enclosure import (
    LID_THICKNESS, RIM_Z, WIDTH, cylinder, make_base, make_lid, preview,
)

top = RIM_Z + LID_THICKNESS
button_x, button_y = 14.0, WIDTH / 2
lid = make_lid()
# Shallow protective recess and illustrative actuator opening.
lid -= cylinder(4.5, 1.7, (button_x, button_y, top - 0.7))
lid -= cylinder(2.8, 4.0, (button_x, button_y, RIM_Z - 1.0))
cap = cylinder(2.45, 1.0, (button_x, button_y, top - 1.4))
assert (lid ^ cap).volume() < 0.001
preview(make_base(), lid, button=cap)
print("Rendered button_concept.png. Switch mounting is provisional.")
