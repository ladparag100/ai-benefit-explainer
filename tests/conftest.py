import sys
from pathlib import Path

# Allow `import app...` when pytest is run from the repo root without an
# editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

ALL_MEMBER_IDS = ["M001", "M002", "M003", "M004", "M005", "M006"]


@pytest.fixture
def all_member_ids() -> list[str]:
    return ALL_MEMBER_IDS
