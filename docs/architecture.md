# Technische Architektur — Safe2Gether

*Letzte Aktualisierung: 2026-06-01*

---

## 1. Systemübersicht

```
┌─────────────────────────────────────────────────────────────────────┐
│                          iOS App (Client)                           │
│  significantLocationChange → Geohash-Update                         │
│  Panic Button, Heartbeat, Auth via REST                             │
│  Live-Alarm-Status via WebSocket                                    │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ HTTPS / WSS
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Cloudflare Tunnel                                 │
│  Öffentlicher Hostname: api.safe2gether.de                          │
│  Health-Check Failover: wechselt auf nächsten Node wenn Primary     │
│  degraded (db_status oder redis_status = "error")                   │
└────────┬────────────────────────────────┬────────────────────────────┘
         │                                │
         ▼                                ▼
┌─────────────────────┐        ┌─────────────────────┐
│  Node A             │        │  Node B             │     (Node C: Hetzner VPS)
│  Raspberry Pi       │        │  Office Server      │     (Node D: NAS, optional)
│  (Primary)          │        │  (Standby)          │
│                     │        │                     │
│  Flask + eventlet   │        │  Flask + eventlet   │
│  Redis (lokal)      │        │  Redis (lokal)      │
│  PostgreSQL Primary │        │  PostgreSQL Replica │
│  CF Tunnel Token A  │        │  CF Tunnel Token B  │
└────────┬────────────┘        └────────┬────────────┘
         │                              │
         │   PostgreSQL Streaming       │
         │   Replication via Tailscale  │
         └──────────────────────────────┘
                       │
              Tailscale VPN (100.x.x.x)
              Verbindet alle Nodes privat
              ohne Port-Forwarding
```

**Jeder Node ist vollständig unabhängig** — er kann wochen- oder monatelang der einzige
aktive Node sein. Fällt der Primary aus, übernimmt Cloudflare automatisch den nächsten
gesunden Node.

---

## 2. Komponenten im Detail

| Komponente | Wo | Rolle | Verlust-Auswirkung |
|---|---|---|---|
| **Flask + eventlet** | Jeder Node (Docker) | REST-API, WebSocket, Business-Logic | Node ist down; CF Failover auf anderen Node |
| **Redis** | Jeder Node (lokal, Docker) | Ephemerer State: Geohash-Cache, Heartbeat-TTL | Nearby Alerting degradiert bis Redis neu aufgebaut (~5 Min.) |
| **PostgreSQL Primary** | Node A (Pi) | Dauerhafter State: Accounts, Alarm-History | Replicas übernehmen Reads; Writes pausieren bis Promotion |
| **PostgreSQL Replica** | Node B, C, D | Hot-Standby, kann zum Primary promoted werden | Replikation endet; Primary unverändert |
| **Cloudflare Tunnel** | Jeder Node | Sicherer Ingress ohne offene Ports | Node nicht erreichbar ohne Tunnel |
| **Tailscale VPN** | Alle Nodes | Private Netzwerk-Verbindung zwischen Nodes | PostgreSQL-Replikation unterbrochen; Nodes laufen weiter |
| **APNs** | Apple-Infrastruktur | Push Notifications an iOS-Geräte | Keine Alerts — App zeigt es an |

---

## 3. Datenflüsse

### 3.1 Geohash-Heartbeat (Nutzer bewegt sich)

```
iOS erkennt Funkzellwechsel (significantLocationChange)
  │
  ▼ POST /api/v1/location  {geohash: "8fvc9"}
Flask empfängt Request
  │
  ▼ Redis: SETEX user_<id>_geo <TTL=600s> "8fvc9"
  │  (kein DB-Schreibzugriff — Redis reicht für ephemere Position)
  │
  ▼ HTTP 200 OK
```

**Redis TTL**: Nach 10 Minuten ohne Heartbeat gilt der Nutzer als offline.
Beim Failover auf einen anderen Node startet Redis leer — die ersten 5–10 Minuten
sind Aufwärmphase, danach kennt der neue Node alle aktiven Nutzer wieder.

---

### 3.2 Panic Button gedrückt

```
iOS: Panic Button gedrückt
  │
  ▼ POST /api/v1/alarm  {alarm_id: "<UUID>", geohash: "8fvc9", ...}
Flask:
  │
  ├─ PostgreSQL: INSERT INTO alarms (id, ...) ON CONFLICT DO NOTHING
  │  └─ Idempotenz: selbe alarm_id wird nie doppelt verarbeitet
  │
  ├─ Redis: GEORADIUS über alle user_*_geo Keys im Radius
  │  └─ Gibt Liste von Nearby-User-IDs zurück
  │
  └─ APNs: Batch-Push an alle Nearby-User
           Payload: {alarm_id, direction, distance}  (kein exakter Pin)
                                │
                                ▼
                     iOS Nearby-User: Alert erscheint
```

**Wichtig**: `alarm_id` kommt vom Client (UUID v4). Die DB-Constraint verhindert,
dass ein Retry auf einem anderen Node einen Duplikat-Alarm auslöst.

---

