from __future__ import annotations

import json
import logging

import pytest

from config.settings import settings
from core.logging_setup import JsonFormatter, setup_logging


def test_setup_logging_uses_json_formatter_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "log_level", "DEBUG")
    setup_logging()

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_json_formatter_includes_message_and_extra() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.run_id = "run_1"
    payload = json.loads(formatter.format(record))
    assert payload["message"] == "hello"
    assert payload["run_id"] == "run_1"
