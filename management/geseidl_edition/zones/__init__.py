"""Registry zone overlay (runtime).

Fiecare zona = un modul cu `process_sections(sections, env, pool, manifest)`,
care muteaza lista de sectiuni in loc (poate adauga/modifica iteme).
"""

from . import status

REGISTRY = {
	"status": status.process_sections,
	# "spam": spam.process_sections,   # de migrat
	# "web":  web.process_sections,    # de migrat
}