### 3.3 Nearby-User antwortet "Ich helfe"

```
Nearby-User tippt "Ich helfe" in der App
  │
  ▼ POST /api/v1/alarm/<alarm_id>/respond
Flask:
  │
  ├─ PostgreSQL: UPDATE alarms SET responder_id = <id>
  │
  └─ WebSocket: Schickt genauen Standort des Alarmierenden an Responder
               (erst jetzt → Datenschutz: Standort nur bei Hilfsbereitschaft)

Beide Geräte: WebSocket-Session für Live-Tracking
  │
  ▼ WebSocket bleibt offen bis Alarm aufgehoben oder Verbindung abbricht
```

---

### 3.4 Node-Ausfall und Cloudflare-Failover

```
Node A (Pi / Primary) fällt aus
  │
  ▼ Cloudflare Health Check: GET /api/v1/health → Timeout / Connection refused
  │  (Health Check Intervall: 30 Sek., nach 2 Fehlern → Failover)
  │
  ▼ Cloudflare leitet Traffic auf Node B (Office Server)
  │  └─ Dauer: ~30–60 Sekunden bis alle Clients umgeleitet sind
  │
  ▼ Node B startet mit leerem Redis
  │  └─ Heartbeats treffen ein → Redis füllt sich → Nearby Alerting aktiv (~5 Min.)
  │
  ▼ PostgreSQL auf Node B: Hot-Standby im Read-Only-Modus
  │  └─ Lesen: sofort möglich (Accounts, History)
  │  └─ Schreiben: erfordert Promotion
  │
  Wenn Primary dauerhaft ausgefallen:
  └─ sudo bash scripts/promote-replica.sh  auf Node B ausführen
     └─ Node B wird Primary, nimmt Writes an
     └─ DATABASE_URL auf allen Nodes auf Node B's Tailscale-IP aktualisieren
```

**Was während des Ausfalls nicht geht:**
- Neue Alarm-History-Einträge (DB-Writes gehen erst nach Promotion)
- Neue User-Registrierungen

**Was weiterhin geht:**
- Einloggen mit existierendem JWT (JWT ist stateless)
- Nearby Alerting (nach ~5 Min. Aufwärmphase)
- APNs-Benachrichtigungen

---

## 4. Redis — Rolle und Design

Redis ist **absichtlich ephemer und node-lokal**.

| Redis Key | TTL | Inhalt |
|---|---|---|
| `user_<id>_geo` | 600 s (10 Min.) | Geohash der letzten bekannten Position |
| `user_<id>_session` | = JWT Expiry | Aktive WebSocket-Session-Metadaten |
| `alarm_<id>_state` | 3600 s (1 h) | Laufender Alarm (Cache, DB ist primary) |

**Warum node-lokal (nicht geteilt):**
- Ein geteiltes Redis wäre ein neuer Single Point of Failure
- Der State ist ephemer und baut sich in Minuten neu auf
- Keine Komplexität durch Redis Cluster/Sentinel nötig
- Deployment eines neuen Nodes braucht keine Netzwerk-Koordination

---

## 5. PostgreSQL — Replikations-Modell

```
Pi (Primary)  ──── Streaming Replication ────► Office Server (Replica)
                                          ────► Hetzner VPS (Replica)
                                          ────► NAS (Replica, optional)
```

- **Streaming Replication**: Walstream wird kontinuierlich vom Primary zu allen Replicas übertragen
- **Hot Standby**: Replicas nehmen Lese-Anfragen an (können als Read-Replicas genutzt werden)
- **Failover**: Manuell via `scripts/promote-replica.sh` — kein automatisches Patroni/pgpool in Phase 0
- **Verbindung**: Über Tailscale VPN (100.64.0.0/10) — kein offener Port nach außen nötig

Replikations-Status prüfen (auf Primary):
```sql
SELECT application_name, state, sent_lsn, replay_lsn,
       (sent_lsn - replay_lsn) AS replication_lag
FROM pg_stat_replication;
```

---

## 6. Cloudflare — Tunnel und Failover

```
Cloudflare Zero Trust Dashboard
  └── Load Balancer: api.safe2gether.de
        ├── Origin Pool A: Tunnel zu Pi (Node A)
        │     Health Check: GET /api/v1/health → { "status": "ok" }
        └── Origin Pool B: Tunnel zu Office Server (Node B)
              Health Check: GET /api/v1/health → { "status": "ok" }
```

**Health Check Response-Felder:**
- `status: "ok"` — alle Abhängigkeiten gesund → Node nimmt Traffic
- `status: "degraded"` — DB oder Redis nicht erreichbar → Cloudflare failover

**Wichtig**: Jeder Node hat seinen eigenen `CF_TUNNEL_TOKEN` in der `.env`.
Tokens niemals committen — `.env` ist in `.gitignore`.

Cloudflare Tunnel Setup: [docs/deployment/new-node.md](deployment/new-node.md)

---

## 7. Tiered Alarm Architecture

Der Server ist auf dem **Happy Path**, nicht auf dem Critical Path.

