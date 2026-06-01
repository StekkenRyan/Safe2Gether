# PostgreSQL — Setup und Streaming Replication

*Safe2Gether nutzt PostgreSQL 16 mit Streaming Replication.*
*Primary: Raspberry Pi. Replicas: Office Server, Hetzner VPS, NAS.*

---

## Übersicht

```
Pi (Primary)
  ├── Nimmt alle Reads und Writes an
  ├── Streamt WAL kontinuierlich zu allen Replicas
  └── Erreichbar für Replicas via Tailscale (100.x.x.x)

Office Server / Hetzner VPS / NAS (Replica / Hot Standby)
  ├── Nimmt Reads an (kann als Read-Replica genutzt werden)
  ├── Writes werden zum Primary weitergeleitet (oder abgelehnt)
  └── Kann bei Ausfall des Primary zum Primary promoted werden
```

---

## Part 1: Primary Setup (Raspberry Pi)

### 1.1 PostgreSQL 16 installieren (nativ)

```bash
sudo apt update
sudo apt install -y postgresql-16 postgresql-client-16
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

Prüfen:
```bash
sudo -u postgres psql -c "SELECT version();"
```

### 1.2 Setup-Script ausführen

```bash
cd /path/to/Safe2Gether-ServerCode
sudo bash scripts/setup-primary.sh
```

Das Script:
- Setzt `wal_level = replica` und `max_wal_senders = 5` in `postgresql.conf`
- Öffnet Port 5432 für das Tailscale-Netz (100.64.0.0/10) in `pg_hba.conf`
- Legt den Replikations-User `replicator` an
- Startet PostgreSQL neu

### 1.3 Datenbank und App-User anlegen

```bash
sudo -u postgres psql << 'EOF'
CREATE DATABASE safe2gether;
CREATE USER safe2gether WITH PASSWORD 'dein-sicheres-passwort';
GRANT ALL PRIVILEGES ON DATABASE safe2gether TO safe2gether;
\c safe2gether
GRANT USAGE ON SCHEMA public TO safe2gether;
GRANT CREATE ON SCHEMA public TO safe2gether;
EOF
```

### 1.4 Flask-Migrationen ausführen

```bash
# Im ServerCode-Verzeichnis:
make migrate
# oder: docker compose exec api flask db upgrade
```

### 1.5 Replikation verifizieren (nachdem Replicas eingerichtet sind)

```bash
sudo -u postgres psql -c "
SELECT application_name, client_addr, state, sent_lsn, replay_lsn,
       (sent_lsn - replay_lsn) AS lag_bytes
FROM pg_stat_replication;
"
```

Erwartete Ausgabe wenn ein Replica verbunden ist:
```
 application_name | client_addr  |   state   | sent_lsn | replay_lsn | lag_bytes
------------------+--------------+-----------+----------+------------+-----------
 office-standby   | 100.64.0.2   | streaming | 0/3000000| 0/3000000  |         0
```

---

## Part 2: Replica Setup (Office Server / Hetzner VPS / NAS)

### 2.1 PostgreSQL 16 installieren

Identisch mit Primary (Schritt 1.1).

### 2.2 Setup-Script ausführen

```bash
sudo bash scripts/setup-replica.sh
```

Das Script fragt nach:
- Tailscale-IP des Primary (z.B. `100.64.0.2`)
- Passwort des Replikations-Users (`replicator`)

Dann:
- Stoppt lokalen PostgreSQL
- Zieht vollständige Kopie vom Primary via `pg_basebackup`
- Erstellt `standby.signal` (Hot-Standby-Modus)
- Schreibt `primary_conninfo` in `postgresql.conf`
- Startet PostgreSQL als Replica

### 2.3 Replica verifizieren

```bash
# Auf dem Replica:
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"
# Erwartet: t (true = läuft als Replica)

# Auf dem Primary:
sudo -u postgres psql -c "SELECT application_name, state FROM pg_stat_replication;"
# Zeigt alle verbundenen Replicas
```

---

## Part 3: Backup-Strategie

### Manuelles Backup

```bash
make backup
# oder direkt:
bash scripts/backup.sh
```

Backups landen in `/var/backups/safe2gether/` (Standard) als `.dump`-Dateien.

### Automatisches Backup via Cron

```bash
sudo crontab -e
```

Folgende Zeile hinzufügen (täglich um 03:00 Uhr):
```
0 3 * * * /path/to/Safe2Gether-ServerCode/scripts/backup.sh >> /var/log/safe2gether-backup.log 2>&1
```

### Backup auf NAS speichern

```bash
# NAS mounten (Beispiel: NFS)
sudo mount -t nfs 100.64.0.4:/backups /mnt/nas-backups

# Dann backup.sh mit NAS-Pfad starten:
BACKUP_DIR=/mnt/nas-backups/safe2gether bash scripts/backup.sh
```

Oder dauerhaft in `/etc/fstab`:
```
100.64.0.4:/backups    /mnt/nas-backups    nfs    defaults    0    0
```

### Backup wiederherstellen

```bash
# Datenbank-Inhalt LÖSCHEN und aus Backup wiederherstellen:
sudo -u postgres pg_restore \
  --clean \
  --if-exists \
  --username=safe2gether \
  --dbname=safe2gether \
  /var/backups/safe2gether/safe2gether_2026-06-01_03-00-00.dump
```

**Achtung**: `--clean` löscht alle bestehenden Tabellen vor der Wiederherstellung.

---

## Part 4: PostgreSQL im Docker-Compose-Kontext

Die `docker-compose.yml` startet PostgreSQL als Container (für Entwicklung und Produktion
auf Nodes ohne native PostgreSQL-Installation). Die Replikation läuft dann innerhalb
von Docker-Netzwerken.

**Für Replikation mit Docker** müssen beide PostgreSQL-Instanzen über Tailscale
erreichbar sein. Dazu Port 5432 im Docker-Compose nach außen (auf Tailscale-Interface) binden:

```yaml
# docker-compose.yml — nur wenn Replikation über Docker läuft:
postgres:
  ports:
    - "100.64.0.1:5432:5432"   # Nur auf Tailscale-Interface binden!
```

**Empfehlung**: PostgreSQL für Produktion nativ installieren (nicht in Docker),
da die Replikations-Tools (`pg_basebackup`, `pg_ctl`) dann direkt verfügbar sind.
Docker wird für Flask und Redis genutzt.

---

## Referenz: Wichtige PostgreSQL-Kommandos

```bash
# Verbinden:
sudo -u postgres psql -d safe2gether

# Replikations-Status (auf Primary):
sudo -u postgres psql -c "SELECT * FROM pg_stat_replication;"

# Ist dieser Node eine Replica?
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"

# PostgreSQL neustarten:
sudo systemctl restart postgresql

# Logs:
sudo journalctl -u postgresql -f

# PostgreSQL-Konfigurationsdatei:
/etc/postgresql/16/main/postgresql.conf

# Authentifizierungsdatei:
/etc/postgresql/16/main/pg_hba.conf
```
