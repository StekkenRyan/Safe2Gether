# Safe2Gether

> Für alle, die allein unterwegs sind.  
> Sicherheit, die im Notfall für dich spricht.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
![Status: In Planung](https://img.shields.io/badge/Status-In%20Planung-yellow)

---

## Was ist Safe2Gether?

Safe2Gether ist eine Community-basierte Sicherheits-App — kein Solo-Tool, sondern ein Netz aus Menschen,
die füreinander da sind. Das „2gether" ist wörtlich gemeint.

Wer allein unterwegs ist — ob beim Wandern, auf dem Nachhauseweg oder im Funkloch — kann sicher sein:
Die App handelt, wenn du es nicht mehr kannst.

---

## Wie es funktioniert

**Panic Button**  
Sofortiger Hilferuf per Knopfdruck — In-App, Widget oder Hardware-Button.
Notfallkontakte werden alarmiert. Gleichzeitig: Nearby Alerting.

**Nearby Alerting**  
Anonyme Nutzer in der Nähe erhalten eine Push-Benachrichtigung.
Sie sehen Richtung und Entfernung — wer "Ich helfe" drückt, bekommt den genauen Standort.
Kein exakter Pin in der Datenbank, kein GPS-Dauerbetrieb.

**Dead Man's Switch** *(v2.0)*  
Der Server eskaliert beim *Ausbleiben* des Heartbeats — nicht beim Eingang eines Alarms.
Funkloch-Resistenz durch kombinierten Silent-Push + lokalen iOS-Timer.

---

## Architektur

```
[iOS App]
  │  REST · WebSocket · significantLocationChange → Geohash
  │
  ▼ (Cloudflare Tunnel)
[Flask + eventlet]  auf sora
  ├──> [Redis]    TTL State Machine · Geo-State aktiver Nutzer
  ├──> [DB]       Accounts · Alarm-History (30 Tage auto-delete)
  └──> [APNs]     Nearby Alert Push · Panic-Button-Benachrichtigung
```

| Komponente | Rolle |
|-----------|-------|
| iOS (Swift) | App, Widget, significantLocationChange, Silent Push |
| Flask + eventlet | REST API, WebSocket, Alarm-Logik |
| Redis | Heartbeat TTL, Geohash-State aktiver Sessions |
| APNs (direkt) | Push Notifications — kein Firebase |
| Cloudflare Tunnel | HTTPS-Endpunkt ohne offenen Port auf sora |

---

## Ausfallsicherheit

Server ist auf dem **Happy Path**, nicht auf dem Critical Path.

| Tier | Komponente | Ohne Server? |
|------|-----------|-------------|
| 1 | iOS-Gerät (lokaler Timer) | Ja |
| 2 | Flask + Redis auf sora | Nein |
| 3 | LoRa Button → direkter Alarm-Kanal *(v2.0)* | Ja |

---

## Roadmap

| Version | Inhalt | Plattform |
|---------|--------|-----------|
| **v1.0** | Panic Button · Notfallkontakte · Nearby Alerting | iOS · DACH |
| **v2.0** | Dead Man's Switch · Premium-Tier · LoRa Button | iOS |
| **v3.0** | Android | Android |

Details: [docs/roadmap.md](docs/roadmap.md)

---

## Dokumentation

| Dokument | Inhalt |
|----------|--------|
| [docs/product-vision.md](docs/product-vision.md) | Produktvision, Zielgruppe, 5-Jahres-Vision |
| [docs/features.md](docs/features.md) | Feature-Scope Free/Premium, Nearby Alerting, Reputation-System |
| [docs/architecture.md](docs/architecture.md) | Stack, Geo-Architektur, DSGVO, Auth |
| [docs/roadmap.md](docs/roadmap.md) | v1.0–v3.0 Phasen, Beta-Strategie, Launch-Kriterien |
| [docs/branding/branding.md](docs/branding/branding.md) | Farben, Font, Icon-Konzept |

---

## Selbst hosten

*Dokumentation folgt mit dem ersten Release.*

Anforderungen: Python 3.11+, Redis, Apple Developer Account (APNs), Cloudflare-Account (optional)

---

## Mitmachen

Contributions sind willkommen — bitte zuerst ein Issue öffnen, bevor du größere Änderungen einreichst.
Details zum Prozess: [CONTRIBUTING.md](CONTRIBUTING.md)

Externe Contributions benötigen ein **CLA (Contributor License Agreement)** —
ermöglicht späteres Dual-Licensing für einen Enterprise-Tier.

---

## Lizenz

[GNU Affero General Public License v3.0](LICENSE) —
kommerzielle SaaS-Forks müssen den Quellcode veröffentlichen. Eigener Betrieb zur Kostendeckung ist erlaubt.
