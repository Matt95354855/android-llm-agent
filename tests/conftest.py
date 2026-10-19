import pytest


@pytest.fixture
def settings(tmp_path):
    from control.config import Settings

    return Settings(
        access_token="jeton-de-test",
        data_dir=tmp_path,
        device_backend="demo",
        device_count=4,
        web_dist=tmp_path / "absent",
    )
