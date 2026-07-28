"""The scenario suite: hand-crafted incident fixtures with known root
causes, used to evaluate agents against corrupted telemetry.
"""

from .definitions import ALL_SCENARIOS
from .matrix import single_axis_matrix

__all__ = ["ALL_SCENARIOS", "single_axis_matrix"]
