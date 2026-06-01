# Tailscale VPN — Setup-Anleitung

Tailscale verbindet alle Safe2Gether-Nodes auf einem privaten WireGuard-Netzwerk
(100.64.0.0/10). PostgreSQL-Replikation und interne Service-Kommunikation laufen
ausschließlich über dieses Netz — keine Ports werden nach außen geöffnet.

---

## Warum Tailscale?

- **Kein Port-Forwarding**: Funktioniert hinter jedem NAT (Home-Router, Office-Firewall)
- **WireGuard-basiert**: Peer-to-peer Verbindungen, sehr geringe Latenz
- **Kostenlos**: Bis 100 Geräte auf dem kostenlosen Plan
- **Resilienz**: Wenn Tailscale-Coordination-Server kurz nicht erreichbar ist,
  bleiben bestehende WireGuard-Tunnel aktiv
- **Einfaches Onboarding**: Ein Befehl pro Node, dann Web-Login

---

## Installation

### Linux (Raspberry Pi OS / Debian / Ubuntu)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Der Browser öffnet (oder die Konsole zeigt einen Link) — mit dem Tailscale-Account einloggen.

Beim ersten Start ohne GUI:
```bash
sudo tailscale up --authkey=<AUTHKEY>
# Authkeys generieren unter: https://login.tailscale.com/admin/settings/keys
```

Tailscale-IP dieses Nodes abfragen:
```bash
tailscale ip -4
# z.B. 100.64.0.2
```

Status prüfen:
```bash
tailscale status
# Zeigt alle verbundenen Nodes
```

### Raspberry Pi OS (headless, kein Browser)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --advertise-tags=tag:server
# Link in der Konsole öffnen (oder Auth-Key nutzen, siehe oben)
```

### TrueNAS SCALE

**Option A: Über Apps (empfohlen)**
1. TrueNAS SCALE → Apps → Discover Apps
2. `Tailscale` suchen und installieren
3. Auth-Key eingeben (generieren unter https://login.tailscale.com/admin/settings/keys)
4. Nach Installation: IP über `Apps → Tailscale → Shell` oder das TrueNAS-Dashboard prüfen

**Option B: Über die TrueNAS Shell**
```bash
# TrueNAS SCALE nutzt Debian-basiertes Linux
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

### Hetzner VPS (Ubuntu)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh  # optional: SSH über Tailscale
```

---

## Netzwerk-Übersicht nach Setup

Nachdem alle Nodes verbunden sind:

```
tailscale status

# Beispiel-Output:
100.64.0.1   pi-primary          linux   active; relay "fra", tx 1.2GiB rx 800MiB
100.64.0.2   office-standby      linux   active; direct 192.168.x.x:41641
100.64.0.3   hetzner-vps-1       linux   active; direct x.x.x.x:41641
100.64.0.4   nas                 linux   active; relay "fra"
```

PostgreSQL-Replikation von Pi zu Office Server:
```
Pi (100.64.0.1) ──WireGuard──► Office (100.64.0.2):5432
```

---

## PostgreSQL-Port über Tailscale freigeben

PostgreSQL auf dem Primary (Pi) muss auf Verbindungen aus dem Tailscale-Netz hören.
Das `setup-primary.sh`-Script erledigt das automatisch — hier zur manuellen Referenz:

```bash
# In /etc/postgresql/16/main/pg_hba.conf:
host    replication     replicator     100.64.0.0/10     scram-sha-256
host    safe2gether     safe2gether    100.64.0.0/10     scram-sha-256

# In /etc/postgresql/16/main/postgresql.conf:
listen_addresses = '*'
```

Nach Änderungen: `sudo systemctl restart postgresql`

---

## Headscale — 100% Self-Hosted (optional, später)

Tailscale nutzt einen zentralen Coordination-Server für Key-Exchange.
Bestehende Verbindungen funktionieren auch wenn dieser kurz nicht erreichbar ist —
aber für vollständige Unabhängigkeit kann **Headscale** als selbst-gehosteter
Replacement genutzt werden.

Headscale ist ein Open-Source Drop-in für den Tailscale Coordination Server.

Migration später (ohne Architektur-Änderung):
```bash
sudo tailscale up --login-server=https://headscale.example.com
```

Das erfordert keine Änderungen an `.env`, docker-compose oder den Scripts —
nur der Tailscale-Daemon wird auf einen anderen Coordination-Server verwiesen.

Headscale-Docs: https://headscale.net/

---

## Troubleshooting

**Nodes sehen sich nicht:**
```bash
tailscale ping 100.64.0.2   # Direkte Verbindung zu einem anderen Node testen
```

**Relay statt direkter Verbindung (langsamer):**
- NAT-Traversal schlägt fehl, läuft über Tailscale-Relay
- Lösung: UDP-Port 41641 auf dem Router/Firewall öffnen (optional)
- Oder: `--advertise-exit-node` auf einem Node mit offener Firewall

**Tailscale-Service neu starten:**
```bash
sudo systemctl restart tailscaled
```

**Auth-Token abgelaufen:**
```bash
sudo tailscale up --force-reauth
```
