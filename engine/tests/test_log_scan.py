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


# ---- block 06 item 2: JavaScript and TypeScript
def js(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return [(f.evidence.location.file, f.evidence.location.line, f.evidence.summary) for f in log_scan.scan(str(tmp_path))]


def test_js_code_view_blanks_comments_and_string_text_but_keeps_template_code_and_line_breaks():
    src = 'a("email"); // user.email\n/* phone\n dob */ b(`x ${user.phone} y`, \'aadhaar\')\n'
    view = log_scan.js_code_view(src)
    assert len(view) == len(src) and view.count("\n") == src.count("\n")
    assert "email" not in view and "dob" not in view and "aadhaar" not in view and "user.phone" in view


def test_js_code_view_handles_nested_templates_escapes_and_a_division():
    view = log_scan.js_code_view("x = a / b; f(`a ${g(`b ${c}`)} \\` d`, 'it\\'s', \"q\")\n")
    assert "c" in view and "a / b" in view and "it" not in view.replace("it\\", "")


def test_js_logs_with_personal_data_are_found_with_file_line_and_names(tmp_path):
    out = js(tmp_path, {"app/s.js": 'const a = 1;\nconsole.log("signup", user.email);\n',
                        "app/t.ts": "logger.info({ aadhaar });\n", "app/u.js": "console.error(`bad ${req.body.phone}`);\n",
                        "app/v.jsx": "this.logger.warn(userEmail, dob)\n"})
    assert out == [("app/s.js", 2, "Log call includes email"), ("app/t.ts", 1, "Log call includes aadhaar"),
                   ("app/u.js", 1, "Log call includes phone"), ("app/v.jsx", 1, "Log call includes userEmail, dob")]


def test_js_comments_string_words_counters_and_other_calls_are_not_flagged(tmp_path):
    assert js(tmp_path, {"a.js": '// console.log(user.email)\n/* console.log(user.phone) */\nconsole.log("send email to the user");\n'
                                 "console.log(emailCount, phoneTotal, user_id);\nsend(user.email);\nconsole.log('started');\n"}) == []


def test_js_test_files_and_node_modules_are_skipped(tmp_path):
    bad = "console.log(user.email);\n"
    assert js(tmp_path, {"a.test.js": bad, "b.spec.ts": bad, "__tests__/c.js": bad, "node_modules/x/i.js": bad, "dist/o.js": bad, "m.min.js": bad}) == []


def test_js_evidence_never_holds_raw_personal_data_and_offers_no_fix(tmp_path):
    from stdnum import verhoeff
    partial = "23412341234"
    aadhaar = partial + verhoeff.calc_check_digit(partial)
    (tmp_path / "a.js").write_text(f'console.log("aadhaar {aadhaar}", user.aadhaar);\n')
    (f,) = log_scan.scan(str(tmp_path))
    assert aadhaar not in f.model_dump_json() and "XXXX XXXX" in f.evidence.masked_sample
    assert f.fix.available is False  # the verified fix template is for the Python demo app


def test_js_log_findings_get_distinct_fingerprints_per_file(tmp_path):
    from dpdp_lens.fingerprint import fingerprint
    (tmp_path / "a.js").write_text("console.log(user.email);\n")
    (tmp_path / "b.js").write_text("console.log(user.email);\n")
    a, b = log_scan.scan(str(tmp_path))
    assert fingerprint(a) != fingerprint(b)
