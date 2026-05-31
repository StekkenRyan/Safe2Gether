# Features & Product Scope — Safe2Gether

*Definiert: 2026-05-31 — Feature-Planungsrunde*

---

## Kern-Philosophie

> **Sicherheit ist immer gratis. Premium ist Komfort und Community.**

Kein sicherheitsrelevantes Feature darf hinter einer Paywall stehen — sonst ist die App sinnlos.
Premium geht in Richtung Life360: Gruppen-Tracking, History, Komfort-Features.

---

## Free-Tier (immer, für alle)

| Feature | Details |
|---------|---------|
| **Panic Button** | Sofortiger Hilferuf — In-App + Widget + optionaler Hardware-Button |
| **Dead Man's Switch** | Hybrid: Aktivitätserkennung (GPS/Accelerometer) + manueller Timer als Fallback |
| **Notfallkontakte** | Unbegrenzt — keine Paywall auf Sicherheit |
| **Nearby Alerting** | Community-Alarm bei Notfall — dynamischer Radius |
| **Eskalationskette** | Nutzer konfiguriert selbst: Gerät → Kontakte → Community (beliebige Reihenfolge) |

---

## Premium-Tier (Life360-Richtung)

| Feature | Details |
|---------|---------|
| **Live-Standort-Sharing (Gruppen)** | Familie/Freunde sehen sich gegenseitig in Echtzeit — freiwillig, jederzeit abschaltbar |
| **Ankunfts-/Abfahrts-Alerts** | Kontakte werden informiert, wenn Nutzer einen Ort verlässt oder ankommt |
| **Aktivitäts-History** | Verlauf letzter Routen + Heartbeat-Logs — für Nutzer selbst und freigebbare Kontakte |

*Abgegrenzt: Notfall-Profil (QR-Code für Ersthelfer) wurde bewusst nicht priorisiert — ggf. spätere Iteration.*

---

## Kernfunktionen — Details

### Dead Man's Switch (Hybrid)

```
Aktivitätserkennung (GPS/Accelerometer) läuft im Hintergrund
       │
       ├── Bewegung erkannt → kein Alarm, Timer resettet
       └── Keine Bewegung (+ Funkloch-Puffer aus EXPECTED_OFFLINE)
              │
              └── Timer abgelaufen → Eskalation nach Nutzer-Konfiguration
```

Funkloch-Puffer: App meldet vor Eintritt `EXPECTED_OFFLINE` + Timer an Server.

### Panic Button — Auslösewege

- **In-App Button** — primärer Weg
- **iOS Widget** — Sperrbildschirm / Home Screen
- **Hardware-Button** — optional (LoRa-Schlüsselanhänger, Bluetooth)
- *(Gesten-Trigger bewusst nicht priorisiert — zu hohes versehentliches Auslöse-Risiko)*

### Nearby Alerting — Flow

```
Alarm ausgelöst
       │
       ▼
Nearby-Nutzer erhalten Push (dynamischer Radius: Stadt klein, Outdoor groß)
       │
       ├── Nutzer sieht: grobe Richtung + Entfernung (kein exakter Pin)
       │
       └── Nutzer drückt "Ich helfe" → exakter Standort freigeschaltet
```

### Cold-Start-Verhalten (geringe Nutzerdichte)

Feature ist von Anfang an aktiv — keine künstliche Deaktivierung.
Bei wenigen Nearby-Nutzern in der Region zeigt die App einen transparenten Hinweis:
> "In deiner Region sind aktuell wenige Nutzer aktiv — dein Alarm wird trotzdem gesendet."

Wachstum der Nutzerdichte ausschließlich über Marketing/Social Media — keine technische Workaround-Lösung geplant.

### Eskalationskette — Nutzer-konfigurierbar

Jeder Nutzer stellt seine eigene Reihenfolge ein. Mögliche Ketten:
- Gerät → Kontakte → Community
- Gerät → Community → Kontakte (z.B. Alleinwanderer ohne erreichbare Kontakte)
- Gerät → Kontakte + Community gleichzeitig (Hochrisiko-Modus)

---

## Reputation-System

### Score-Berechnung (Kombination)

| Quelle | Wirkung |
|--------|---------|
| Telefonnummer-Verifikation | Basis-Score (sofort) |
| Echte Hilfsaktionen ("Ich helfe" + Follow-through) | Score steigt |
| Falschalarme (gemeldet/erkannt) | Score sinkt |
| Nutzungsdauer (Loyalität) | Bonus über Zeit |

### Score-Sanktionen

| Score-Level | Wirkung |
|-------------|---------|
| Normal | Vollzugriff |
| Niedrig | Kann Alarme senden (mit Falschalarm-Hinweis für Empfänger), empfängt keine Community-Alerts |
| Sehr niedrig | Manuelle Review, weiterhin Alarm-Senden möglich (Sicherheit bleibt) |

**Prinzip**: Score entzieht Vertrauen, nie die Fähigkeit Hilfe zu rufen.

---

## Offene Entscheidungen (nächste Planungsebene)

- Genaue Preispunkte für Premium (Monat / Jahr)
- DSGVO-Architektur: wie wird Standort für Nearby Alerting gespeichert/gelöscht?
- Minimale Nutzerdichte für Nearby Alerting — was passiert wenn niemand in der Nähe ist?
- Onboarding-Flow: wie wird Vertrauen aufgebaut ohne Reibung?
- iOS Background-Limits: wie bleibt DMS bei iOS-Background-Einschränkungen zuverlässig?
