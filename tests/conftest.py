import pytest
from controller.db import store

@pytest.fixture(autouse=True)
def clean_cluster_state():
    store.clear()
    yield
    store.clear()
