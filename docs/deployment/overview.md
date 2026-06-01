# Deployment — Übersicht

*Letzte Aktualisierung: 2026-06-01*

Diese Dokumentation beschreibt, wie Safe2Gether auf eigener Hardware deployt,
gewartet und bei Ausfall wiederhergestellt wird.

---

## Architekturüberblick (Kurzfassung)

Jeder Node läuft dieselbe Docker-Compose-Konfiguration:

```
[Flask API] ──► [Redis (lokal)]
     │
     └──► [PostgreSQL]
            Primary: Raspberry Pi (Home)
            Replicas: Office Server, Hetzner VPS, NAS
```

Alle Nodes sind über **Tailscale VPN** verbunden.
**Cloudflare Tunnel** macht jeden Node aus dem Internet erreichbar.

---

## Welches Dokument wann?

| Situation | Dokument |
|---|---|
| Neuen Node (Pi, VPS, NAS) aufsetzen | [new-node.md](new-node.md) |
| Tailscale VPN einrichten | [tailscale.md](tailscale.md) |
| PostgreSQL Primary + Replicas konfigurieren | [database.md](database.md) |
| Node ausgefallen, Failover, Backup/Restore | [operations.md](operations.md) |
| Technische Architektur verstehen | [../architecture.md](../architecture.md) |

---

## Schnellübersicht: Neuen Node aufsetzen

1. Docker + Tailscale installieren
2. Repo clonen: `git clone <repo>`
3. `.env` aus `.env.example` kopieren und befüllen
4. Cloudflare Tunnel anlegen und `CF_TUNNEL_TOKEN` in `.env` eintragen
5. `make prod` — startet alle Services
6. `make migrate` — DB-Schema anlegen (nur beim ersten Node)
7. Node in Cloudflare Load Balancer eintragen

Vollständige Anleitung: [new-node.md](new-node.md)

---

## Hardware-Rollen

| Node | Rolle | PostgreSQL | Priorität |
|---|---|---|---|
| Raspberry Pi (Home) | **Primary** | Primary | Hauptserver |
| Office Server | Standby | Replica | Übernimmt bei Pi-Ausfall |
| Hetzner VPS | Standby | Replica | Zusätzliche Redundanz |
| NAS (optional) | Standby + Backups | Replica | Letzte Absicherung |

---

## Deployment-Konzepte

**Stateless App-Layer**: Flask selbst speichert keinen State zwischen Requests.
JWT-Token sind auf allen Nodes gültig (gleicher `JWT_SECRET_KEY`).

**Node-lokales Redis**: Redis läuft auf jedem Node separat. State baut sich
nach einem Neustart in ~5 Minuten neu auf (durch eingehende Heartbeats).

**PostgreSQL Primary/Replica**: Writes gehen immer zum Primary. Bei Primary-Ausfall
muss manuell promoted werden (siehe [operations.md](operations.md)).

**Cloudflare als einziger Eingang**: Keine Ports werden nach außen geöffnet.
Cloudflare erkennt Ausfälle via Health Check und routet automatisch um.
