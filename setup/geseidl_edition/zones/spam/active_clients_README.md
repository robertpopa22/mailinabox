# Active clients — candidat izolat

`active_clients.lua` nu se înregistrează singur și nu este conectat la `rspamd.sh`.
`decision(context, lookup, now)` este pură. Hash map-ul unic conține `__schema=1`,
`__observed=<epoch>`, `__expires=<epoch>`, `senderhex:<hex lowercase bytes ASCII adresă>=1` și
`domain:<domeniu local>=1`. Producerul trebuie să publice atomic întreaga hartă și
să păstreze eligibilitatea până la retragerea ultimei relații active. TTL maxim:
3600 secunde; expirarea exactă este deja invalidă. Nu se elimină plus-taguri.

`register(cfg, options)` cere `options.lookup` și un adaptor explicit
`options.context(task)` verificat pe versiunea Rspamd instalată. Contextul conține
`from` (lista adreselor RFC5322), `header_from_count`, `smtp_from`, `recipients`
(SMTP), booleene explicite `authenticated/local_outbound/bulk/list/bounce`,
`auto_submitted` (nil sau valoare), `symbols` (nume -> scor), `total`,
`reject_threshold`, `pre_result` (false numai dacă verificabil absent).
Nu deduce lipsa semnalelor din API-uri indisponibile. `security_symbols` poate
înlocui lista exactă; veto-urile conservative după nume rămân.

Implicit shadow: simbol informativ cu scor zero, fără ajustare. Numai
`mode='enforce'` aplică `adjust_result('BAYES_SPAM',1.0)`, păstrând simbolul.
Nicio acțiune este forțată/dezactivată; scorul total propus se schimbă numai prin
cap-ul Bayes. Respingerile/pre-result, semnalele security și autentificarea
insuficientă sunt veto. Nu există învățare, restart, transport ori deployment.

Prioritatea candidatului este 20 și sunt cerute dependențe pentru executare înainte
de GREYLIST_SAVE/SPAM_REPORT_HEADER când API-ul există. Ordinea efectivă, adaptorul
task, pragul reject, reevaluarea acțiunii și încărcarea atomică a hărții trebuie
validate într-o clonă Rspamd 4.1.5 înainte de integrare. Testele pure nu dovedesc
comportamentul pipeline-ului real.

`context_from_task(task)` folosește API-urile task pentru envelope, antete și
rezultatele scanării; nu citește body și nu acceptă DMARC/simboluri din antetele
mesajului. Erorile adaptorului opresc eligibilitatea, cu mesaj sanitizat.
`install(cfg, options)` înregistrează explicit hash map-ul prin `add_map` și
folosește `map:get_key`. Cere `map_path`; `mode` absent înseamnă shadow, iar orice
valoare diferită de shadow/enforce este eroare. Instalarea nu se execută automat.

Testele sintetice pure, hex și mock au trecut pe Rspamd 4.1.5. Ele nu validează
pipeline-ul real: instanța izolată complet configurată rămâne obligatorie.
Cheia `senderhex` împiedică interpretarea `#` și altor caractere din local-part
ca sintaxă de map; această codificare este acoperită de testele sintetice.
Test sintetic: `lua active_clients_test.lua` din acest director (fără Rspamd).
