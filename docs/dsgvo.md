# DSGVO-Entwurf — Safe2Gether

*Stand: 2026-05-31 — Interner Arbeitsentwurf, kein rechtsgültiges Dokument*

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
| **Apple APNs** | Push-Benachrichtigungen (Alarme, DMS) | APNs Device Token | Art. 6 Abs. 1 lit. b |
| **Apple Sign In** | Authentifizierung | Sub (anonyme ID) + optional E-Mail via Privacy Relay | Art. 6 Abs. 1 lit. b |
| **Google Sign In** | Authentifizierung | Sub + E-Mail | Art. 6 Abs. 1 lit. b |
| **Cloudflare** | CDN / Tunnel / DDoS-Schutz | IP-Adressen, HTTP-Metadaten | Art. 6 Abs. 1 lit. f (Sicherheit) |
| **SMS-Provider** (TBD) | OTP-Versand | Telefonnummer | Art. 6 Abs. 1 lit. a |
| **Firebase/FCM** | **Nicht verwendet** — APNs direkt | — | — |

**Kein Tracking, keine Werbung, keine Datenweitergabe an Dritte zu Marketingzwecken.**

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
| Keine Drittland-Übertragung | Server auf `sora` (DE); Cloudflare EU-Rechenzentrum konfigurieren |
| Logging | Kein personenbezogenes Logging in Produktions-Logs (IPs maskieren) |

---

## Offene Entscheidungen vor Launch ⚠️

Diese Punkte **müssen** vor dem App-Store-Launch geklärt und implementiert sein:

- [x] **Verantwortlichen** festlegen (Paul Czymek) und in Datenschutzerklärung eintragen
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
