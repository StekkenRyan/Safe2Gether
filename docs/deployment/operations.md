# Operations Runbook

*Schritt-für-Schritt-Anleitungen für den laufenden Betrieb.*

---

## 1. Tägliche Checks

```bash
# Health-Status aller Services:
make health

# Laufende Container:
docker compose ps

# Replikations-Lag prüfen (auf Primary):
sudo -u postgres psql -c "
  SELECT application_name, state, (sent_lsn - replay_lsn) AS lag_bytes
  FROM pg_stat_replication;
"
```

---

## 2. Node fällt aus — Failover

### Szenario A: Temporärer Ausfall (Stunden)

Cloudflare erkennt den Ausfall automatisch (Health Check, ~30–60 Sek.) und leitet
Traffic auf den nächsten gesunden Node um. Kein manueller Eingriff nötig.

Wenn Primary (Pi) wieder online kommt:
```bash
# Auf dem Pi:
make prod   # Services starten
make health  # Prüfen ob alles ok

# Cloudflare routet automatisch wieder zum Pi zurück
# (sobald Health Check wieder "status": "ok" meldet)
```

### Szenario B: Dauerhafter Ausfall (Tage/Wochen)

**Phase 1: Replica zum Primary promoten**

Auf dem Standby-Node (z.B. Office Server), der Primary werden soll:

```bash
sudo bash scripts/promote-replica.sh
```

Das Script:
- Prüft ob dieser Node wirklich eine Replica ist
- Promoted PostgreSQL zu Primary (`pg_ctl promote`)
- Gibt genaue Folgeschritte aus

**Phase 2: DATABASE_URL auf allen anderen Nodes aktualisieren**

Auf jedem aktiven Node:
```bash
# .env bearbeiten:
nano .env

# DATABASE_URL auf neuen Primary zeigen lassen:
DATABASE_URL=postgresql://safe2gether:<pw>@<NEUER_PRIMARY_TAILSCALE_IP>:5432/safe2gether

# Flask neu starten:
docker compose restart api
```

**Phase 3: Cloudflare Load Balancer prüfen**

Wenn der ausgefallene Node (Pi) noch als "healthy" im Load Balancer eingetragen ist,
ihn temporär deaktivieren:
- Cloudflare Zero Trust → Traffic → Load Balancing → Origin Pool bearbeiten
- Ausgefallenen Node auf "Disabled" setzen

**Phase 4: Ausgefallenen Node wieder eingliedern (wenn er zurückkommt)**

Wenn der Pi wieder läuft, ihn als Replica des neuen Primary einrichten:
```bash
# Auf dem Pi:
sudo bash scripts/setup-replica.sh
# Primary-IP des neuen Primary eingeben (z.B. Office Server: 100.64.0.2)
```

Dann entscheiden: bleibt Office Server Primary, oder wird Pi wieder Primary?
- Pi als Primary: auf Office Server `promote-replica.sh` rückgängig machen und Pi-Setup wiederholen
- Office als Primary: Pi bleibt Replica, DATABASE_URL auf allen Nodes zeigt auf Office

---

## 3. Neuen Node hinzufügen

Egal ob zweiter Pi, NAS, Hetzner VPS, Mini-PC:

```bash
# Auf dem neuen Node:
# 1. Repo clonen, .env konfigurieren (siehe new-node.md)
# 2. Docker + Tailscale installieren
# 3. Als Replica einrichten:
sudo bash scripts/setup-replica.sh

# 4. Docker Services starten:
make prod

# 5. In Cloudflare Load Balancer eintragen:
#    Zero Trust → Traffic → Load Balancing → Origin Pool → Add Origin
#    URL: http://localhost:5000 (über den Tunnel)
```

---

## 4. Update deployen

```bash
git pull origin main
make prod-build   # Rebuild + Restart mit neuem Code
make migrate      # Falls neue DB-Migrationen vorhanden
```

