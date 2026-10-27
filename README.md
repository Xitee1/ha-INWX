# INWX für Home Assistant

![Status: Work in Progress](https://img.shields.io/badge/status-WIP-orange)
![KI-generiert](https://img.shields.io/badge/code-KI--generiert-blueviolet)

> [!WARNING]
> **Work in Progress:** Die Integration ist noch nicht mit einem echten INWX-Konto getestet.
> Funktionen und Entitäten können sich noch ändern.

> [!NOTE]
> **KI-generiert:** Code, Tests und Dokumentation dieses Projekts wurden mit KI
> (Claude Code, Anthropic) erstellt.

Benutzerdefinierte Integration, die ein [INWX](https://www.inwx.de/)-Konto über die
DomRobot-API (JSON-RPC) überwacht: Domains, Verlängerungstermine, Verlängerungspreise und
das Kontoguthaben. Ein Binärsensor warnt, wenn das Guthaben die anstehenden automatischen
Verlängerungen nicht deckt.

Gedacht vor allem für `.de`-Domains, bei denen WHOIS kein Ablaufdatum liefert.

## Installation

### HACS (benutzerdefiniertes Repository)

1. HACS → Menü → **Benutzerdefinierte Repositories** → URL dieses Repositorys, Typ
   **Integration**.
2. **INWX** installieren und Home Assistant neu starten.

### Manuell

Den Ordner `custom_components/inwx` nach `<config>/custom_components/inwx` kopieren und
Home Assistant neu starten.

## Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → INWX**

| Feld | Beschreibung |
|------|--------------|
| Benutzername | Benutzername des INWX-Kontos |
| Passwort | Passwort des INWX-Kontos |
| 2FA-Secret | Base32-Schlüssel aus der INWX-2FA-Einrichtung. Nur nötig, wenn das Konto Zwei-Faktor-Authentifizierung nutzt. |

Das 2FA-Secret ist der Schlüssel, der beim Einrichten der Zwei-Faktor-Authentifizierung
angezeigt wird (meist als QR-Code, darunter als Text). Die Integration erzeugt daraus selbst
die Einmalcodes. Wurde der Schlüssel damals nicht gesichert, muss 2FA bei INWX neu
eingerichtet werden.

INWX bietet keine API-Schlüssel an. Die Integration meldet sich deshalb mit den
Kontozugangsdaten an und hat damit dieselben Rechte wie das Konto. Sie liest nur Daten und
ändert nichts.

Geänderte Zugangsdaten: Bei einem Anmeldefehler fragt Home Assistant selbst nach neuen
Zugangsdaten. Manuell geht es über **Neu konfigurieren** im Menü der Integration.

## Optionen

| Option | Standard | Beschreibung |
|--------|----------|--------------|
| Prognosezeitraum | 30 Tage | Zeitraum, in dem automatische Verlängerungen addiert und mit dem verfügbaren Guthaben verglichen werden (1–365 Tage). |
| Preise inkl. MwSt. | an | Verlängerungspreise inkl. MwSt. verwenden. Ausschalten, wenn das Konto netto abgerechnet wird. |

## Entitäten

### Gerät „INWX &lt;Benutzername&gt;“

| Entität | Typ | Beschreibung |
|---------|-----|--------------|
| Verfügbares Guthaben | Sensor (Währung) | Verfügbares Guthaben laut INWX (`available`). |
| Verlängerungskosten im Prognosezeitraum | Sensor (Währung) | Summe der Verlängerungspreise aller automatischen Verlängerungen bis zum Ende des Prognosezeitraums. |
| Nächste Verlängerung | Sensor (Zeitstempel) | Frühestes Verlängerungsdatum aller Domains mit automatischer Verlängerung. |
| Guthaben für Verlängerungen | Binärsensor (Problem) | `Problem`, wenn die Verlängerungskosten im Prognosezeitraum größer sind als das verfügbare Guthaben. |

### Ein Gerät pro Domain

| Entität | Typ | Beschreibung |
|---------|-----|--------------|
| Verlängerungsdatum | Sensor (Zeitstempel) | Zeitpunkt, an dem INWX die Domain verlängert (`reDate`). |
| Ablaufdatum | Sensor (Zeitstempel) | Ende des bezahlten Zeitraums (`exDate`). |
| Verlängerungspreis | Sensor (Währung) | Verlängerungspreis der Domain für ihre Laufzeit. |
| Verlängerungsmodus | Sensor (Auswahl) | Automatisch verlängern / Automatisch löschen / Automatisch auslaufen. |
| Status | Sensor | Domainstatus laut INWX. |

Neue Domains bekommen beim nächsten Abruf automatisch ein Gerät. Domains, die das Konto
verlassen, werden samt Gerät entfernt.

## Berechnung der Guthaben-Warnung

- Berücksichtigt werden nur Domains mit Verlängerungsmodus **Automatisch verlängern**.
- Gezählt wird jede Verlängerung, deren Datum bis zum Ende des Prognosezeitraums liegt.
  Verlängerungsdaten in der Vergangenheit (noch nicht abgebucht) zählen mit.
- Domains mit kurzer Laufzeit (z. B. `1M`) werden pro Laufzeit im Zeitraum einmal gezählt.
- Verglichen wird mit dem verfügbaren Guthaben. Ein Kreditlimit wird nicht einbezogen.

Beispiel: Guthaben 5,00 €, Verlängerung von Domain A in 25 Tagen (4,76 €) und von Domain B
in 29 Tagen (4,76 €). Bei 30 Tagen Prognosezeitraum ergeben sich 9,52 € Kosten, der
Binärsensor steht auf `Problem`.

## Datenabruf

Einmal pro Stunde: Anmeldung, Guthaben, Domainliste, Verlängerungspreis pro Domain,
Abmeldung. Jeder 2FA-Code wird nur einmal verwendet. Folgen zwei Anmeldungen im selben
30-Sekunden-Fenster aufeinander (z. B. direkt nach der Einrichtung), wartet die Integration
auf den nächsten Code.

## Bekannte Einschränkungen

- Die Auswertung der Preisantwort (`domain.getalldomainprices`) und das Zeitformat der API
  sind aus der API-Dokumentation abgeleitet und noch nicht gegen ein echtes Konto geprüft.
  Zeitangaben ohne Zeitzone werden als deutsche Ortszeit gelesen.
- Das Icon in `custom_components/inwx/brand/icon.png` ist das INWX-Logo (Globus), erstellt
  aus dem GitHub-Profilbild von INWX. Es gibt nur `icon.png` (256 × 256), weil die Vorlage
  für eine scharfe 512er-Variante zu klein ist. Die Markenrechte liegen bei INWX.

## Entwicklung

```bash
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
