import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_numbers", ROOT / "paper" / "check_numbers.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

DOC = "\\begin{document}\n%s\n\\bibliographystyle{x}"


def test_paper_matches_results():
    bad = check.unverified((ROOT / "paper/main.tex").read_text(), (ROOT / "docs/RESULTS.md").read_text())
    assert not bad, f"numbers in paper/main.tex missing from docs/RESULTS.md: {bad}"


def test_checker_catches_drift_and_ignores_noise():
    results = "mAP50 0.156, 7,417 ships, 1297 checked"
    ok = DOC % "mAP 0.16 on 7417 and 1,297 ships, 3 regions, YOLO26n, \\tbd{0.99 \\url{x{1}}} % 555"
    assert check.unverified(ok, results) == []
    assert check.unverified(DOC % "mAP 0.17 on 7418 ships", results) == ["0.17", "7418"]
    assert check.unverified(DOC % "width 17mm, 4pt", results) == []
