import logging

import pytest

from core.log import HANDLER_NAME, configure_logging


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def _our_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if h.get_name() == HANDLER_NAME]


def test_defaults_to_info(monkeypatch):
    monkeypatch.delenv("CFPB_LOG_LEVEL", raising=False)
    configure_logging()
    assert logging.getLogger().level == logging.INFO


def test_level_from_env(monkeypatch):
    monkeypatch.setenv("CFPB_LOG_LEVEL", "debug")
    configure_logging()
    assert logging.getLogger().level == logging.DEBUG


def test_argument_overrides_env(monkeypatch):
    monkeypatch.setenv("CFPB_LOG_LEVEL", "DEBUG")
    configure_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING


def test_idempotent():
    configure_logging("INFO")
    configure_logging("DEBUG")
    assert len(_our_handlers()) == 1
    assert logging.getLogger().level == logging.DEBUG


def test_invalid_level_raises():
    with pytest.raises(ValueError, match="NOPE"):
        configure_logging("NOPE")


def test_format_includes_level_and_logger_name(capsys):
    configure_logging("INFO")
    logging.getLogger("ingestion.example").info("hello %s", "world")
    err = capsys.readouterr().err
    assert "INFO ingestion.example hello world" in err
