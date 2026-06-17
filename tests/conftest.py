import pytest


@pytest.fixture(autouse=True)
def configure_caplog(caplog):
    """Auto-configure caplog to capture INFO logs from hubcast routes."""
    caplog.set_level("INFO", logger="hubcast.web.github.routes")
    caplog.set_level("INFO", logger="hubcast.web.gitlab.routes")
