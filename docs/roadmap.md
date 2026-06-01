# Roadmap — Safe2Gether

*Definiert: 2026-05-31 — Roadmap-Planungsrunde*

---

## Entwicklungsprinzipien

- **Solo-Entwicklung, aber Team-ready**: Architektur und Repo-Struktur so, dass ein kleines Team (2–3 Personen) jederzeit einsteigen kann
- **Parallel: Backend + iOS gleichzeitig** — API-Contract zuerst definieren, dann beide Seiten parallel
- **Feature-getrieben, kein festes Datum** — fertig wenn Qualitätskriterien erfüllt sind
- **Open Source von Tag 1** — GitHub Repo public, AGPL v3

---

## Phase 0 — Fundament

*Bevor Code entsteht*

- [ ] API-Contract definieren (OpenAPI / Swagger)
- [ ] Repo-Struktur für kleine Teams: CONTRIBUTING.md, Issue-Templates, Branch-Strategie
- [ ] CI/CD-Grundgerüst (GitHub Actions: Lint, Tests)
- [ ] Lokale Dev-Umgebung: Docker Compose (Flask + Redis)
- [ ] Datenschutzerklärungs-Entwurf (DSGVO) — früh, nicht am Ende

---

## Phase 1 — v1.0 Entwicklung (parallel Backend + iOS)

### Backend (Flask + Redis)

- [ ] Auth-System: Apple Sign-In + Google Sign-In + E-Mail/Passwort + optionale 2FA
- [ ] Nutzerprofile & Notfallkontakte (CRUD)
- [ ] Panic Button Endpunkt → Alarm an Kontakte via APNs
- [ ] Nearby Alerting: Geohash-Registrierung (significantLocationChange) + Push an Nearby-Nutzer
- [ ] Reputation-System: Basis-Score via Telefon-OTP, Aktions-Tracking
- [ ] APNs-Integration (direkt, kein Firebase)
- [ ] DSGVO-Mechanismen: Retention 30 Tage auto-delete, Lösch-Request
- [ ] Monitoring: Cloudflare + systemd + UptimeRobot

### iOS App

- [ ] Onboarding-Flow (Auth, Kontakte hinterlegen, Permissions erklären)
- [ ] Panic Button UI — mehrere Auslösewege (In-App, Widget)
- [ ] Notfallkontakte verwalten
- [ ] Nearby Alerting: `significantLocationChange` → Geohash senden
- [ ] Alarm empfangen: Push → gestufter Response-Flow ("Ich helfe")
- [ ] Reputation-Anzeige im Profil
- [ ] Push-Notification Handling (APNs)

---

## Phase 2 — Beta

**Privater Beta-Kreis (10–50 Personen)**
- Vertrauenspersonen, kein öffentlicher Zugang
- Fokus: Core-Flow Panic Button → Kontakt alarmiert → bestätigt

**TestFlight (halboffene Beta)**
- Waitlist via Social Media / Community
- Bis 10.000 externe Tester möglich
- 2-Wochen-Mindestlaufzeit vor Launch-Entscheidung

---

## Phase 3 — v1.0 App Store Launch

### Launch-Kriterien (alle müssen erfüllt sein)

- [ ] Panic Button + Notfallkontakte funktionieren zuverlässig (0 kritische Bugs im Core-Flow)
- [ ] DSGVO-konforme Datenhaltung verifiziert (Datenschutzerklärung live, Retention implementiert)
- [ ] Kein kritischer Bug in 2-Wochen-Beta
- [ ] *(Nearby Alerting Nutzerdichte ist kein Launch-Kriterium — Feature ist von Anfang an da, wächst mit Community)*

### Launch-Kanal

- Instagram / TikTok — Teaser-Content bereits vorbereitet ([branding/teaser.md](branding/teaser.md))
- Post-Reihenfolge: B → D/F → Launch-Teaser (gemäß teaser.md)

---

## v2.0 — Nach erfolgreichem Launch

*Reihenfolge innerhalb v2.0 noch offen*

- [ ] **Dead Man's Switch** — Herzstück der ursprünglichen Architektur
  - Silent Push (APNs) + lokaler iOS-Timer kombiniert
  - Hybrid: Aktivitätserkennung + manueller Timer
  - Nutzer-konfigurierbare Eskalationskette
- [ ] **Premium-Tier** (Life360-Richtung)
  - Live-Standort-Sharing (Gruppen)
  - Ankunfts-/Abfahrts-Alerts
  - Aktivitäts-History (30 Tage)
  - In-App Purchase / Subscription
- [ ] **LoRa Hardware-Button**
  - STM32 + RFM95W Schlüsselanhänger als Panic-Button
  - Gateway schreibt direkt in SMS-Kanal (nicht durch Flask)
  - USP für Outdoor-Zielgruppe

---

## v2.x — Safe Ride Home (Volunteer Drivers)

*Eigenständiger Block — nicht Teil von v2.0, vermutlich v2.5*

- [ ] **Volunteer-Driver-Modell** — eine Tab, beide Rollen (Hilfesuchend / Hilfsbereit)
- [ ] **Soft-Radius-Matching** — Anfragen außerhalb des Fahrer-Radius mit Warnhinweis zustellbar
- [ ] **Live-Tracking & Panic Button während aktiver Fahrt** — Dead Man's Switch greift bei verpasster Ankunfts-Bestätigung
- [ ] **Optionales In-App-Trinkgeld** (Apple Pay / SEPA) — niemals Bedingung
- [ ] **Erhöhtes Fahrer-Vetting** — Telefon-OTP verpflichtend, Mindest-Reputation, ggf. Führerschein-Verifikation

**Vor Implementierung zu klären** (anwaltlich):
- Personenbeförderungsgesetz und Trinkgeld-Grenze
- Versicherungsmodell (Gruppen-Police vs. Einzelversicherung)
- Haftung bei Unfall + Disclaimer-Wortlaut
- Gründe für Einstellung des Bremer Vorbild-Dienstes

Details: [docs/safe-ride-home.md](safe-ride-home.md)

---

## v3.0 — Android & Wachstum

- [ ] Android-App — nach v2.0 etabliert
  - Plattform: nativ (Kotlin) oder Cross-platform Rewrite (TBD beim Android-Planungszeitpunkt)
- [ ] Weitere Features nach Community-Feedback

---

## Was bewusst nicht in v1.0 ist

| Feature | Grund |
|---------|-------|
| Dead Man's Switch | Komplexer (iOS Background, Funkloch-Puffer, lokaler Timer) — v2.0 |
| Premium-Tier / Monetarisierung | Erst Community aufbauen, dann monetarisieren |
| LoRa Hardware | Hardware-Komplexität zu hoch für MVP |
| Android | iOS first — solide Basis vor zweiter Plattform |
| 2FA verpflichtend | Optional in v1.0, nicht Blocker |
