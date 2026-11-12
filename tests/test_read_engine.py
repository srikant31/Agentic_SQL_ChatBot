import database


def test_read_engine_falls_back_to_existing_engine_when_not_configured(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(database, "READONLY_DB_URI", None)
    monkeypatch.setattr(database, "get_engine", lambda: sentinel)
    database.get_read_engine.clear()
    try:
        assert database.get_read_engine() is sentinel
    finally:
        database.get_read_engine.clear()


def test_read_engine_uses_separate_account_when_configured(monkeypatch, tmp_path):
    privileged = object()
    monkeypatch.setattr(database, "READONLY_DB_URI", f"sqlite:///{tmp_path}/readonly.db")
    monkeypatch.setattr(database, "get_engine", lambda: privileged)
    monkeypatch.setattr(database, "create_engine", lambda uri, **kwargs: ("engine", uri))
    database.get_read_engine.clear()
    try:
        assert database.get_read_engine() == ("engine", f"sqlite:///{tmp_path}/readonly.db")
        assert database.get_read_engine() is not privileged
    finally:
        database.get_read_engine.clear()


def test_question_path_defaults_to_read_engine(monkeypatch):
    import context_pipeline
    sentinel = object()
    monkeypatch.setattr(database, "get_read_engine", lambda: sentinel)
    assert context_pipeline._engine(None) is sentinel
