# Neuen Node aufsetzen

*Gilt für: Raspberry Pi, Hetzner VPS, Office Server, TrueNAS SCALE*

Diese Anleitung bringt einen frischen Node in ~20 Minuten produktionsbereit.

---

## Voraussetzungen

- Linux (Raspberry Pi OS / Debian 12, Ubuntu 22.04+, oder TrueNAS SCALE)
- Internetzugang
- SSH-Zugang zum Node
- Cloudflare-Account (kostenlos) mit Zero Trust aktiviert
- Tailscale-Account (kostenlos, [tailscale.com](https://tailscale.com))

---

## Schritt 1 — Docker installieren

```bash
# Debian/Ubuntu/Raspberry Pi OS:
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Docker Compose ist seit Docker 23+ eingebaut (docker compose)
docker compose version
```

Auf TrueNAS SCALE: Docker ist bereits installiert — weiter mit Schritt 2.

---

## Schritt 2 — Tailscale installieren

Tailscale verbindet alle Nodes auf einem privaten Netzwerk (100.x.x.x).
PostgreSQL-Replikation läuft über dieses Netzwerk.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Vollständige Tailscale-Anleitung: [tailscale.md](tailscale.md)

Nach dem Login:
```bash
tailscale ip -4
# Gibt die Tailscale-IP dieses Nodes aus, z.B. 100.64.0.3
# Diese IP wird für DATABASE_URL benötigt
```

---

## Schritt 3 — Repo clonen

```bash
git clone https://github.com/paulczymek/Safe2Gether-ServerCode.git
cd Safe2Gether-ServerCode
```

---

## Schritt 4 — Umgebungsvariablen konfigurieren

```bash
cp .env.example .env
nano .env   # oder: vim .env
```

Folgende Werte anpassen:

| Variable | Wert |
|---|---|
| `NODE_ID` | Eindeutiger Name, z.B. `pi-primary`, `office-standby`, `hetzner-vps-1` |
| `DATABASE_URL` | `postgresql://safe2gether:<PW>@<PRIMARY_TAILSCALE_IP>:5432/safe2gether` |
| `POSTGRES_PASSWORD` | Sicheres Passwort (wird nur lokal für den lokalen PG-Container genutzt) |
| `JWT_SECRET_KEY` | **Muss auf ALLEN Nodes identisch sein** |
| `SECRET_KEY` | Sicherer zufälliger String |
| `CF_TUNNEL_TOKEN` | Tunnel-Token von Cloudflare (Schritt 5) |

Für `DATABASE_URL` auf dem **Primary-Node selbst** (Raspberry Pi):
```
DATABASE_URL=postgresql://safe2gether:<PW>@postgres:5432/safe2gether
```
(zeigt auf den lokalen postgres-Container)

Für **alle anderen Nodes** (Replicas/Standbys):
```
DATABASE_URL=postgresql://safe2gether:<PW>@<PI_TAILSCALE_IP>:5432/safe2gether
```
(zeigt über Tailscale auf den Primary)

---

## Schritt 5 — Cloudflare Tunnel einrichten

### Einmalig (pro Node): Tunnel anlegen

1. Cloudflare Zero Trust Dashboard öffnen: https://one.dash.cloudflare.com
2. `Networks` → `Tunnels` → `Create a tunnel`
3. Connector: **Cloudflared** wählen
4. Name eingeben, z.B. `safe2gether-pi`
5. Token kopieren und in `.env` eintragen:
   ```
   CF_TUNNEL_TOKEN=eyJhIjoiY...
   ```
6. Public Hostname konfigurieren:
   - Subdomain: `api` (oder leer lassen für Apex)
   - Domain: `safe2gether.app` (deine Domain)
   - Service: `http://api:5000`

### Load Balancer für Failover (wenn mehrere Nodes aktiv):

1. `Traffic` → `Load Balancing` → `Create Load Balancer`
2. Hostname: `api.safe2gether.app`
3. Origin Pool A: Tunnel zum Pi
4. Origin Pool B: Tunnel zum Office Server
5. Health Check: `GET /api/v1/health`, Match: `"status":"ok"`
6. Failover-Reihenfolge: Pi → Office → Hetzner VPS

---

## Schritt 6 — Services starten

```bash
make prod
```

Prüfen ob alle Container laufen:
```bash
docker compose ps
# Erwartet: api (Up), redis (Up), postgres (Up), cloudflared (Up)
```

---

## Schritt 7 — Datenbank-Migration ausführen

**Nur beim allerersten Node (Primary):**

```bash
make migrate
```

Auf allen weiteren Nodes läuft die PostgreSQL-Replikation — kein `migrate` nötig.

---

## Schritt 8 — Health Check verifizieren

```bash
make health
# oder:
curl -s http://localhost:5000/api/v1/health | python3 -m json.tool
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

---

## Schritt 9 — PostgreSQL-Replikation einrichten (für Replica-Nodes)

Nur wenn dieser Node als Replica laufen soll (alle Nodes außer dem Primary):

```bash
# Auf dem PRIMARY (Pi) zuerst:
sudo bash scripts/setup-primary.sh

# Dann auf diesem Replica-Node:
sudo bash scripts/setup-replica.sh
```

Vollständige Anleitung: [database.md](database.md)

---

## Troubleshooting

**Container startet nicht:**
```bash
make logs
# oder spezifischer:
docker compose logs api
```

**DB-Verbindung schlägt fehl:**
- Tailscale-IP des Primary prüfen: `tailscale ip -4` (auf dem Primary)
- `DATABASE_URL` in `.env` korrekt? Richtige IP + Passwort?
- PostgreSQL auf dem Primary läuft? `docker compose ps postgres`
- Firewall auf dem Primary: Port 5432 im Tailscale-Netz erlaubt?

**Cloudflare Tunnel verbindet nicht:**
- `CF_TUNNEL_TOKEN` in `.env` vorhanden?
- `docker compose logs cloudflared` für Fehlermeldungen

**`make migrate` schlägt fehl:**
- DB erreichbar? `make health` prüfen
- Bereits migriert? `make migrate-history` zeigt bisherige Migrationen
