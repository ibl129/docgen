"""Tests voor de contract-signaallogica en hulpfuncties in app.py (8 jun 2026).

Test de PURE functies (geen DB/Flask/mail nodig): de signaal-beslissing, het parsen
van signaal_dagen en het samenstellen van accounthouder-velden. De functies worden
uit app.py geïsoleerd via AST, zoals tests/test_docx_render.py.

Run:  python3 tests/test_contract.py
"""

import ast
import os
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(names):
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    mod = ast.parse(src)
    glb = {"date": date, "timedelta": timedelta}
    for node in mod.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            exec(ast.get_source_segment(src, node), glb)
    return glb


_FN = _load({"bepaal_contract_signalen", "_parse_signaal_dagen", "_accounthouder_velden"})
bepaal = _FN["bepaal_contract_signalen"]
parse_dagen = _FN["_parse_signaal_dagen"]
accounthouder = _FN["_accounthouder_velden"]

T = date(2026, 6, 8)


def _names(sigs):
    return sorted((s["soort"], s["dagen"]) for s in sigs)


def test_parse_signaal_dagen():
    assert parse_dagen("60, 30, 7") == [60, 30, 7]
    assert parse_dagen("7;30;60") == [60, 30, 7]          # ; ook toegestaan, gesorteerd aflopend
    assert parse_dagen("30, 30, abc, -5, 0, 7") == [30, 7]  # uniek, geen rommel/negatief/0
    assert parse_dagen("") == []


def test_accounthouder_velden():
    gebruikers = [{"id": "u1", "email": "jan@x.nl", "naam": "Jan"}]
    assert accounthouder("", gebruikers) == {
        "accounthouder_id": None, "accounthouder_email": None, "accounthouder_naam": None}
    assert accounthouder("u1", gebruikers) == {
        "accounthouder_id": "u1", "accounthouder_email": "jan@x.nl", "accounthouder_naam": "Jan"}
    # onbekende id: id bewaard, geen e-mail/naam
    assert accounthouder("u9", gebruikers)["accounthouder_id"] == "u9"
    assert accounthouder("u9", gebruikers)["accounthouder_email"] is None


def test_signaal_vooraf_exact():
    r = bepaal(T, T + timedelta(days=30), [60, 30, 7], "concept", set())
    assert _names(r) == [("vooraf", 30)]


def test_signaal_vooraf_reeds_verstuurd():
    r = bepaal(T, T + timedelta(days=30), [60, 30, 7], "concept", {("vooraf", 30)})
    assert r == []


def test_signaal_geen_match():
    assert bepaal(T, T + timedelta(days=29), [60, 30, 7], "concept", set()) == []


def test_signaal_verlopen_op_einddatum():
    r = bepaal(T, T, [30], "concept", set())
    assert _names(r) == [("verlopen", None)]


def test_signaal_verlopen_na_einddatum():
    r = bepaal(T, T - timedelta(days=2), [30], "concept", set())
    assert _names(r) == [("verlopen", None)]


def test_signaal_al_verlopen_geen_dubbel():
    assert bepaal(T, T - timedelta(days=5), [30], "verlopen", set()) == []
    assert bepaal(T, T - timedelta(days=5), [30], "concept", {("verlopen", None)}) == []


def test_signaal_geen_einddatum():
    assert bepaal(T, None, [30], "concept", set()) == []


def _main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} geslaagd")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
