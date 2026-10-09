"""Retry-policy unit tests: permanent fails fast, transient recovers via retry."""
import app.services.jobs as jobs_mod
from app.services.jobs import _generate_with_retry, _is_permanent
from app.services.storage import LocalStorage


def test_permanent_errors_fail_fast():
    assert _is_permanent(ValueError("bad")) is True
    assert _is_permanent(TypeError("bad")) is True
    assert _is_permanent(RuntimeError("simulated generation failure for x")) is True
    assert _is_permanent(OSError("disk hiccup")) is False
    assert _is_permanent(RuntimeError("database is locked")) is False


def test_transient_recovers_on_retry(tmp_path):
    calls = {"n": 0}

    def flaky(path, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient disk hiccup")
        from app.services.generator import generate_certificate_pdf as real
        return real(path, *a, **k)

    jobs_mod.generate_certificate_pdf = flaky
    try:
        storage = LocalStorage(str(tmp_path))
        path, attempts = _generate_with_retry(storage, "j1", "c1", "Asha", "Python", "Acme", 2)
        assert attempts == 2 and calls["n"] == 2
    finally:
        from app.services.generator import generate_certificate_pdf as real
        jobs_mod.generate_certificate_pdf = real


def test_permanent_does_not_retry(tmp_path):
    calls = {"n": 0}

    def always_bad(path, *a, **k):
        calls["n"] += 1
        raise ValueError("bad data forever")

    jobs_mod.generate_certificate_pdf = always_bad
    try:
        import pytest as _pt
        storage = LocalStorage(str(tmp_path))
        with _pt.raises(ValueError):
            _generate_with_retry(storage, "j1", "c2", "X", "Y", "Z", 2)
        assert calls["n"] == 1  # failed fast, no retries wasted
    finally:
        from app.services.generator import generate_certificate_pdf as real
        jobs_mod.generate_certificate_pdf = real
