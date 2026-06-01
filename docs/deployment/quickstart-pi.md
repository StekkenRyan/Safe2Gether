# Quickstart — Erster Deploy auf dem Raspberry Pi (Primary)

Diese Anleitung ist für den **ersten, einzigen Node** — den Pi als Primary.
Für weitere Nodes (Office Server, VPS) danach: [new-node.md](new-node.md)

---

## Voraussetzungen

- Raspberry Pi 4 (empfohlen: 4 GB RAM) mit Raspberry Pi OS Lite (Debian 12, 64-bit)
- SSH-Zugang zum Pi
- Domain in Cloudflare (kostenloser Free-Plan reicht)
- Cloudflare Zero Trust aktiviert (kostenlos): [one.dash.cloudflare.com](https://one.dash.cloudflare.com)

---

## Schritt 1 — Docker installieren

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker compose version   # muss ≥ 2.x ausgeben
```

---

## Schritt 2 — Repo clonen

```bash
git clone https://github.com/StekkenRyan/Safe2Gether.git
cd Safe2Gether
```

---

## Schritt 3 — Secrets generieren

```bash
# Drei zufällige Secrets erzeugen (einmalig — sicher aufbewahren!)
python3 -c "import secrets; print(secrets.token_hex(32))"   # → JWT_SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"   # → SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(16))"   # → POSTGRES_PASSWORD
```

---

## Schritt 4 — .env konfigurieren

```bash
cp .env.example .env
nano .env
```

Mindest-Konfiguration für den ersten Start:

```env
NODE_ID=pi-primary

# Die drei Secrets von Schritt 3:
JWT_SECRET_KEY=<generierter-wert>
SECRET_KEY=<generierter-wert>
POSTGRES_PASSWORD=<generierter-wert>

# Lokale DB (Pi ist Primary):
DATABASE_URL=postgresql://safe2gether:<POSTGRES_PASSWORD>@postgres:5432/safe2gether

# Redis lokal:
REDIS_URL=redis://redis:6379/0

# Cloudflare Tunnel (kommt in Schritt 5):
CF_TUNNEL_TOKEN=

# APNs — erst nötig wenn iOS-App angebunden wird:
APNS_KEY_ID=
APNS_TEAM_ID=
APNS_BUNDLE_ID=com.safe2gether.app
APNS_KEY_PATH=/run/secrets/apns_key.p8
APNS_SANDBOX=true
```

---

## Schritt 5 — Cloudflare Tunnel anlegen

1. [one.dash.cloudflare.com](https://one.dash.cloudflare.com) → **Networks → Tunnels → Create a tunnel**
2. Connector: **Cloudflared**
3. Name: `safe2gether-pi`
4. **Token kopieren** → in `.env` eintragen: `CF_TUNNEL_TOKEN=eyJ...`
5. Public Hostname:
   - Subdomain: `api`
   - Domain: `safe2gether.de` (deine Domain)
   - Service: `http://api:5000`
6. Speichern

---

## Schritt 6 — Starten

```bash
make prod-build     # Image bauen + alle Container starten
```

Status prüfen (alle 4 müssen `Up` zeigen):
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

---

## Schritt 7 — Datenbank initialisieren

```bash
make migrate
```

Erwartete Ausgabe:
```
Running upgrade -> 0001, initial users table
Running upgrade 0001 -> 0002, add reputation_actions table
Running upgrade 0002 -> 0003, add emergency_contacts, alarms, alarm_responders tables
Running upgrade 0003 -> 0004, security and DSGVO compliance improvements
```

---

## Schritt 8 — Health Check

```bash
make health
```

Erwartete Antwort:
```json
{
    "status": "ok",
    "node_id": "pi-primary",
    "version": "1.0.0",
    "db_status": "ok",
    "redis_status": "ok"
}
```

Wenn `status: "ok"` → der Pi ist live und über `https://api.safe2gether.de` erreichbar.

---

## Schritt 9 — Cron für DSGVO-Cleanup einrichten

```bash
crontab -e
```

Folgende Zeile hinzufügen (täglich 04:00 Uhr):
```
0 4 * * * cd /home/pi/Safe2Gether-ServerCode && docker compose exec -T api flask cleanup users && docker compose exec -T api flask cleanup alarms && docker compose exec -T api flask cleanup reputation >> /var/log/safe2gether-cleanup.log 2>&1
```

---

## Das war's.

Der Pi läuft als Primary. Nächste Schritte:

| Was | Wo |
|---|---|
| Zweiten Node (Office/VPS) hinzufügen | [new-node.md](new-node.md) |
| PostgreSQL-Replikation einrichten | [database.md](database.md) |
| Tailscale VPN (für Replikation nötig) | [tailscale.md](tailscale.md) |
| Was tun wenn der Pi ausfällt | [operations.md](operations.md) |

---

## Troubleshooting

**`make prod-build` hängt / schlägt fehl:**
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs api
```

**`make migrate` schlägt fehl mit "DB not reachable":**
- Postgres gestartet? `docker compose -f docker-compose.yml -f docker-compose.prod.yml ps postgres`
- `DATABASE_URL` in `.env` prüfen — `@postgres:5432` zeigt auf den lokalen Container

**Cloudflare Tunnel verbindet nicht:**
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs cloudflared
```
- `CF_TUNNEL_TOKEN` leer oder falsch in `.env`?
- Dashboard: Networks → Tunnels → Status des Tunnels prüfen

**Health zeigt `db_status: error`:**
- `POSTGRES_PASSWORD` stimmt nicht überein (in `DATABASE_URL` vs `POSTGRES_PASSWORD`)
- Container neu starten: `make prod-down && make prod-build`
