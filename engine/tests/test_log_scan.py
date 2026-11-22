import json

from conftest import BACKEND
from dpdp_lens.scanners import log_scan


def test_log_scan_finds_v3(raw_pii):
    findings = log_scan.scan(str(BACKEND))
    assert [f.check for f in findings] == ["log_pii"]
    f = findings[0]
    assert f.evidence.location.file == "app/main.py"
    assert f.evidence.masked_sample == 'logger.info("signup email=%s aadhaar=%s", req.email, req.aadhaar)'
    assert f.evidence.summary == "Log call includes email, aadhaar"
    lines = (BACKEND / "app" / "main.py").read_text().splitlines()
    assert lines[f.evidence.location.line - 2].strip() == "# PLANTED V3"
    dumped = json.dumps(f.model_dump())
    for raw in raw_pii:
        assert raw not in dumped


def test_user_id_only_and_plain_text_not_flagged(tmp_path):
    (tmp_path / "ok.py").write_text(
        "import logging\n"
        "logger = logging.getLogger('x')\n"
        "def f(user_id):\n"
        "    logger.info('signup ok user_id=%s', user_id)\n"
        "    logger.info(f'signup ok {user_id}')\n"
        "    logger.info('email sent')\n"
        "    print('done')\n")
    assert log_scan.scan(str(tmp_path)) == []


def test_flags_print_fstring_and_subscript(tmp_path):
    (tmp_path / "bad.py").write_text(
        "import logging\n"
        "def f(password, data):\n"
        "    print(f'pw {password}')\n"
        "    logging.warning('x %s', data['phone'])\n")
    findings = log_scan.scan(str(tmp_path))
    assert [(f.evidence.location.line, f.evidence.summary) for f in findings] == [
        (3, "Log call includes password"), (4, "Log call includes phone")]
