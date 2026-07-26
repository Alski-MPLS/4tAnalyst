import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import render_report  # noqa: E402


def _minimal_payload(**overrides):
    payload = {
        "ticket_id": None,
        "request": {
            "src": "10.20.20.0/24", "dst": "10.1.1.7/32", "service": "https",
            "justification": "test", "firewalls": ["FortiWiFi-71G"],
        },
        "zone_verdict": {
            "verdict": "BLOCKED", "src_zones": ["WAN-Zone"],
            "dst_zones": ["Internal-Zone"], "governing": [],
        },
        "existing_rules": {},
        "naming": {"objects": []},
        "logging": {
            "rule_type": "block_all", "log_start": False, "log_end": True,
            "alert_on_match": False, "retention_days": 90,
            "siem_forward": True, "notes": "",
        },
        "approval": {
            "risk_level": "high", "approvers": [], "peer_review": True,
            "security_review": True, "change_window": "", "sla_hours": 72,
        },
        "recommendation": "test",
        "cli": {"status": "blocked_exception", "per_firewall": []},
    }
    payload.update(overrides)
    return payload


def test_validate_payload_accepts_minimal_valid_payload():
    render_report.validate_payload(_minimal_payload())  # should not raise


def test_validate_payload_rejects_missing_top_level_key():
    payload = _minimal_payload()
    del payload["approval"]
    try:
        render_report.validate_payload(payload)
        assert False, "expected PayloadError"
    except render_report.PayloadError as exc:
        assert "approval" in str(exc)


def test_validate_payload_rejects_invalid_cli_status():
    payload = _minimal_payload(cli={"status": "not_a_real_status", "per_firewall": []})
    try:
        render_report.validate_payload(payload)
        assert False, "expected PayloadError"
    except render_report.PayloadError as exc:
        assert "not_a_real_status" in str(exc)


def test_output_dir_name_uses_ticket_id_when_present():
    payload = _minimal_payload(ticket_id="CHG0012345")
    assert render_report.output_dir_name(payload) == "CHG0012345"


def test_output_dir_name_falls_back_to_timestamp_when_absent():
    payload = _minimal_payload(ticket_id=None)
    name = render_report.output_dir_name(payload)
    assert re.match(r"^\d{4}-\d{2}-\d{2}_\d{4}$", name), name


def test_render_conf_already_covered_has_no_cli_commands():
    payload = _minimal_payload(cli={"status": "already_covered", "per_firewall": []})
    conf = render_report.render_conf(payload)
    assert "STATUS: ALLOWED -- already covered" in conf
    assert "config firewall" not in conf


def test_render_conf_unknown_no_action_has_no_cli_commands():
    payload = _minimal_payload(cli={"status": "unknown_no_action", "per_firewall": []})
    conf = render_report.render_conf(payload)
    assert "STATUS: UNKNOWN" in conf
    assert "config firewall" not in conf


def test_render_conf_blocked_exception_includes_banner_and_commands():
    payload = _minimal_payload(cli={
        "status": "blocked_exception",
        "per_firewall": [{
            "firewall": "FortiWiFi-71G",
            "address_objects": [{"cli": "config firewall address\nedit \"H_10.1.1.7\"\nend"}],
            "policy": {"cli": "config firewall policy\nedit 0\nend", "name": "x"},
            "warnings": ["destination interface mismatch: example warning"],
        }],
    })
    conf = render_report.render_conf(payload)
    assert "STATUS: BLOCKED" in conf
    assert "FortiWiFi-71G" in conf
    assert "config firewall address" in conf
    assert "config firewall policy" in conf
    assert "WARNING: destination interface mismatch: example warning" in conf


def test_render_conf_substitutes_ticket_id_placeholder():
    payload = _minimal_payload(ticket_id="CHG0099999", cli={
        "status": "new_rule",
        "per_firewall": [{
            "firewall": "FortiWiFi-71G",
            "address_objects": [],
            "policy": {"cli": "edit \"<TICKET_ID>_WAN_TO_FTG_TEST_001\"", "name": ""},
            "warnings": [],
        }],
    })
    conf = render_report.render_conf(payload)
    assert "CHG0099999_WAN_TO_FTG_TEST_001" in conf
    assert "<TICKET_ID>" not in conf


def test_render_conf_keeps_placeholder_when_no_ticket_id():
    payload = _minimal_payload(ticket_id=None, cli={
        "status": "new_rule",
        "per_firewall": [{
            "firewall": "FortiWiFi-71G",
            "address_objects": [],
            "policy": {"cli": "edit \"<TICKET_ID>_WAN_TO_FTG_TEST_001\"", "name": ""},
            "warnings": [],
        }],
    })
    conf = render_report.render_conf(payload)
    assert "<TICKET_ID>_WAN_TO_FTG_TEST_001" in conf


def test_render_html_contains_key_sections_and_values():
    payload = _minimal_payload(ticket_id="CHG0012345")
    output = render_report.render_html(payload)
    assert "<!DOCTYPE html>" in output
    assert "CHG0012345" in output
    assert "10.20.20.0/24" in output
    assert "10.1.1.7/32" in output
    assert "BLOCKED" in output
    assert "verdict-blocked" in output
    assert "Zone Policy Verdict" in output
    assert "Existing Rules on Named Firewalls" in output
    assert "Object Naming" in output
    assert "Logging Requirements" in output
    assert "Approval Requirements" in output
    assert "Recommendation" in output


