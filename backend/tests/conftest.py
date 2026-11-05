import os, pathlib, shutil, tempfile

TMP = pathlib.Path(tempfile.mkdtemp(prefix="platesense-tests-"))
os.environ.update(DATABASE_URL=f"sqlite:///{TMP / 'test.db'}", UPLOAD_DIR=str(TMP / "uploads"), MODEL_DIR=str(TMP / "models"),
                  DEBUG_RETURN_RESET_TOKEN="true", SECRET_KEY="test-secret-key-for-tests-only-0123456789")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from app import seed
    from app.main import app
    seed.run(n_students=60, days_back=45, reset=True, quiet=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def db():
    from app.db import SessionLocal
    s = SessionLocal()
    yield s
    s.close()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TMP, ignore_errors=True)
