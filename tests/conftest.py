import os
import sys
import tempfile
from pathlib import Path

# Tests always run in mock mode with a throwaway data directory.
os.environ["GRADEAI_MODE"] = "mock"
os.environ.setdefault("GRADEAI_DATA_DIR", tempfile.mkdtemp(prefix="gradeai-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