def test_render_html_escapes_untrusted_text_fields():
    payload = _minimal_payload(recommendation="<script>alert(1)</script>")
    output = render_report.render_html(payload)
    assert "<script>alert(1)</script>" not in output
    assert "&lt;script&gt;" in output


def test_render_html_includes_warnings_section_when_present():
    payload = _minimal_payload(cli={
        "status": "blocked_exception",
        "per_firewall": [{
            "firewall": "FortiWiFi-71G",
            "address_objects": [],
            "policy": {"cli": "", "name": ""},
            "warnings": ["destination interface mismatch: example warning"],
        }],
    })
    output = render_report.render_html(payload)
    assert "Warnings" in output
    assert "destination interface mismatch: example warning" in output


def test_render_html_omits_warnings_section_when_absent():
    payload = _minimal_payload(cli={"status": "already_covered", "per_firewall": []})
    output = render_report.render_html(payload)
    assert "<h2>Warnings</h2>" not in output


import json as _json  # noqa: E402


def test_main_writes_both_files_under_ticket_id_folder(tmp_path):
    data_file = tmp_path / "payload.json"
    data_file.write_text(_json.dumps(_minimal_payload(ticket_id="CHG0012345")))
    outdir = tmp_path / "output"

    rc = render_report.main(["--data", str(data_file), "--outdir", str(outdir)])

    assert rc == 0
    assert (outdir / "CHG0012345" / "report.html").exists()
    assert (outdir / "CHG0012345" / "implementation.conf").exists()


def test_main_writes_both_files_under_timestamp_folder_when_no_ticket(tmp_path):
    data_file = tmp_path / "payload.json"
    data_file.write_text(_json.dumps(_minimal_payload(ticket_id=None)))
    outdir = tmp_path / "output"

    rc = render_report.main(["--data", str(data_file), "--outdir", str(outdir)])

    assert rc == 0
    subdirs = list(outdir.iterdir())
    assert len(subdirs) == 1
    assert re.match(r"^\d{4}-\d{2}-\d{2}_\d{4}$", subdirs[0].name)
    assert (subdirs[0] / "report.html").exists()
    assert (subdirs[0] / "implementation.conf").exists()


def test_main_overwrites_existing_files_for_same_ticket(tmp_path):
    data_file = tmp_path / "payload.json"
    data_file.write_text(_json.dumps(_minimal_payload(ticket_id="CHG0012345", recommendation="first run")))
    outdir = tmp_path / "output"
    render_report.main(["--data", str(data_file), "--outdir", str(outdir)])

    data_file.write_text(_json.dumps(_minimal_payload(ticket_id="CHG0012345", recommendation="second run")))
    render_report.main(["--data", str(data_file), "--outdir", str(outdir)])

    html_content = (outdir / "CHG0012345" / "report.html").read_text()
    assert "second run" in html_content
    assert "first run" not in html_content


def test_main_rejects_malformed_payload_and_writes_no_files(tmp_path, capsys):
    payload = _minimal_payload()
    del payload["approval"]
    data_file = tmp_path / "payload.json"
    data_file.write_text(_json.dumps(payload))
    outdir = tmp_path / "output"

    rc = render_report.main(["--data", str(data_file), "--outdir", str(outdir)])

    assert rc == 1
    assert not outdir.exists()
    captured = capsys.readouterr()
    assert "approval" in captured.err


def test_main_rejects_unparseable_json(tmp_path, capsys):
    data_file = tmp_path / "payload.json"
    data_file.write_text("{not valid json")
    outdir = tmp_path / "output"

    rc = render_report.main(["--data", str(data_file), "--outdir", str(outdir)])

    assert rc == 1
    assert not outdir.exists()
    captured = capsys.readouterr()
    assert "error" in captured.err


def test_render_conf_includes_group_append_alternative():
    payload = _minimal_payload(cli={
        "status": "new_rule",
        "per_firewall": [{
            "firewall": "FW1",
            "warnings": [],
            "address_objects": [{"cli": "config firewall address\n    edit \"H_10.9.8.7\"\nend"}],
            "policy": {"cli": "config firewall policy\nend"},
            "alternative": {
                "summary": "Extend existing rule #20 'publish-hosts' by appending "
                           "'H_10.9.8.7' to its destination group 'GRP_PUB'.",
                "package": "pkgA", "policy_id": 20, "policy_name": "publish-hosts",
                "side": "destination", "group": "GRP_PUB",
                "member_name": "H_10.9.8.7",
                "member_cli": "config firewall address\n    edit \"H_10.9.8.7\"\nend",
                "group_cli": "config firewall addrgrp\n    edit \"GRP_PUB\"\n"
                             "        append member \"H_10.9.8.7\"\n    next\nend",
                "affected_rules": [{"package": "pkgA", "policy_id": 30,
                                    "name": "other", "side": "source",
                                    "status": "enable", "via": ["GRP_PUB"]}],
                "warnings": ["Appending to group 'GRP_PUB' also changes 1 other rule(s)."],
            },
        }],
    })
    conf = render_report.render_conf(payload)
    assert "OPTION A" in conf and "OPTION B" in conf
    assert 'append member "H_10.9.8.7"' in conf
    assert "ALSO AFFECTS" in conf and "#30" in conf
    html_out = render_report.render_html(payload)
    assert "Alternative: Extend Existing Group" in html_out
    assert "GRP_PUB" in html_out
