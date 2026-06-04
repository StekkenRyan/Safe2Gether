# DSGVO-Entwurf — Safe2Gether

*Stand: 2026-06-04 — Interner Arbeitsentwurf, kein rechtsgültiges Dokument*

Dieser Entwurf dokumentiert alle datenschutzrelevanten Entscheidungen für v1.0.
Er ist die Grundlage für die öffentliche Datenschutzerklärung, die **vor dem Launch live sein muss**.

---

## Verantwortlicher

| Feld | Wert |
|------|------|
| Name | Paul Czymek |
| Adresse | *wird nachgetragen* |
| E-Mail | kontakt@safe2gether.de |
| Vertreter EU | entfällt (DE-ansässig) |

---

## Datenarten & Verarbeitungszwecke

### 1. Account-Daten

| Datum | Pflicht? | Zweck | Speicherort |
|-------|----------|-------|-------------|
| E-Mail-Adresse | Ja (E-Mail-Auth) / Nein (Apple/Google) | Auth, Kontakt bei sicherheitsrelevantem Vorfall | Datenbank |
| Auth-Provider-ID (Apple/Google Sub) | Ja | Verknüpfung des externen Auth-Accounts | Datenbank |
| Passwort-Hash (bcrypt) | Nur bei E-Mail-Auth | Login | Datenbank |
| APNs Device Token | Ja | Push-Benachrichtigungen (Alarme, DMS) | Datenbank |
| Erstelldatum / letzter Login | Ja | Sicherheit, Inaktivitäts-Bereinigung | Datenbank |

**Rechtsgrundlage**: Art. 6 Abs. 1 lit. b DSGVO (Vertragserfüllung)

---

### 2. Telefonnummer (optional)

| Datum | Pflicht? | Zweck | Speicherort |
|-------|----------|-------|-------------|
| Telefonnummer | Nein | OTP-Verifikation → Reputation-Score | Datenbank |
| Verifikationsstatus | Ja (nach Verifikation) | Reputation-Nachweis | Datenbank |

**Rechtsgrundlage**: Art. 6 Abs. 1 lit. a DSGVO (Einwilligung — jederzeit mit Wirkung für die Zukunft widerrufbar)

---

### 3. Standortdaten (Geohash / Nearby Alerting)

| Datum | Genauigkeit | Zweck | Speicherort | TTL |
|-------|-------------|-------|-------------|-----|
| H3-Geohash (Level 7) | ≈1,2 km² — kein exakter Pin | Nearby Alerting — Nutzer in der Nähe im Notfall alarmieren | Redis | ~7 Tage Inaktivität |
| Geohash-Snapshot im Alarm | ≈1,2 km² | Alarm-Kontext, Hilfe koordinieren | Datenbank (verschlüsselt) | 30 Tage |

**Privacy-by-Design**:
- iOS nutzt `significantLocationChange` (Funkzellwechsel, ~500 m–2 km) — kein GPS-Dauerbetrieb
- Nur die Hex-Zelle wird gespeichert, niemals Koordinaten
- Exakter Standort wird nur nach "Ich helfe"-Bestätigung temporär an den Responder übermittelt und **nicht persistent gespeichert**

**Rechtsgrundlage**: Art. 6 Abs. 1 lit. b DSGVO (Vertragserfüllung — Kernfunktion der App)

---

### 4. Alarm-Historie

| Datum | Zweck | Speicherort | Löschfrist |
|-------|-------|-------------|-----------|
| Alarm-ID, Zeitstempel, Auslöser | Protokollierung, Missbrauchsschutz | Datenbank | **30 Tage automatisch** |
| Geohash-Snapshot (verschlüsselt) | Kontext für Responder | Datenbank (E2E-verschlüsselt) | **30 Tage automatisch** |
| Responder-Liste (UUIDs) | Dokumentation der Hilfeleistung | Datenbank | **30 Tage automatisch** |
| Alarm-Status (active/resolved/false_alarm) | Missbrauchsschutz, Reputation | Datenbank | **30 Tage automatisch** |

**Implementierung**: `auto_delete_at`-Feld + DB-Level-Job oder TTL-Index (MongoDB) / scheduled DELETE (PostgreSQL)

---

### 5. Reputation-Daten

