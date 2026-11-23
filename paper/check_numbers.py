"""Every number in the paper must appear in docs/RESULTS.md (the submission rule).

    python paper/check_numbers.py        # exit 1 and list offenders if any

A decimal passes if some RESULTS value rounds to it (0.16 <- 0.156). Integers
<= 12 are skipped: too common to check meaningfully ("3 regions", "1 km").
Text inside \\tbd{...}, comments, tikz pictures and TeX lengths is ignored.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Values computed from RESULTS numbers rather than copied; each says how.
DERIVED = {
    "47.2": "Laconia matched share, 58 / 123 (§4e)",
    "0.054": "spread of overall mAP50 in §3, 0.402 - 0.348",
    "1.75": "AIS counting radius, 1 km + 750 m (§4d)",
    "15": "AIS-unmatched STS after the sidelobe fix, 14 Oman + 1 Laconia (§4g)",
}
NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")


def _drop_braced(s, cmd):
    """Remove every `cmd{...}` including nested braces."""
    out, i = [], 0
    while (j := s.find(cmd + "{", i)) >= 0:
        out.append(s[i:j])
        k, depth = j + len(cmd) + 1, 1
        while depth and k < len(s):
            depth += {"{": 1, "}": -1}.get(s[k], 0)
            k += 1
        i = k
    return "".join(out) + s[i:]


def paper_numbers(tex):
    body = tex.split(r"\begin{document}", 1)[-1].split(r"\bibliographystyle", 1)[0]
    body = re.sub(r"(?<!\\)%.*", "", body)                                   # comments
    body = re.sub(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", "", body, flags=re.S)
    body = _drop_braced(body, r"\tbd")
    body = re.sub(r"\d+(?:\.\d+)?\s*(?:mm|pt|cm|em|ex|\\columnwidth|\\textwidth)", "", body)
    body = re.sub(r"(?<=\d),(?=\d{3})", "", body)                           # 1,297 -> 1297
    return NUM.findall(body)


def unverified(tex, results):
    results = re.sub(r"(?<=\d),(?=\d{3})", "", results)
    known = NUM.findall(results)
    ints = {k for k in known if "." not in k}
    decs = [k for k in known if "." in k]
    bad = []
    for n in dict.fromkeys(paper_numbers(tex)):
        if n in DERIVED:
            continue
        if "." not in n:
            if int(n) > 12 and n not in ints:
                bad.append(n)
            continue
        d = len(n.split(".")[1])
        if not any(len(k.split(".")[1]) >= d and round(float(k), d) == float(n) for k in decs):
            bad.append(n)
    return bad


if __name__ == "__main__":
    bad = unverified((ROOT / "paper/main.tex").read_text(), (ROOT / "docs/RESULTS.md").read_text())
    print("all paper numbers found in RESULTS.md" if not bad else f"not in RESULTS.md: {bad}")
    sys.exit(1 if bad else 0)
