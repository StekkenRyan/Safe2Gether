# Safe2Gether — ServerCode

## Projektbeschreibung

Ausfallsichere Personen-Sicherheits-App. Kernphilosophie: **Dead Man's Switch** — der Server eskaliert beim
*Ausbleiben* eines Signals, nicht beim Eingang eines Alarms. Funkloch-Resistenz ist kein Add-on, sondern
architekturelles Grundprinzip.

## Drei-Säulen-Architektur

### 1. Vorausschauende Funkloch-Pufferung (Software)
- App meldet vor Funkloch-Eintritt: `EXPECTED_OFFLINE` + Timer
- Bundesnetzagentur-Daten + Crowdsourcing für Kartierung (BNetzA-Daten zu grob → Crowdsourcing nötig)
- Redis TTL als State Machine: `SETEX user_123_heartbeat 270 "WALKING"`

### 2. LoRaWAN / 868 MHz Hardware-Bridge
- STM32 + RFM95W Schlüsselanhänger als Panic-Button
- TTN-Netz oder eigene Gateways (TTN-Dichte gering → eigener Gateway empfohlen)
- Gateway schreibt direkt in SMS-Kanal, **nicht** durch Flask-Server

### 3. Bluetooth-Mesh-Relay
- iOS Background Bluetooth stark eingeschränkt (seit iOS 13 kein passives Scanning)
- Vereinfacht zu: „Passant scannt QR-Code"-Flow oder weglassen

## Server-Stack

```
[iOS App / LoRa Button]
       │
       ▼ (Cloudflare Tunnel)
[Flask + eventlet]
       ├──> [Redis] (Heartbeat State Machine, TTL-basiert)
       └──> [Twilio / SMTP] (Alarm-Ausgang, serverunabhängig)
```

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
- **Entkoppelter Outbound-Kanal**: Twilio/SMTP nicht im Flask Request-Response-Cycle blockierend
- **Cloudflare Health Check + systemd Watchdog** auf sora; optional Hetzner Backup-VPS (~4 €/Monat)

## Geplante Verzeichnisstruktur

```
ServerCode/
├── app/
│   ├── __init__.py        # Flask app factory
│   ├── heartbeat.py       # Heartbeat State Machine (Redis TTL)
│   ├── alarm.py           # Alarm-Auslösung und Eskalation
│   ├── routes.py          # API-Endpunkte
│   └── notifications.py   # Twilio / SMTP (entkoppelt)
├── tests/
├── docs/
├── requirements.txt
└── CLAUDE.md
```

## Open-Source-Setup

- **Lizenz**: AGPL v3 — verhindert kommerzielle SaaS-Forks ohne Rückgabe; eigener kommerzieller
  Betrieb (Kostendeckung) bleibt erlaubt
- **Primär-Plattform**: GitHub (Discovery, Contributors, Actions-CI)
- **Mirror**: Codeberg (EU-Hosting, automatischer Mirror)
- Bei späterem Enterprise-Tier: Dual-Licensing (AGPL v3 + kommerziell) + CLA für externe Contributions

## Entwicklungsreihenfolge

1. Backend State Machine (Flask + Redis Heartbeat)
2. iOS App mit Heartbeat-Integration
3. LoRa Button Hardware
4. Rest (Crowdsourcing-Kartierung, Backup-VPS, etc.)

## Offene Entscheidungen

- Scope: Reines Portfolio-Projekt oder echtes Produkt?
- iOS vs. Android Priorität