| Datum | Zweck | Speicherort | Löschfrist |
|-------|-------|-------------|-----------|
| Reputation-Score (Zahl) | Community-Vertrauen, Feature-Zugang | Datenbank | Mit Account-Löschung |
| Aktions-Log (Typ, Delta, Zeitstempel) | Nachvollziehbarkeit, Missbrauchsschutz | Datenbank | 30 Tage rollierend |

**Rechtsgrundlage**: Art. 6 Abs. 1 lit. f DSGVO (Berechtigtes Interesse: Gewährleistung der Plattformsicherheit und Missbrauchsprävention)

---

### 6. Notfallkontakte

**Gespeichert ausschließlich auf dem Gerät (iOS Keychain / verschlüsselt).**
Kein zentrales Adressbuch auf dem Server. Bei Alarmauslösung werden Kontakt-Metadaten (Typ + anonymisierter Bezeichner) für die Push-Zustellung temporär übermittelt.

**Rechtsgrundlage**: Art. 6 Abs. 1 lit. b DSGVO (Vertragserfüllung)
---

### 7. Session-Daten (Redis)

| Datum | Zweck | TTL |
|-------|-------|-----|
| Heartbeat-Status | DMS-Grundlage, Online-Status | ~270 s (auto-expire) |
| Refresh-Token-Hash | Session-Verwaltung | 30 Tage |

Redis-Daten sind flüchtig — kein Backup, kein persistentes Log.

---

## Drittanbieter & Datenempfänger

| Empfänger | Zweck | Datenweitergabe | Rechtsgrundlage |
|-----------|-------|----------------|----------------|
| **Hetzner Online GmbH** (DE) | Storage Box: tägliche Off-Site-Backups (DB-Dumps, Website-Dateien) via rsync — **kein Hosting** | Datenbank-Dumps und Website-Dateien at rest auf der Storage Box | Art. 6 Abs. 1 lit. f (Berechtigtes Interesse: Verfügbarkeit) |
| **Apple APNs** | Push-Benachrichtigungen (Alarme, DMS) | APNs Device Token | Art. 6 Abs. 1 lit. b |
| **Apple Sign In** | Authentifizierung | Sub (anonyme ID) + optional E-Mail via Privacy Relay | Art. 6 Abs. 1 lit. b |
| **Google Sign In** | Authentifizierung | Sub + E-Mail | Art. 6 Abs. 1 lit. b |
| **Cloudflare** (US, EU-Rechenzentrum) | CDN / Tunnel / DDoS-Schutz | IP-Adressen, HTTP-Metadaten | Art. 6 Abs. 1 lit. f (Sicherheit) |
| **Brevo / Sendinblue SAS** (FR) | Transaktionale E-Mails (Auth-Links, Sicherheitshinweise) | E-Mail-Adresse, Betreff, Inhalt der Transaktions-E-Mail | Art. 6 Abs. 1 lit. b (Vertragserfüllung) |
| **Strato AG** (DE) | E-Mail-Postfach `kontakt@safe2gether.de` | Inhalte + Metadaten eingehender E-Mails | Art. 6 Abs. 1 lit. f (Berechtigtes Interesse: Erreichbarkeit) |
| **SMS-Provider** (TBD) | OTP-Versand für Telefonnummer-Verifikation | Telefonnummer | Art. 6 Abs. 1 lit. a (Einwilligung) |
| **Firebase/FCM** | **Nicht verwendet** — APNs direkt | — | — |

**Kein Tracking, keine Werbung, keine Datenweitergabe an Dritte zu Marketingzwecken.**

> **Hinweis Hetzner Storage Box**: Der Pi rsynct täglich PostgreSQL-Dumps und Website-Dateien
> auf eine Hetzner Storage Box (DE-Rechenzentrum). Hetzner agiert als Auftragsverarbeiter (AVV
> abzuschließen unter *Hetzner Robot → Einstellungen → Auftragsverarbeitungsvertrag*).

---

## Betroffenenrechte — Umsetzung

| Recht | DSGVO | Umsetzung |
|-------|-------|-----------|
| Auskunft | Art. 15 | `GET /api/v1/users/me` + Alarm-Export (v1.0 Placeholder) |
| Berichtigung | Art. 16 | `PATCH /api/v1/users/me` |
| Löschung | Art. 17 | `DELETE /api/v1/users/me` → Soft-Delete, permanent nach 30 Tagen |
| Einschränkung | Art. 18 | Manuell via Support-E-Mail (v1.0) |
| Datenportabilität | Art. 20 | JSON-Export (v1.0 Placeholder) |
| Widerspruch | Art. 21 | Opt-out Nearby Alerting in App-Einstellungen |
| Beschwerde | Art. 77 | Zuständige Aufsichtsbehörde: LfDI Baden-Württemberg (vorläufig) |

