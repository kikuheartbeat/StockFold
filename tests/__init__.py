"""Keep disposable SQLite files inside the authorized project workspace."""
from pathlib import Path
import tempfile

TEST_TMP=Path(__file__).resolve().parents[1]/'tmp'/'tests'
TEST_TMP.mkdir(parents=True,exist_ok=True)
tempfile.tempdir=str(TEST_TMP)
