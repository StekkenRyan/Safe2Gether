# Safe2Gether — ServerCode

## Projektbeschreibung

Community-basierte Personen-Sicherheits-App für DACH. v1.0-Kern: **Panic Button + Nearby Alerting** —
anonyme Nutzer in der Nähe werden im Notfall alarmiert (gestufter Response-Flow). v2.0 fügt den
**Dead Man's Switch** hinzu: Server eskaliert beim *Ausbleiben* eines Signals, nicht beim Eingang eines Alarms.
Funkloch-Resistenz ist kein Add-on, sondern architekturelles Grundprinzip.

Produkt-Philosophie: **Sicherheit ist immer gratis. Premium ist Komfort und Community.**

## Drei-Säulen-Architektur

### 1. Community Nearby Alerting (v1.0)
- Anonyme Nutzer in der Nähe werden im Alarmfall per APNs benachrichtigt
- Geohash-Raster (H3/S2) + iOS `significantLocationChange` als Trigger — kein GPS-Dauerbetrieb
- Gestufter Response-Flow: erst grob (Richtung/Entfernung), nach "Ich helfe" → genauer Standort

### 2. Vorausschauende Funkloch-Pufferung (Software, v2.0 DMS)
- App meldet vor Funkloch-Eintritt: `EXPECTED_OFFLINE` + Timer
- Redis TTL als State Machine: `SETEX user_123_heartbeat 270 "WALKING"`
- Silent Push (APNs) + lokaler iOS-Timer kombiniert für Hintergrund-Zuverlässigkeit

### 3. LoRaWAN / 868 MHz Hardware-Bridge (v2.0)
- STM32 + RFM95W Schlüsselanhänger als Panic-Button
- Gateway schreibt direkt in Alarm-Kanal, **nicht** durch Flask-Server

## Server-Stack

```
[iOS App]
  │  REST (Auth, Panic Button, Config)
  │  WebSocket (Live-Alarm-Status, Premium Live-Tracking)
  │  significantLocationChange → Geohash → Server
  │
  ▼ (Cloudflare Tunnel)
[Flask + eventlet] auf sora
  ├──> [Redis]    TTL State Machine, Geo-State (Geohash aktiver Nutzer)
  ├──> [DB *]     Accounts, Alarm-History (30 Tage auto-delete)
  └──> [APNs]     Nearby Alert Push, Panic-Button-Benachrichtigung
```

`*` DB: TBD — Clustering muss möglich sein. Kandidaten: PostgreSQL+PostGIS, MongoDB.

Deployment: bestehender Server `sora` (Kosten: 0 €)

## Tiered Alarm Architecture

Server ist auf dem **Happy Path**, nicht auf dem Critical Path.

| Tier | Wer | Ohne Server? | Fängt auf |
|------|-----|-------------|-----------|
| 1 | iOS-Gerät (lokaler Timer) | Ja | Server offline |
| 2 | Flask/Redis auf sora | Nein | Geräteverlust |
| 3 | LoRa Button → direkter SMS-Ausgang | Ja | Beides offline |

## Design-Invarianten

Diese Entscheidungen sind bewusst getroffen und sollen nicht rückgängig gemacht werden ohne explizite
Neubewertung:

- **Stateless Heartbeat**: Jeder Ping rekonstruiert den vollständigen Zustand — kein kumulativer State
- **Lokale Notfallkontakte**: Verschlüsselt auf Gerät gespeichert; kein zentrales Adressbuch
- **Doppelte Alarm-Logik**: Unabhängig implementiert in Swift (Gerät) und Flask (Server)
- **Entkoppelter Outbound-Kanal**: APNs-Push nicht im Flask Request-Response-Cycle blockierend
- **Cloudflare Health Check + systemd Watchdog** auf sora; optional Hetzner Backup-VPS (~4 €/Monat)

## Verzeichnisstruktur

```
ServerCode/
├── .github/
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.md
│       └── feature_request.md
├── app/                        # (noch nicht angelegt — v1.0 Backend)
│   ├── __init__.py             # Flask app factory
│   ├── alarm.py                # Alarm-Auslösung und Eskalation
│   ├── geo.py                  # Geohash / Nearby Alerting
│   ├── routes.py               # API-Endpunkte (REST + WebSocket)
│   └── notifications.py        # APNs (entkoppelt, nicht blockierend)
├── docs/
│   ├── docs.md                 # Dokumentations-Index
│   ├── product-vision.md       # Produktvision & Marktpositionierung
│   ├── features.md             # Feature-Scope Free/Premium, Kernfunktionen
│   ├── architecture.md         # Technische Architektur (Stack, Geo, DSGVO)
│   ├── roadmap.md              # v1.0–v3.0 Roadmap mit Checklisten
│   └── branding/
│       ├── branding.md         # Marke, Farben, Font, Icon-Konzept
│       └── teaser.md           # Social Media Teaser-Posts
├── tests/
├── CONTRIBUTING.md
├── requirements.txt
└── CLAUDE.md
```

## Code-Qualität & Linting

**Nach jeder Änderung an Python-Dateien** (`app/`, `wsgi.py`) zwingend ausführen — bevor ein Commit vorgeschlagen wird:

```bash
ruff check app/ wsgi.py          # Lint-Check (E, F, W, I — identisch mit CI)
ruff check --fix app/ wsgi.py    # Auto-Fix wo möglich
```

Konfiguration: `pyproject.toml` → `line-length = 100`, `target-version = "py312"`, Regeln `E F W I`.

**Regel**: Kein Python-Code wird committed, wenn `ruff check` Fehler zurückgibt. Alle Verstöße werden im selben Arbeitsschritt behoben — nicht später.

## Lokale Checks & Git Hook

