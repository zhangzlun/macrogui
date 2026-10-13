import importlib.util
from pathlib import Path


def test_handout_answers_match_the_library():
    path = Path(__file__).resolve().parent.parent / "math" / "check_examples.py"
    spec = importlib.util.spec_from_file_location("check_examples", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    wrong = [(h, q, e, a) for h, q, e, a, ok in module.run() if not ok]
    assert not wrong, wrong
