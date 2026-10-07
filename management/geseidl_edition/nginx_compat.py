"""Version-aware rendering for the optional edition's installed nginx."""
import importlib.util
from pathlib import Path


def adapt_generated(text):
    root = Path(__file__).resolve().parents[2]
    if not (root / '.geseidl-edition').is_file():
        return text
    path = root / 'setup/geseidl_edition/components/nginx_http2.py'
    spec = importlib.util.spec_from_file_location('geseidl_nginx_http2', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.adapt(text, module.installed_version())
