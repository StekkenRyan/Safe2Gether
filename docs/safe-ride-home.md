# Safe Ride Home — Volunteer Drivers

*Definiert: 2026-06-01 — Erste Feature-Skizze, v2.x-Scope*

---

## Kern-Idee

Freiwillige Fahrer bringen Nutzer nachts sicher nach Hause — nicht-kommerzielle Mitnahme
als Community-Leistung. Vorbild: ehrenamtlicher Bremer Mitnahme-Dienst, eingestellt
Januar 2026 (vermutete Gründe: rechtliche / versicherungstechnische Themen — vor
Implementierung zu klären, siehe „Rechtliche Klippen").

> Sicherheit auch dann, wenn ÖPNV ausfällt, Taxi unbezahlbar ist oder ein vertrauter
> Mensch näher ist als ein kommerzieller Anbieter.

---

## Funktionsmodell — beide Rollen in einer Tab

Jeder Nutzer ist potenziell Fahrer **und** Hilfesuchender. Kein getrennter „Fahrer-Modus"
wie bei kommerziellen Diensten. Eine Tab, oben ein Toggle:

```
Tab: Safe Ride Home
   │
   ├── [Modus: Hilfe gesucht]
   │      Start- und Zielort wählen
   │      → Liste verfügbarer Fahrer in Reichweite (Profilbild, Reputation, Distanz)
   │      → Anfrage senden
   │
   └── [Modus: Hilfsbereit]
          Verfügbarkeit ein/aus
          Radius einstellen (z. B. 15 km)
          Zeitfenster (z. B. „Heute 22–02 Uhr")
          → Empfängt Anfragen passender Suchender
```

---

## Soft-Radius — kein Hardfail

Wenn eine Anfrage außerhalb des konfigurierten Fahrer-Radius liegt:

- **App zeigt klar an**: „Anfrage außerhalb deines Radius (18 km statt 15 km)"
- **Anfrage wird trotzdem zugestellt** — Fahrer entscheidet selbst
- Grund: Nachts können wenige zusätzliche Kilometer lebensentscheidend sein. Ein
  Hardfail würde Sicherheit gegen Komfort eintauschen — gegen die Produkt-Philosophie.

---

## Trinkgeld / Spritkostenbeteiligung

| Weg | Wie |
|-----|-----|
| Bar / persönlich | Standard — keine App-Vermittlung nötig |
| In-App (optional) | Nachträgliches Trinkgeld via Apple Pay / SEPA |

**Prinzip**: Trinkgeld ist **immer freiwillig**, niemals Bedingung. Vorgeschlagene
Beträge orientieren sich an Distanz (z. B. „~5 € für 12 km"), nicht an Tageszeit/Surge.

> Sobald Bezahlung zur Bedingung wird, fallen wir unter Personenbeförderungsgesetz.
> Freiwilliges Trinkgeld bei nachweislich nicht-gewerblicher Mitnahme ist juristisch
> ein anderer Sachverhalt — muss aber anwaltlich verifiziert werden.

---

## Reputation & Vetting

Fahrer brauchen ein höheres Vertrauensniveau als normale Community-Mitglieder.

- Telefon-OTP **verpflichtend** für Fahrer-Modus (nicht nur empfohlen wie sonst)
- Mindest-Reputation-Score zum Freischalten des Fahrer-Modus (z. B. 50)
- Erste N Fahrten: Suchender sieht „Neuer Fahrer" — kein automatisches Vertrauen
- Nach Fahrt: beide Seiten können Reputation steigern oder Vorfall melden
- Vorfall-Meldung → manuelle Review + temporäre Suspendierung möglich

---

## Sicherheit während aktiver Fahrt

- **Live-Standort-Sharing** mit Notfallkontakten automatisch aktiv während Ride
  (überschneidet sich mit Premium — denkbar als Free-Add-On nur während aktiver Ride)
- **Panic Button** bleibt im Ride-Screen ein-Tap-erreichbar
- Geplante Ankunftszeit + Auto-Check-In: bestätigt der Nutzer nach X Min. nicht,
  läuft Dead Man's Switch an (v2.0-Architektur greift hier)

---

## Tech-Skizze

| Komponente | Wofür |
|------------|-------|
| Fahrer-Verfügbarkeits-Endpoint | Geo-Index (H3) aller aktiven Fahrer mit Radius + Zeitfenster |
| Matching | Server liefert auf Anfrage alle Fahrer, deren Radius (oder Radius+Soft-Puffer) den Startpunkt abdeckt, sortiert nach Distanz |
| Live-Tracking während Fahrt | WebSocket-Channel (bereits in v2.0-Architektur vorgesehen) |
| Trinkgeld | Stripe / Apple Pay — DSGVO-Prüfung + Buchhaltungsmodell offen |

---

## Rechtliche Klippen — vor Implementierung klären

1. **Personenbeförderungsgesetz**: Wann gilt eine Mitnahme als gewerblich?
   Trinkgeld kann die Grenze überschreiten. Anwaltliche Klärung zwingend.
2. **Versicherung**: Kfz-Haftpflicht deckt Passagiere bei privater Mitnahme — Bedingungen
   variieren je Versicherer. Eventuell Gruppen-Police über Trägerverein nötig.
3. **Vetting-Tiefe**: Brauchen wir Führerschein-Verifikation? Strafregisterauszug?
   Wie oft erneuern?
4. **Haftung bei Unfall**: Wer trägt was? Klarer Disclaimer + dokumentierte Nutzer-
   zustimmung im Onboarding.
5. **Bremer Lesson Learned**: Warum genau wurde der Dienst eingestellt? Ansprache an
   das alte Team — vermutlich existieren dokumentierte Erfahrungen und Stolpersteine.

---

## Scope-Entscheidung: v2.x

- **Nicht v1.0** — Launch-Fokus bleibt Panic Button + Nearby Alerting
- **Nicht v2.0** (Dead Man's Switch, Premium-Tier, LoRa) — eigenständige Komplexität
- Sinnvoll als **v2.5 oder v3.0** — nachdem Community-Basis steht und das
  Reputation-System in echtem Betrieb getestet ist

---

## Offene Entscheidungen

- Rechtliche Trägerstruktur (gemeinnütziger Verein? Direktbetrieb durch Safe2Gether?)
- Vetting-Tiefe (Führerschein + Strafregister + Identitätsprüfung?)
- Geografischer Pilot — Bremen als Wiederbelebung oder größere Stadt als Test?
- Trinkgeld via In-App oder strikt offline?
- Verhältnis zu Premium-Tier — ist Live-Tracking während Ride Free oder Premium?
- Ein-Tab-Modell vs. eigener Bereich für Fahrer mit komplexerer Verfügbarkeits-UI?
