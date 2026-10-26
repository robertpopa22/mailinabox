"""Effective sshd configuration lookup and old-OpenSSH compatibility."""
import importlib.util
from pathlib import Path


_UTILS_PATH = Path(__file__).parents[1] / "management" / "utils.py"
_UTILS_SPEC = importlib.util.spec_from_file_location("miab_utils_test", _UTILS_PATH)
utils = importlib.util.module_from_spec(_UTILS_SPEC)
_UTILS_SPEC.loader.exec_module(utils)


def test_prefers_effective_g_dump_and_reads_nondefault_port(monkeypatch):
	commands = []
	def fake_shell(method, args, **kwargs):
		commands.append((method, args, kwargs))
		return 0, "port 2222\npasswordauthentication no\n"
	monkeypatch.setattr(utils, "shell", fake_shell)

	assert utils.get_ssh_config_value("port") == "2222"
	assert len(commands) == 1
	assert commands[0][0:2] == ("check_output", ["sshd", "-G"])
	assert commands[0][2]["capture_stderr"] is True
	assert commands[0][2]["trap"] is True


def test_invalid_config_diagnostic_does_not_fallback_to_t(monkeypatch):
	commands = []
	def fake_shell(method, args, **kwargs):
		commands.append(args)
		return 255, "sshd: /etc/ssh/sshd_config: line 4: Bad configuration option: ExampleOption\n"
	monkeypatch.setattr(utils, "shell", fake_shell)

	assert utils.get_ssh_config_value("port") is None
	assert commands == [["sshd", "-G"]]


def test_unrecognized_g_option_uses_t_fallback(monkeypatch):
	commands = []
	def fake_shell(method, args, **kwargs):
		commands.append((args, kwargs))
		if args == ["sshd", "-G"]:
			return 1, "sshd: illegal option -- G\n"
		return 0, "port 2200\npasswordauthentication yes\n"
	monkeypatch.setattr(utils, "shell", fake_shell)

	assert utils.get_ssh_config_value("port") == "2200"
	assert [call[0] for call in commands] == [["sshd", "-G"], ["sshd", "-T"]]
	assert all(call[1]["capture_stderr"] is True and call[1]["trap"] is True for call in commands)


def test_unrecognized_g_with_failed_t_stays_unknown(monkeypatch):
	commands = []
	def fake_shell(method, args, **kwargs):
		commands.append(args)
		if args == ["sshd", "-G"]:
			return 1, "sshd: unknown option -- G\n"
		return 255, "sshd: /etc/ssh/sshd_config: Bad configuration option\n"
	monkeypatch.setattr(utils, "shell", fake_shell)

	assert utils.get_ssh_config_value("port") is None
	assert commands == [["sshd", "-G"], ["sshd", "-T"]]


def test_missing_sshd_binary_stays_unknown_without_fallback(monkeypatch):
	commands = []
	def fake_shell(method, args, **kwargs):
		commands.append(args)
		raise FileNotFoundError("sshd")
	monkeypatch.setattr(utils, "shell", fake_shell)

	assert utils.get_ssh_config_value("port") is None
	assert commands == [["sshd", "-G"]]


def test_malformed_successful_g_output_is_not_treated_as_config(monkeypatch):
	commands = []
	def fake_shell(method, args, **kwargs):
		commands.append(args)
		return 0, "sshd: warning: not a configuration row\nport 2222\n"
	monkeypatch.setattr(utils, "shell", fake_shell)

	assert utils.get_ssh_config_value("port") is None
	assert commands == [["sshd", "-G"]]


def test_valid_other_directives_may_have_trailing_whitespace_or_empty_values(monkeypatch):
	outputs = [
		"port 2222\nsubsystem sftp /usr/lib/openssh/sftp-server   \n",
		"port 2222  \noptionalsetting \n",
	]
	for output in outputs:
		monkeypatch.setattr(utils, "shell", lambda *args, _output=output, **kwargs: (0, _output))
		assert utils.get_ssh_config_value("port") == "2222"


def test_requested_empty_or_duplicate_values_are_unknown(monkeypatch):
	for output in ("port \n", "port 2222\nport 2223\n"):
		monkeypatch.setattr(utils, "shell", lambda *args, _output=output, **kwargs: (0, _output))
		assert utils.get_ssh_config_value("port") is None


def test_old_overlay_hook_is_updated_without_duplicate_block(tmp_path):
	import importlib.util
	from pathlib import Path

	path = Path(__file__).parents[1] / "management" / "geseidl_edition" / "apply_overlay.py"
	spec = importlib.util.spec_from_file_location("apply_overlay_legacy_test", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	hook = next(h for h in module.HOOKS if h["name"] == "status_checks:ssh-config-unknown")
	legacy = ("def run_services_checks(env, output, pool):\n"
			  "\tservices = get_services(env)\n"
			  "\t" + module.MARK_START + "\n"
			  "\tif any(service[\"name\"] == \"SSH Login (ssh)\" and service[\"port\"] is None for service in services):\n"
			  "\t\toutput.print_warning(\"SSH configuration could not be read (sshd -T); SSH port and firewall status are unknown.\")\n"
			  "\t\tall_running = False\n"
			  "\t" + module.MARK_END + "\n")
	(tmp_path / "status_checks.py").write_text(legacy, encoding="utf-8")
	module.MGMT_DIR = str(tmp_path)

	assert module.apply_hook(hook) == "updated"
	result = (tmp_path / "status_checks.py").read_text(encoding="utf-8")
	assert result.count("SSH configuration could not be read") == 1
	assert "(sshd configuration dump)" in result
	assert "(sshd -T)" not in result
	assert module.apply_hook(hook) == "already"


def test_modified_legacy_overlay_hook_is_refused_without_losing_wip(tmp_path):
	import importlib.util
	from pathlib import Path

	path = Path(__file__).parents[1] / "management" / "geseidl_edition" / "apply_overlay.py"
	spec = importlib.util.spec_from_file_location("apply_overlay_wip_test", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	hook = next(h for h in module.HOOKS if h["name"] == "status_checks:ssh-config-unknown")
	legacy = hook["legacy_blocks"][0].replace(
		"\t\toutput.print_warning(\"SSH configuration could not be read (sshd -T); SSH port and firewall status are unknown.\")\n",
		"\t\tcustom_wip_guard()\n",
	)
	path = tmp_path / "status_checks.py"
	path.write_text("def run_services_checks(env, output, pool):\n\tservices = get_services(env)\n" + legacy + "\n",
				encoding="utf-8")
	module.MGMT_DIR = str(tmp_path)
	before = path.read_text(encoding="utf-8")

	assert module.apply_hook(hook) == "legacy-block-modified"
	assert path.read_text(encoding="utf-8") == before
	assert "custom_wip_guard()" in before


def test_modified_legacy_hook_fails_command_without_success_stamp(monkeypatch):
	import pytest
	path = Path(__file__).parents[1] / "management" / "geseidl_edition" / "apply_overlay.py"
	spec = importlib.util.spec_from_file_location("overlay_refusal_command", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	monkeypatch.setattr(module, "HOOKS", [{"name": "fixture"}])
	monkeypatch.setattr(module, "apply_hook", lambda hook: "legacy-block-modified")
	stamps = []
	monkeypatch.setattr(module, "write_stamp", lambda: stamps.append(True))
	with pytest.raises(RuntimeError, match="stamp not updated"):
		module.main(["apply_overlay.py", "apply"])
	assert stamps == []