Zero-Downtime-Update bei mehreren Nodes:
1. Node B updaten (Office Server)
2. Cloudflare kurz auf Node B zeigen lassen
3. Node A updaten (Pi)
4. Cloudflare wieder auf beide zeigen

---

## 5. Backup wiederherstellen

```bash
# Alle Services stoppen:
make down

# PostgreSQL direkt starten (ohne Flask):
docker compose up -d postgres

# Restore:
docker compose exec -T postgres pg_restore \
  --clean --if-exists \
  --username=safe2gether \
  --dbname=safe2gether \
  < /var/backups/safe2gether/safe2gether_2026-06-01_03-00-00.dump

# Alle Services wieder starten:
make prod
make health
```

---

## 6. Logs prüfen

```bash
# Flask API Logs (live):
make logs

# Alle Services:
make logs-all

# Nur Fehler:
docker compose logs api 2>&1 | grep -i error

# PostgreSQL Logs:
sudo journalctl -u postgresql -f

# Cloudflare Tunnel Logs:
docker compose logs cloudflared
```

---

## 7. TrueNAS SCALE — Docker Compose deployen

TrueNAS SCALE (Electric Eel+) unterstützt Docker Compose direkt.

**Option A: Über die TrueNAS Shell (empfohlen für volle Kontrolle)**

```bash
# SSH in TrueNAS:
ssh admin@<truenas-ip>

# Repo clonen in ein Dataset (persistent):
cd /mnt/pool/appdata
git clone https://github.com/paulczymek/Safe2Gether-ServerCode.git
cd Safe2Gether-ServerCode

# .env konfigurieren:
cp .env.example .env
nano .env

# Starten:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Option B: Über TrueNAS Apps (Custom App)**
1. Apps → Discover Apps → Custom App
2. Docker Compose YAML direkt eingeben
3. Volumes auf ein TrueNAS-Dataset mappen

**Persistente Volumes auf TrueNAS:**

In `.env` oder docker-compose.override.yml den Datenpfad anpassen:
```yaml
# docker-compose.override.yml (nur auf TrueNAS):
services:
  postgres:
    volumes:
      - /mnt/pool/appdata/safe2gether/postgres:/var/lib/postgresql/data
  redis:
    volumes:
      - /mnt/pool/appdata/safe2gether/redis:/data
```

---

## 8. Häufige Probleme

### Flask startet nicht / `DATABASE_URL` Fehler

```bash
docker compose logs api | tail -50
```

Häufige Ursache: `DATABASE_URL` in `.env` falsch. Primary erreichbar?
```bash
# Tailscale-Verbindung zum Primary testen:
tailscale ping 100.64.0.1

# PostgreSQL-Port erreichbar?
nc -zv 100.64.0.1 5432
```

### PostgreSQL-Replica ist weit hinter Primary zurück (hoher Lag)

```bash
# Auf Primary:
sudo -u postgres psql -c "SELECT application_name, (sent_lsn - replay_lsn) AS lag FROM pg_stat_replication;"
```

Wenn Lag > 100 MB: Netzwerk-Verbindung prüfen (`tailscale status`), ggf. Replica neu initialisieren:
```bash
sudo bash scripts/setup-replica.sh
```

### Cloudflare Tunnel trennt sich wiederholt

```bash
docker compose logs cloudflared
```

Häufig: `CF_TUNNEL_TOKEN` abgelaufen oder ungültig. Neuen Token in Cloudflare Zero Trust
generieren und in `.env` eintragen, dann `docker compose restart cloudflared`.

### "status: degraded" im Health Check

```bash
curl -s http://localhost:5000/api/v1/health | python3 -m json.tool
```

Prüfe `db_status` und `redis_status`:
- `db_status: error`: PostgreSQL nicht erreichbar → `docker compose ps postgres`
- `redis_status: error`: Redis nicht erreichbar → `docker compose ps redis`
- Beide down: `make down && make prod`
