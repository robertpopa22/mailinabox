import importlib.util,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('report',ROOT/'setup/geseidl_edition/zones/spam/rspamd_report.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
def test_historical_timeout_needs_real_recovery_not_a_skipped_message(tmp_path):
    log=tmp_path/'rspamd.log';now=r.datetime(2026,10,12,12)
    log.write_text('2026-10-12 08:00:00 gpt.lua:99 request failed: IO timeout\n2026-10-12 11:00:01 rspamd_task_write_log: GPT_SKIPPED_DECIDED(0),GPT_UNCERTAIN(0)\n')
    d=r.get_gpt_stats([log],now);assert r.apply_gpt_health('OK',[],[],d)=='ALERT'
    with log.open('a') as f:f.write('2026-10-12 11:30:01 rspamd_task_write_log: GPT_HAM(-1)\n')
    d=r.get_gpt_stats([log],now);assert r.apply_gpt_health('OK',[],[],d)=='OK'
    assert d['timeouts']==1 and d['current_timeouts']==0 and d['current_model_results']==1
def test_fork_only_commit_compared_in_fork_namespace():
    import sys,io
    sys.path.insert(0,str(ROOT/'management'))
    from geseidl_edition.zones import status
    runs=[SimpleNamespace(stdout='a'*40),SimpleNamespace(stdout='https://github.com/example/miab.git')]
    response=io.StringIO(json.dumps({'ahead_by':2,'behind_by':4,'commits':[]}))
    with patch.object(status.subprocess,'run',side_effect=runs),patch.object(status.urllib.request,'urlopen',return_value=response) as request:
        got,error=status._upstream_commit_gap({'path':str(ROOT/'.geseidl-edition')})
    assert error is None and got[:2]==(4,2)
    assert request.call_args.args[0].full_url=='https://api.github.com/repos/example/miab/compare/'+'a'*40+'...mail-in-a-box:main'
