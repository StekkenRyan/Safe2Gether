# Technische Architektur — Safe2Gether

*Definiert: 2026-05-31 — Architektur-Planungsrunde*

---

## Stack-Übersicht

```
[iOS App]  ──────────────────────────────────────────────────────────────────────
  │  Silent Push (APNs) ← Server (keep-alive DMS)
  │  significantLocationChange → Geohash-Update (nur bei Zellwechsel)
  │  WebSocket (Live-Updates: Alarm-Status, Premium Live-Tracking)
  │  REST (Heartbeat, Auth, Config)
  │
  ▼ (Cloudflare Tunnel)
[Flask + eventlet] auf sora
  ├──> [Redis]         Heartbeat TTL State Machine, aktive Sessions, Geo-Live-State
  ├──> [DB *]          Accounts, Alarm-History (30 Tage), verschlüsselte Standorte
  └──> [APNs direkt]   Nearby Alerting Push, Silent Push für DMS
```

`*` DB: TBD — muss Clustering unterstützen. Kandidaten: PostgreSQL+PostGIS, MongoDB.

---

## iOS — Dead Man's Switch (Hintergrund-Zuverlässigkeit)

**Strategie: Kombiniert**

| Kanal | Rolle |
|-------|-------|
| Silent Push (APNs) | Server weckt App periodisch auf — primärer Keep-Alive |
| Lokaler iOS-Timer | Fallback wenn kein Netz (Funkloch) — Gerät löst lokal aus |

```
Server sendet Silent Push alle N Minuten
       │
       ├── App antwortet → Timer resettet, kein Alarm
       └── Keine Antwort (Funkloch / Gerät aus)
              │
              └── Lokaler iOS-Timer läuft ab → lokale Eskalation
```

Hinweis: Silent Push ist von Apple-Infrastruktur abhängig und darf vom System throttled werden.
Lokaler Timer ist die echte Ausfallsicherung — Server ist auf dem Happy Path.

---

## Geo-Architektur — Nearby Alerting

**Mechanismus: Geohash-Raster (H3 oder S2)**

- Nutzer werden in Hex-Zellen eingeteilt — kein exakter Pin im Backend
- iOS nutzt `CLLocationManager.significantLocationChange`:
  - Wird nur getriggert wenn Gerät die Funkzelle wechselt (~500m–2km)
  - Kein GPS-Dauerbetrieb → minimaler Akkuverbrauch
  - Weckt App im Hintergrund auf → sendet neuen Geohash an Server

```
iOS erkennt Zellwechsel (significantLocationChange)
       │
       ▼
App sendet neuen Geohash (nicht exakten Pin) an Flask
       │
       ▼
Redis: SETEX user_<id>_geohash <TTL> "<H3-cell>"
       │
Im Alarmfall:
GEOSEARCH über alle aktiven Geohash-Einträge im Radius → Nearby-Nutzer-Liste
       │
       ▼
APNs Nearby Alert Push
```

**Datenschutz**: Geohash ist auf Zell-Granularität (TBD: H3 Level 7 ≈ 1.2 km²) — kein Hauseingang.

---

## Standort — DSGVO-Architektur

- Standorte werden **Ende-zu-Ende verschlüsselt** gespeichert — Server sieht nur Ciphertext
- Alarm-History (inkl. Standort-Snapshots): **30 Tage auto-delete** (TTL auf DB-Ebene)
- Aktive Sessions: nur Redis mit kurzer TTL — bei Session-Ende sofort gelöscht
- Nutzer kann jederzeit manuellen Lösch-Request stellen (DSGVO Art. 17)

---

## API-Design

**REST + WebSocket**

| Protokoll | Verwendung |
|-----------|-----------|
| REST (HTTPS) | Heartbeat POST, Auth, Konfiguration, Alarm auslösen |
| WebSocket | Live-Alarm-Status, Premium Live-Standort-Sharing (Gruppen) |

WebSocket-Verbindung nur während aktiver Session oder Premium-Gruppe — nicht dauerhaft offen.

---

## Authentifizierung

**Drei Wege — alle gleichwertig unterstützt:**

| Provider | Bemerkung |
|----------|-----------|
| Sign in with Apple | iOS-native, Privacy-Relay, DSGVO-freundlich |
| Sign in with Google | Für Nutzer ohne Apple ID / Android-Vorbereitung |
| E-Mail + Passwort | Plattformunabhängig, mit optionaler 2FA (TOTP) |

Telefonnummer-Verifikation (OTP) zusätzlich für Reputation-Basis-Score — unabhängig vom Auth-Weg.

---

## Push Notifications

**APNs direkt — kein Firebase**

- Kein Google als Datenmittler
- DSGVO-sauberer
- iOS first — FCM wird erst mit Android-Launch evaluiert
- Server hält APNs-Verbindung via HTTP/2 (APNs Provider API)

---

## Monitoring & Betrieb (sora)

| Schicht | Tool |
|---------|------|
| Prozess-Neustart | systemd Watchdog |
| HTTP-Verfügbarkeit | Cloudflare Health Check + Tunnel |
| Externer Uptime-Check | UptimeRobot oder Betterstack (kostenlos) — E-Mail/SMS bei Down |
| Fallback-Server | Hetzner Backup-VPS (~4 €/Monat) als Hot-Standby |

---

## Deployment (MVP → später)

| Phase | Ansatz |
|-------|--------|
| MVP | Manuell via SSH: `git pull && systemctl restart safe2gether` |
| Später | GitHub Actions → SSH Deploy oder Docker + CI/CD |

---

## Offene Entscheidungen (nächste Planungsebene)

- Konkrete Datenbank-Wahl (PostgreSQL+PostGIS vs. MongoDB) — nach erstem Feature-Prototypen
- H3 Level für Geohash (Granularität vs. Datenschutz-Trade-off)
- E2E-Verschlüsselungsschema für Standortdaten (welcher Key, wo wird entschlüsselt?)
- WebSocket-Library für Flask (Flask-SocketIO vs. raw asyncio)
- 2FA-Provider (TOTP selbst implementieren oder Drittanbieter?)
- Onboarding-Flow und Vertrauensaufbau (nächste Planungsebene: UX)