| Tier | Wer | Ohne Server? | Fängt auf |
|---|---|---|---|
| **1** | iOS-Gerät (lokaler Timer) | Ja | Server komplett offline |
| **2** | Flask/Redis auf aktivem Node | Nein | Geräteverlust, kein Netz |
| **3** | LoRa Button → direkter SMS-Ausgang (v2.0) | Ja | Tier 1 + 2 offline |

Selbst wenn der Server wochenlang ausfällt: Tier 1 (iOS lokaler Timer +
lokale Notfallkontakte) greift immer. Der Server fügt **Community Nearby Alerting**
hinzu — wichtig, aber nicht lebenskritisch allein.

---

## 8. API-Design

| Protokoll | Verwendung |
|---|---|
| **REST (HTTPS)** | Auth, Heartbeat, Konfiguration, Alarm auslösen |
| **WebSocket** | Live-Alarm-Status, Premium Live-Standort-Sharing |

WebSocket ist **nicht** permanent offen — nur während aktivem Alarm oder Premium-Session.

Vollständige API-Spec: [docs/api/openapi.yaml](api/openapi.yaml)

---

## 9. Authentifizierung

Drei gleichwertige Auth-Wege:

| Provider | Bemerkung |
|---|---|
| Sign in with Apple | iOS-native, Privacy-Relay, DSGVO-freundlich |
| Sign in with Google | Für Nutzer ohne Apple ID / Android-Vorbereitung |
| E-Mail + Passwort | Plattformunabhängig, optionale 2FA (TOTP) |

Telefonnummer-Verifikation (OTP) zusätzlich für Reputation-Score.

**JWT ist stateless** — `JWT_SECRET_KEY` muss auf allen Nodes identisch sein.
Ein Token von Node A ist auf Node B sofort gültig. Kein Session-Store nötig.

---

## 10. Push Notifications

**APNs direkt — kein Firebase**

- Kein Google als Datenmittler
- DSGVO-sauber
- iOS-first (FCM wird erst mit Android-Launch evaluiert)
- APNs Provider API via HTTP/2 (`httpx[http2]` bereits in requirements.txt)

Push-Typen:

| Typ | Trigger | Payload |
|---|---|---|
| Nearby Alert | Panic Button in der Nähe | Richtung + Entfernung (kein Pin) |
| Responder Update | "Ich helfe" von Nearby-User | Alarm-Status |
| Silent Push (v2.0) | Dead Man's Switch Keep-Alive | Leer (weckt App auf) |

---

## 11. Geo-Architektur — Nearby Alerting

```
iOS: significantLocationChange (Funkzellwechsel, ~500m–2km)
  │
  ▼ Geohash berechnen (H3, Level TBD — ~1.2 km² pro Zelle)
  │
  ▼ POST /api/v1/location  {geohash: "8fvc9..."}
  │
  ▼ Redis: SETEX user_<id>_geo 600 "8fvc9..."
  │
Im Alarmfall:
  Redis GEORADIUS (oder H3 Nachbar-Zellen) → Nearby-User-IDs
  │
  ▼ APNs Batch-Push

Datenschutz: Server kennt nur Geohash-Zelle, keinen exakten Pin.
H3 Level 7 ≈ 1.2 km² — kein Hauseingang sichtbar.
```

---

## 12. DSGVO-Architektur

| Datenkategorie | Speicherort | Retention |
|---|---|---|
| Standort (Geohash) | Redis (ephemer, lokal) | TTL 10 Min., dann gelöscht |
| Alarm-Standort-Snapshots | PostgreSQL, Ende-zu-Ende verschlüsselt | 30 Tage auto-delete |
| Notfallkontakte | Nur auf iOS-Gerät (lokal, verschlüsselt) | Kein Server-Speicher |
| Account-Daten | PostgreSQL | Bis Nutzer löscht (DSGVO Art. 17) |
| Active Sessions | Redis (TTL = JWT Expiry) | Sofort bei Logout gelöscht |

Vollständige DSGVO-Dokumentation: [docs/dsgvo.md](dsgvo.md)

---

## 13. Monitoring & Betrieb

| Schicht | Tool | Zweck |
|---|---|---|
| Prozess-Neustart | Docker `restart: always` | Flask/Redis/Postgres crashen → automatischer Neustart |
| HTTP-Verfügbarkeit | Cloudflare Health Check | Failover bei Node-Ausfall |
| Externer Uptime-Check | UptimeRobot / Betterstack (kostenlos) | E-Mail/SMS bei Ausfall |
| Replikations-Lag | `pg_stat_replication` (manuell) | Replikation gesund? |
| Logs | `make logs` / `docker-compose logs -f` | Fehleranalyse |

---

## Deployment-Guides

| Thema | Dokument |
|---|---|
| Erster Node aufsetzen | [docs/deployment/new-node.md](deployment/new-node.md) |
| Tailscale VPN einrichten | [docs/deployment/tailscale.md](deployment/tailscale.md) |
| PostgreSQL Replikation | [docs/deployment/database.md](deployment/database.md) |
| Failover, Backup, Restore | [docs/deployment/operations.md](deployment/operations.md) |