`make check` führt exakt dieselben Schritte aus wie die GitHub Actions CI (Lint → OpenAPI → Tests).
Das Venv wird bei erstem Aufruf automatisch in `.venv/` erstellt.

**Beim Start einer neuen Session / nach `git clone` sofort ausführen:**

```bash
make install-hooks   # installiert scripts/pre-push-hook → .git/hooks/pre-push
```

Der Hook blockiert jeden `git push` solange `make check` fehlschlägt.
Ist der Hook **nicht** aktiv, `make install-hooks` ohne Rückfrage ausführen.

### Tests & Checks direkt ausführen (Agent / VS Code)

Diese Befehle laufen lokal **ohne Docker** (sie nutzen das `.venv`). Der Agent führt sie
**selbstständig vor jedem Commit-Vorschlag** aus und wartet das Ergebnis ab — Code gilt erst als
fertig, wenn die Tests **grün durchgelaufen** sind, nicht schon wenn er „compiliert".

```bash
# Einmalig pro Maschine / nach git clone — legt .venv an und installiert alle Abhängigkeiten:
make install-dev

# Komplette Suite (wie CI):
make test                      # == .venv/bin/pytest tests/ -v
# oder direkt:
.venv/bin/pytest tests/ -v

# Nur Lint (E, F, W, I — line-length 100):
make lint                      # == ruff check app/ wsgi.py
ruff check --fix app/ wsgi.py  # Auto-Fix wo möglich

# Alles zusammen (Lint → OpenAPI → Tests):
make check
```

**Gezielt** nur sicherheitskritische / kürzlich geänderte Bereiche (läuft in Sekunden):

```bash
.venv/bin/pytest tests/test_ratelimit.py tests/test_timer_worker.py \
  tests/test_escalation_chain.py tests/test_auth.py tests/test_security.py -v
```

Hinweise für den Agenten:
- Suite **vollständig durchlaufen lassen** — die Auth-Tests sind durch `bcrypt` bewusst etwas
  langsamer (~0,2 s pro Hash), das ist **kein** Hänger. Nicht mit Strg-C abbrechen.
- `^C` / `KeyboardInterrupt` im Output ⇒ manueller Abbruch, **kein** Testfehler → erneut laufen
  lassen. `make: *** [test] Error 2` nach einem `^C` ist ebenfalls nur die Abbruch-Folge.
- `npx nicht gefunden` beim OpenAPI-Lint ⇒ Node fehlt (`brew install node`). `make check`
  überspringt den Schritt dann automatisch; die CI prüft ihn. **Kein lokaler Blocker.**
- Bei rotem Lint/Test: im selben Arbeitsschritt fixen, dann erneut prüfen — kein Commit-Vorschlag
  mit roter Suite.

Standard-Ablauf vor jedem Commit-Vorschlag: **`make lint` → `make test`** (oder der gezielte
Befehl oben) → erst dann committen.

## Dokumentation & Arbeitsweise

**Vor jeder Implementierung** relevante Docs lesen — nicht aus dem Gedächtnis arbeiten:

| Thema | Dokument |
|-------|----------|
| Marke, Sprache, Tonalität | [docs/branding/branding.md](docs/branding/branding.md) |
| Dokumentations-Übersicht | [docs/docs.md](docs/docs.md) |
| Produktvision & Zielgruppe | [docs/product-vision.md](docs/product-vision.md) |
| Feature-Scope (Free/Premium) | [docs/features.md](docs/features.md) |
| Technische Architektur | [docs/architecture.md](docs/architecture.md) |
| Roadmap & Build-Reihenfolge | [docs/roadmap.md](docs/roadmap.md) |

**Pflege-Regel**: Wenn Code-Änderungen ein bestehendes Dokument berühren (z.B. neue API-Endpunkte → API-Docs, neue Konfiguration → Setup-Guide), wird das Dokument **im selben Arbeitsschritt** aktualisiert — nicht nachträglich. Neue Docs werden in `docs.md` eingetragen.

## Open-Source-Setup

- **Lizenz**: AGPL v3 — verhindert kommerzielle SaaS-Forks ohne Rückgabe; eigener kommerzieller
  Betrieb (Kostendeckung) bleibt erlaubt
- **Primär-Plattform**: GitHub (Discovery, Contributors, Actions-CI)
- **Mirror**: Codeberg (EU-Hosting, automatischer Mirror)
- Bei späterem Enterprise-Tier: Dual-Licensing (AGPL v3 + kommerziell) + CLA für externe Contributions

## Entwicklungsreihenfolge

**Phase 0 — Fundament** *(aktuell)*
- API-Contract (OpenAPI), CONTRIBUTING.md, CI/CD-Grundgerüst, Docker Compose Dev-Umgebung

**Phase 1 — v1.0 (Backend + iOS parallel)**
- Backend: Auth, Nutzerprofile/Kontakte, Panic Button → APNs, Nearby Alerting (Geohash), Reputation
- iOS: Onboarding, Panic Button UI + Widget, Nearby Alerting (significantLocationChange), Push Handling

**Phase 2 — Beta**
- Privater Kreis (10–50 Personen) → TestFlight (halboffene Beta, 2-Wochen-Mindestlaufzeit)

**v2.0** — Dead Man's Switch, Premium-Tier (Life360), LoRa Button Hardware

**v3.0** — Android

## Offene Entscheidungen

- Konkrete DB-Wahl (PostgreSQL+PostGIS vs. MongoDB) — nach erstem Feature-Prototypen
- H3 Geohash-Level (Granularität vs. Datenschutz-Trade-off)
- E2E-Verschlüsselungsschema für Standortdaten (welcher Key, wo entschlüsselt?)
- Preispunkte für Premium-Tier (Monat / Jahr)
