import pytest
from helpers import build_telemetry

from langgraph_telemetry_fuzzer import Telemetry


@pytest.fixture
def telemetry() -> Telemetry:
    return build_telemetry()
