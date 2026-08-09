# Yettel Srbija — Home Assistant integracija

Custom HACS integracija za praćenje Yettel (Srbija) mobilnih i fiksnih usluga.
Namenjeno **srpskim korisnicima** — sve na srpskom.

## Šta prati

Po svakom broju (jedan nalog = jedna instanca integracije):

- **Trenutno stanje** (RSD) — dugovanje na nalogu
- **Iznos računa** (RSD) — poslednji mesečni račun + atributi (mesec, status, rok)
- **Status računa** — `placen` / `nije_placen`
- **Rok plaćanja** — datum
- **Internet** — preostalo (GB) ili „Neograničeno"
- **Roming internet** (GB)
- **Zapadni Balkan internet** (GB)
- **Minuti** — broj ili „Neograničeno"
- **SMS poruke** — broj ili „Neograničeno"

## Više brojeva

Za svaki Yettel broj/nalog (npr. Markov, Marijin sa TV+optikom, treći broj) dodaj
**zasebnu instancu** integracije (Settings → Devices → Add Integration → Yettel Srbija).

## Prijava

1. **Korisničko ime** — broj telefona ili e-mail
2. **Lozinka** — Yettel nalog lozinka
3. **PIN** — onaj koji si kreirao u Yettel aplikaciji (za pristup listingu/podacima)

Pri prvoj prijavi može stići **SMS kod** (dvofaktorska verifikacija). Uneseš ga jednom —
uređaj se pamti (`rememberDevice`) i kod se ne traži ubuduće.

## Kako radi (tehnički)

```
1. POST /nalog/app/login-post           → session cookie
2. (opciono) POST /2fa/confirm-code-post → rememberDevice=1
3. GET  /nalog/api/auth (OAuth2)         → code → access cookie
4. POST /api/pwa/services/validate-pin   → tokenPin
5. GET  /api/index/home                  → podaci
```

- Dedikovana `aiohttp` sesija sa sopstvenim cookie jar-om (izolovano od HA core).
- Kolačići (uklj. „remember device") se čuvaju na disk → preživljavaju restart i
  preskaču 2FA pri ponovnom login-u.
- `DataUpdateCoordinator` osvežava na **4h**. Kad sesija istekne (`has_pin`), radi se
  automatski ponovni login.

## Status

`v0.1.0` — početna verzija. Testirano parsiranje na realnim API odgovorima.

### Otvoreno / TODO

- Logo i ikonice (`custom_components/yettel_srbija/icon.png` + `logo.png`, HA 2026.3+ standard)
- Senzori za **fiksne usluge** (TV, optički internet) — `ftth_info` scope već tražen u OAuth-u
- Detaljnija potrošnja (listing) i istorija računa kao grafikon na dashboard-u
- Testiranje sa prepaid nalozima i sa više brojeva pod istim nalogom

## Napomena

Nezvanična integracija. Nije povezana sa Yettel d.o.o. Koristi se na sopstvenu odgovornost.

## ☕ Podrži

Integracija je besplatna i nastaje u slobodno vreme. Ako ti je uštedela veče,
možeš da [platiš kafu](https://ko-fi.com/zonya2026).

[![Ko-fi](https://img.shields.io/badge/Ko--fi-F16061?style=for-the-badge&logo=ko-fi&logoColor=white)](https://ko-fi.com/zonya2026)
