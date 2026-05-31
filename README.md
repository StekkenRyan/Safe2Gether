# Safe2Gether

> Ausfallsichere Personen-Sicherheits-App — auch ohne Mobilfunknetz.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

## Konzept

Safe2Gether basiert auf dem Prinzip des **Dead Man's Switch**: Der Server eskaliert beim *Ausbleiben* eines Signals — nicht beim Eingang eines Alarms. Funkloch-Resistenz ist kein nachträgliches Feature, sondern architekturelles Grundprinzip.

```
Kein Heartbeat empfangen  →  Alarm auslösen
Heartbeat empfangen       →  Nichts tun
```

## Architektur

```
[iOS App / LoRa Button]
       │
       ▼ (Cloudflare Tunnel)
[Flask + eventlet]
       ├──> [Redis]          Heartbeat State Machine (TTL-basiert)
       └──> [Twilio / SMTP]  Alarm-Ausgang (serverunabhängig)
```

### Drei-Säulen-Ausfallsicherheit

| Tier | Komponente | Funktioniert ohne Server? |
|------|-----------|--------------------------|
| 1 | iOS-Gerät (lokaler Timer) | Ja |
| 2 | Flask + Redis | Nein |
| 3 | LoRa Button → direktes SMS | Ja |

### Komponenten

- **Vorausschauende Funkloch-Pufferung** — App meldet `EXPECTED_OFFLINE + Timer` vor Funkloch-Eintritt; Redis TTL läuft entsprechend länger
- **LoRaWAN-Bridge** — STM32 + RFM95W Schlüsselanhänger als Panic-Button; Gateway schreibt direkt in SMS-Kanal
- **Server** — Flask + eventlet, Redis als State Machine, Twilio/SMTP für Alarme

## Status

🚧 In aktiver Entwicklung — noch kein stabiles Release.

Geplante Reihenfolge:
1. Backend State Machine (Flask + Redis)
2. iOS App mit Heartbeat
3. LoRa Button Hardware
4. Crowdsourcing-Funklochkartierung

## Selbst hosten

*Dokumentation folgt mit dem ersten Release.*

Anforderungen: Python 3.11+, Redis, Twilio-Account (oder SMTP), Cloudflare-Account (optional)

## Mitmachen

Contributions willkommen. Bitte zuerst ein Issue öffnen, bevor du größere Änderungen einreichst.

Bei externen Contributions wird ein **CLA (Contributor License Agreement)** benötigt, um ein späteres Dual-Licensing für Enterprise-Nutzung zu ermöglichen.

## Lizenz

[GNU Affero General Public License v3.0](LICENSE) — kommerzielle SaaS-Forks müssen den Quellcode veröffentlichen. Eigener Betrieb zur Kostendeckung ist erlaubt.
