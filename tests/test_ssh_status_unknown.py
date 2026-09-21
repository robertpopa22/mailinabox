import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace


SOURCE = (Path(__file__).parents[1] / "management" / "status_checks.py").read_text(encoding="utf-8")


def test_overlay_hooks_reapply_ssh_unknown_fix_idempotently(tmp_path):
    path = Path(__file__).parents[1] / "management" / "geseidl_edition" / "apply_overlay.py"
    spec = importlib.util.spec_from_file_location("apply_overlay_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hooks = [hook for hook in module.HOOKS if hook["name"] in {
        "status_checks:ssh-config-unknown", "status_checks:firewall-skip-unknown-port"}]
    assert len(hooks) == 2
    source = ("def run_services_checks(env, output, pool):\n"
              "\tall_running = True\n"
              "\tservices = get_services(env)\n"
              "def check_ufw(env, output):\n"
              "\t\tfor service in get_services():\n"
              "\t\t\tif service[\"public\"] and not is_port_allowed(ufw, service[\"port\"]):\n"
              "\t\t\t\tpass\n")
    (tmp_path / "status_checks.py").write_text(source, encoding="utf-8")
    module.MGMT_DIR = str(tmp_path)
    assert [module.apply_hook(hook) for hook in hooks] == ["applied", "applied"]
    result = (tmp_path / "status_checks.py").read_text(encoding="utf-8")
    assert [module.apply_hook(hook) for hook in hooks] == ["already", "already"]
    assert (tmp_path / "status_checks.py").read_text(encoding="utf-8") == result
    assert "SSH configuration could not be read" in result
    assert 'service["port"] is not None' in result


def test_ssh_unknown_does_not_become_port_none_firewall_advice():
    tree = ast.parse(SOURCE)
    services = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_services_checks")
    ufw = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "check_ufw")
    services_source = ast.get_source_segment(SOURCE, services)
    ufw_source = ast.get_source_segment(SOURCE, ufw)
    assert "SSH configuration could not be read" in services_source
    assert 'service["port"] is not None' in ufw_source
    assert "Port None" not in ufw_source


def test_config_failure_reports_unknown_and_skips_firewall_port_advice():
    tree = ast.parse(SOURCE)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"run_services_checks", "check_ufw"}]
    namespace = {
        "get_services": lambda env=None: [{"name": "SSH Login (ssh)", "port": None, "public": True}],
        "get_spam_filter_type": lambda _env: "spamassassin",
        "check_service": lambda i, service, env: (i, None, None, None),
        "shell": lambda *args, **kwargs: (0, "Status: active\n"),
        "is_port_allowed": lambda *_args: False,
        "os": SimpleNamespace(path=SimpleNamespace(isfile=lambda _path: True)),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "status_checks.py", "exec"), namespace)

    class Output:
        def __init__(self): self.warnings = []; self.errors = []; self.ok = []
        def print_warning(self, value): self.warnings.append(value)
        def print_error(self, value): self.errors.append(value)
        def print_ok(self, value): self.ok.append(value)

    class Pool:
        def starmap(self, function, args, chunksize=1): return [function(*arg) for arg in args]

    output = Output()
    assert namespace["run_services_checks"]({}, output, Pool()) is True
    namespace["check_ufw"]({}, output)
    assert any("SSH configuration could not be read" in warning for warning in output.warnings)
    assert not output.errors
    assert "Firewall is active." in output.ok
