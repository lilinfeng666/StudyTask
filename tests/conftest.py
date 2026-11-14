from datetime import date

import pytest

from studytask import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "test.sqlite3"),
            "TODAY_PROVIDER": lambda: date(2026, 11, 14),
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()
