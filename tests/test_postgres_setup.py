import re
from pathlib import Path

ROOT = Path(__file__).parents[1] / 'setup/postgres'


def test_immutable_unaccent_is_schema_qualified():
    sql = (ROOT / 'schema.sql').read_text(encoding='utf-8')
    body = re.search(r"FUNCTION public\.immutable_unaccent\(text\).*?AS \$\$(.*?)\$\$", sql, re.S).group(1)
    assert "public.unaccent('public.unaccent'::regdictionary, $1)" in body
    assert not re.search(r"(?<![.\w])unaccent\(", body)


def test_install_and_tuned_conf_name_the_same_major():
    version = re.search(r'^PG_VERSION=(\d+)$', (ROOT / 'install.sh').read_text(encoding='utf-8'), re.M).group(1)
    conf = (ROOT / 'postgresql.conf.tuned').read_text(encoding='utf-8')
    assert f'/etc/postgresql/{version}/main/' in conf
    assert set(re.findall(r'/etc/postgresql/(\d+)/', conf)) == {version}