**Antwortfrist**: 30 Tage (DSGVO-Pflicht). Kontakt: *TBD (kontakt@safe2gether.de)*

---

## Technische & organisatorische Maßnahmen (TOMs)

| Maßnahme | Umsetzung |
|----------|-----------|
| Verschlüsselung in Transit | HTTPS (TLS 1.3) via Cloudflare Tunnel |
| Verschlüsselung at Rest | Standort-Snapshots (Datenbank) E2E-verschlüsselt; Passwörter bcrypt-gehasht |
| Zugriffskontrolle | JWT-Auth für alle API-Endpunkte; Redis nur intern erreichbar |
| Datensparsamkeit | Geohash statt Koordinaten; Notfallkontakte lokal auf Gerät |
| Löschkonzept | 30-Tage-Auto-Delete für Alarm-Historie; Redis TTL für Session/Geo-State |
| Datensicherung | Tägliche Off-Site-Sicherung via rsync auf Hetzner Storage Box (DE); lokale DB-Dumps 30 Tage via `scripts/backup.sh` |
| E-Mail-Versand | Transaktionale E-Mails ausschließlich via Brevo (SMTP-Relay); kein Marketing-Tracking |
| Keine Drittland-Übertragung | Server auf `sora` (DE); Cloudflare EU-Rechenzentrum konfigurieren; Hetzner DE; Brevo FR (EU) |
| Logging | Kein personenbezogenes Logging in Produktions-Logs (IPs maskieren) |

---

## Offene Entscheidungen vor Launch ⚠️

Diese Punkte **müssen** vor dem App-Store-Launch geklärt und implementiert sein:

- [x] **Verantwortlichen** festlegen (Paul Czymek) und in Datenschutzerklärung eintragen
- [x] **E-Mail-Provider** festgelegt: Brevo (Versand via SMTP-Relay) + Strato (Postfach `kontakt@safe2gether.de`)
- [ ] **Brevo AVV** abschließen (im Brevo Dashboard unter *Einstellungen → Rechtliches → DPA*)
- [ ] **Strato AVV** abschließen (Strato bietet Standard-AVV für Hosting-/Mailkunden)
- [ ] **Hetzner AVV** abschließen (Hetzner Robot → *Einstellungen → Auftragsverarbeitungsvertrag*)
- [ ] **SMS-Provider** wählen (Twilio, Vonage, etc.) → Auftragsverarbeitungsvertrag (AVV) abschließen
- [ ] **Cloudflare AVV** abschließen (kostenlos im Dashboard verfügbar)
- [ ] **Apple / Google** AVV prüfen (i.d.R. in Developer Agreement enthalten)
- [ ] **E2E-Verschlüsselungsschema** finalisieren: welcher Key, wo generiert, wo gespeichert
- [ ] **Datenbank-Wahl** finalisieren → Lösch-Mechanismus implementieren (TTL-Index oder Cronjob)
- [ ] **IP-Anonymisierung** in Flask-Logs implementieren (letztes Oktett maskieren)
- [ ] **Datenschutzerklärung** als öffentliche HTML-Seite auf `safe2gether.de/datenschutz` — **muss vor Beta-Launch live sein**
- [ ] **Impressum** auf `safe2gether.de/impressum` (§ 5 TMG)
- [ ] Verzeichnis von Verarbeitungstätigkeiten (VVT) anlegen (Art. 30 DSGVO)

---

## Nicht in v1.0

| Feature | Datenschutz-Implikation | Zeitpunkt |
|---------|------------------------|-----------|
| Premium Live-Tracking | Echtzeit-Koordinaten in Gruppe → strengere Einwilligungspflicht | v2.0 |
| Aktivitäts-History | Bewegungsprofile → besondere Schutzkategorie | v2.0 |
| LoRa Hardware | Gerätedaten, Gateway-Logs | v2.0 |
| Android / FCM | FCM = Google-Datenweitergabe → separate Bewertung | v3.0 |
