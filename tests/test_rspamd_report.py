import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "setup/geseidl_edition/zones/spam/rspamd_report.py"
SPEC = importlib.util.spec_from_file_location("rspamd_learn_report", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_ai_log_counts_only_final_summaries_in_window_and_detects_timeout(tmp_path):
    log = tmp_path / 'rspamd.log'
    log.write_text('\n'.join([
        '2026-10-10 11:00:00 gpt.lua:99 request failed: IO timeout',
        '2026-10-11 11:00:00 gpt.lua:99 request failed: IO timeout',
        '2026-10-11 11:00:01 debug GPT_UNCERTAIN(0)',
        '2026-10-11 11:00:01 rspamd_task_write_log: GPT_UNCERTAIN(0),GPT_BACKEND_UNAVAILABLE(0)',
        '2026-10-11 11:01:01 rspamd_task_write_log: GPT_SPAM(3.6),GPT_PHISHING(1)',
    ]))
    stats = MODULE.get_gpt_stats([log], MODULE.datetime(2026, 10, 11, 12))
    assert stats['available']
    assert stats['timeouts'] == stats['backend_errors'] == 1
    assert stats['GPT_UNCERTAIN'] == stats['GPT_BACKEND_UNAVAILABLE'] == 1
    alerts, notes = [], []
    assert MODULE.apply_gpt_health('OK', alerts, notes, stats) == 'ALERT'
    assert len(alerts) == 1
    assert MODULE.apply_gpt_health('EROARE', [], [], stats) == 'EROARE'


def test_ai_missing_logs_unknown_and_true_uncertainty_is_not_outage(tmp_path):
    now = MODULE.datetime(2026, 10, 11, 12)
    stats = MODULE.get_gpt_stats([tmp_path / 'missing'], now)
    assert not stats['available']
    assert MODULE.apply_gpt_health('OK', [], [], stats) == 'ALERT'
    log = tmp_path / 'rspamd.log'
    log.write_text('2026-10-11 11:00:01 rspamd_task_write_log: GPT_UNCERTAIN(0)')
    stats = MODULE.get_gpt_stats([log], now)
    assert stats['GPT_UNCERTAIN'] == 1
    assert MODULE.apply_gpt_health('OK', [], [], stats) == 'OK'


def test_disabled_gpt_keeps_history_informational_and_active_failures_visible(tmp_path):
    stats=MODULE.get_gpt_stats([tmp_path/'absent'], MODULE.datetime(2026,10,16,8))
    stats['backend_errors']=27
    notes=[]
    assert MODULE.apply_gpt_health('OK',[],notes,stats,enabled=False)=='OK'
    assert '27' in notes[0] and 'dezactivat' in notes[0]
    assert MODULE.apply_gpt_health('EROARE',['milter missing'],[],stats,enabled=False)=='EROARE'
    assert MODULE.apply_gpt_health('OK',[],[],stats,enabled=None)=='ALERT'


def test_rule_update_freshness_and_missing_are_explicit(tmp_path):
    from datetime import timezone
    now=MODULE.datetime(2026,10,11,12,tzinfo=timezone.utc)
    path=tmp_path/'status.json'
    assert MODULE.get_rule_update_status(path,now)['status']=='UNKNOWN'
    path.write_text('{"status":"OK","checked_at":"2026-10-11T11:00:00+00:00"}')
    assert MODULE.get_rule_update_status(path,now)['status']=='OK'
    path.write_text('{"status":"OK","checked_at":"2026-10-08T11:00:00+00:00"}')
    assert MODULE.get_rule_update_status(path,now)['status']=='STALE'


def test_zero_learned_with_healthy_scanning_is_ok():
    status, alerts, notes = MODULE.assess_health(
        0, 75, 200, 1000, True,
        {"rspamd": True, "redis-server": True, "postfix": True, "dovecot": True},
    )
    assert status == "OK"
    assert alerts == []
    assert notes == []


def test_zero_learned_with_failed_attempts_warns():
    status, alerts, _notes = MODULE.assess_health(
        0, 75, 200, 1000, True,
        {"rspamd": True, "redis-server": True, "postfix": True, "dovecot": True},
        learn_failures=2,
    )
    assert status == "ALERT"
    assert "2 incercari" in alerts[0]


def test_missing_milter_remains_critical():
    status, alerts, _notes = MODULE.assess_health(
        0, 75, 200, 1000, False,
        {"rspamd": True, "redis-server": True, "postfix": True, "dovecot": True},
    )
    assert status == "EROARE"
    assert any("LIPSESTE" in alert for alert in alerts)


def test_low_positive_scan_volume_is_ok():
    status, alerts, _notes = MODULE.assess_health(
        0, 1, 200, 1000, True,
        {"rspamd": True, "redis-server": True, "postfix": True, "dovecot": True},
    )
    assert status == "OK"
    assert alerts == []


def test_zero_scans_without_inbound_evidence_warns_as_inconclusive():
    status, alerts, notes = MODULE.assess_health(
        0, 0, 200, 1000, True,
        {"rspamd": True, "redis-server": True, "postfix": True, "dovecot": True},
        inbound_received=None,
    )
    assert status == "ALERT"
    assert alerts == []
    assert "neconcludenta" in notes[0]


def test_unknown_service_collector_warns_without_claiming_down():
    status, alerts, notes = MODULE.assess_health(
        0, 75, 200, 1000, True,
        {"rspamd": None, "redis-server": True, "postfix": True, "dovecot": True},
    )
    assert status == "ALERT"
    assert alerts == []
    assert "rspamd" in notes[0]


def test_failed_journal_collector_is_unknown_not_zero(monkeypatch):
    monkeypatch.setattr(MODULE, "run_result", lambda command, timeout=30: (0, "active"))

    def fail_journal(*_args, **_kwargs):
        raise OSError("journal unavailable")

    monkeypatch.setattr(MODULE.subprocess, "run", fail_journal)
    services, learn_failures, inbound_received = MODULE.get_runtime_evidence()
    assert all(services.values())
    assert learn_failures is None
    assert inbound_received is None


def test_zero_scans_with_acceptance_evidence_is_warn_not_false_critical():
    status, alerts, _notes = MODULE.assess_health(
        0, 0, 200, 1000, True,
        {"rspamd": True, "redis-server": True, "postfix": True, "dovecot": True},
        inbound_received=3,
    )
    assert status == "ALERT"
    assert alerts == []
    assert "3 acceptari" in _notes[0]


def test_inactive_runtime_service_is_critical():
    status, alerts, _notes = MODULE.assess_health(
        0, 75, 200, 1000, True,
        {"rspamd": False, "redis-server": True, "postfix": True, "dovecot": True},
    )
    assert status == "EROARE"
    assert "rspamd" in alerts[0]


def test_learn_failure_does_not_downgrade_inactive_service():
    status, alerts, _notes = MODULE.assess_health(
        0, 75, 200, 1000, True,
        {"rspamd": False, "redis-server": True, "postfix": True, "dovecot": True},
        learn_failures=2,
    )
    assert status == "EROARE"
    assert any("inactive" in alert for alert in alerts)
    assert any("invatare" in alert for alert in alerts)


def test_neural_status_uses_effective_config_and_does_not_equate_keys_with_enablement(monkeypatch):
    outputs = {
        "timeout 15 rspamadm configdump neural 2>/dev/null": "enabled = false;\n",
        "rspamc counters 2>/dev/null": "NEURAL_SPAM_SHORT 0 0.0\n",
        "redis-cli --scan --pattern 'rn_*' 2>/dev/null": "rn_model_a\n",
    }
    monkeypatch.setattr(MODULE, "run", lambda command, timeout=30: outputs.get(command, ""))
    monkeypatch.setattr(MODULE, "run_result", lambda command, timeout=30: (0, outputs.get(command, "")))
    status = MODULE.get_neural_status()
    assert status["enabled"] is False
    assert status["model_stored"] is True
    assert status["config_source"] == "rspamadm configdump neural"


def test_report_source_has_no_destructive_footer():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Dezactivare: rm " not in source


def test_send_report_is_multipart_html_and_escapes(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def send_message(self, message): sent.append(message)

    monkeypatch.setattr(MODULE.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(MODULE, "REPORT_TO", "operator@example.com")
    monkeypatch.setattr(MODULE, "REPORT_FROM", "report@example.com")
    MODULE.send_report("subject <x>", "body <script>", status="WARN")
    message = sent[0]
    assert message.is_multipart()
    assert message["X-Geseidl-Status"] == "WARN"
    assert "&lt;script&gt;" in message.get_body(preferencelist=("html",)).get_content()


def test_missing_report_binding_refuses_send(monkeypatch):
    import pytest
    monkeypatch.setattr(MODULE, 'REPORT_TO', None)
    with pytest.raises(ValueError): MODULE.send_report('test','test')
