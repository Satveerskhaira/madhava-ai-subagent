import warnings
from datetime import date

import pytest

from rulegraph import Settings

import pharmacy_agents as pa

warnings.filterwarnings("ignore")

TODAY = date(2026, 10, 14)


@pytest.fixture(scope="session")
def knowledge():
    return pa.build(Settings(today=TODAY)).knowledge


@pytest.fixture()
def system(knowledge, tmp_path):
    return pa.build(Settings(today=TODAY, episodic_dir=tmp_path / "episodic"), knowledge=knowledge)
