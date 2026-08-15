# TruckerWorldMP Discord Bot

Der Python-Bot verbindet den Discord-Server mit der vorhandenen TruckerWorldMP-Plattform in
`D:\programmieren\TruckerWorldMP`. Website, Launcher und API bleiben die maßgebliche Datenquelle; der Bot liest die
öffentlichen `/api/v1`-Endpunkte und greift nicht direkt auf MongoDB oder Benutzer-Sitzungen zu.

## Funktionsumfang

- Live-Status, Spielerzahlen und Details aller Gameserver
- kommende Convoys, News, öffentliche TWMP-Profile und VTC-Suche
- aktuelle Launcher-Version mit Download, Prüfsumme und Release Notes
- automatische Bot-Präsenz sowie Status-, News- und Convoy-Meldungen
- Begrüßung, Abschied, Auto-Rolle und zentraler Discord-Protokollkanal
- persistentes, privates Ticketsystem mit Support-Rolle und Ticket-Kategorie
- lokale Discord-Verwarnungen, Timeout, Timeout-Aufhebung und Nachrichtenbereinigung
- komplette Einrichtung pro Discord-Server über `/admin`
- SQLite mit WAL-Modus für Konfiguration, Tickets und Discord-Verwarnungen

## Schnellstart unter Windows

Python 3.12 oder neuer wird benötigt. Die echte `.env` liegt bereits lokal vor und wird durch `.gitignore` nicht
versioniert.

```powershell
cd D:\programmieren\TruckerWorldMPP
.\start.ps1 -Install
```

Spätere Starts benötigen nur noch:

```powershell
.\start.ps1
```

Alternativ manuell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Discord Developer Portal

Unter **Bot → Privileged Gateway Intents** muss `Server Members Intent` aktiviert sein, damit Willkommen,
Abschied und Auto-Rolle funktionieren. `Message Content Intent` ist nicht erforderlich und bleibt aus.

Unter **Installation → Guild Install** werden die Scopes `bot` und `applications.commands` verwendet. Der Bot benötigt:

- Kanäle ansehen, Nachrichten senden, Links einbetten, Dateien anhängen und Nachrichtenverlauf lesen
- Kanäle verwalten für private Tickets
- Nachrichten verwalten für `/mod loeschen`
- Mitglieder moderieren für Discord-Timeouts

Der passende Installationslink wird nach der ersten Installation auch mit `/admin einladung` ausgegeben. Für schnelle
Command-Updates während der Einrichtung kann `DISCORD_GUILD_ID` auf die ID des Testservers gesetzt werden. Ohne diese
ID werden Commands global synchronisiert; Discord kann globale Änderungen verzögert ausrollen.

## Ersteinrichtung auf dem Discord-Server

Nach der Bot-Installation führt ein Administrator diese Befehle aus:

```text
/admin kanal bereich:willkommen kanal:#willkommen
/admin kanal bereich:abschied kanal:#abschied
/admin kanal bereich:protokoll kanal:#bot-log
/admin kanal bereich:ankuendigungen kanal:#ankuendigungen
/admin rolle bereich:support rolle:@Support
/admin rolle bereich:auto rolle:@Mitglied
/admin kategorie kategorie:Supporttickets
/admin ticket-panel kanal:#support
/admin anzeigen
```

Die Bot-Rolle muss in der Discord-Rollenliste über der Auto-Rolle und über moderierten Mitgliederrollen stehen.
Ein Ticketkanal wird nicht automatisch gelöscht: Beim Schließen bleibt er für Support-Mitarbeiter lesbar und kann
nach Dokumentation manuell entfernt werden.

## Befehle

`/twmp` bietet `status`, `server`, `convoys`, `news`, `profil`, `vtc`, `download`, `links` und `hilfe`.

`/ticket` bietet `erstellen`, `schliessen` und für Administratoren `panel`.

`/mod` bietet `warnung`, `warnungen`, `timeout`, `freigeben` und `loeschen`. Discord-Rechte und Rollenhierarchie werden
vor jeder Aktion geprüft. Diese Discord-Verwarnungen sind bewusst getrennt von den Plattform-Strafen der Website, weil
die vorhandene API keinen allgemeinen Bot-Service-Login für administrative Schreibzugriffe bereitstellt.

`/admin` bietet `anzeigen`, `kanal`, `rolle`, `kategorie`, `zuruecksetzen`, `ticket-panel` und `einladung`.

## `.env`

Die vollständige Vorlage steht in `.env.example`.

| Variable | Zweck |
| --- | --- |
| `DISCORD_CLIENT_ID` | Öffentliche Anwendungs-ID |
| `DISCORD_BOT_TOKEN` | Geheimes Bot-Token für Gateway und Discord-API |
| `DISCORD_CLIENT_SECRET` | Für diesen Bot nicht nötig; nur für einen späteren eigenen OAuth-Code-Flow |
| `DISCORD_GUILD_ID` | Optionaler Testserver für sofortige Command-Synchronisierung |
| `TWMP_API_URL` | Vorhandene Plattform-API, standardmäßig `https://truckerworldmp.com/api/v1` |
| `TWMP_WEB_URL` | Öffentliche Website für Links in Embeds |
| `BOT_DATABASE_PATH` | Lokale SQLite-Datei |
| `COMMAND_SYNC_ON_START` | Slash-Commands beim Start registrieren |
| `ENABLE_MEMBER_INTENT` | Mitgliederereignisse, Willkommen und Auto-Rolle |
| `STATUS_POLL_INTERVAL_SECONDS` | Status-/Präsenzintervall, mindestens 30 Sekunden |
| `ANNOUNCEMENT_POLL_INTERVAL_SECONDS` | News-/Convoy-Prüfung, mindestens 60 Sekunden |
| `REQUEST_TIMEOUT_SECONDS` | HTTP-Timeout zur Plattform |

Der Bot liest `DISCORD_CLIENT_SECRET` nicht für seinen normalen Betrieb. Discord-Bots authentifizieren sich mit dem
Bot-Token; die Client-ID identifiziert die Anwendung und erzeugt den Installationslink.

## Tests und Qualität

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

## Produktion

Docker Compose:

```bash
docker compose up -d --build
docker compose logs -f discord-bot
```

Ohne Docker kann `deployment/truckerworldmp-bot.service` nach `/etc/systemd/system/` kopiert und an Benutzer sowie Pfad
der Zielmaschine angepasst werden. `data/` und `logs/` müssen für den Dienst beschreibbar sein.

Das Token gehört ausschließlich in `.env` oder den Secret Store der Laufzeit. Wird es außerhalb einer geschützten
Umgebung geteilt, sollte im Discord Developer Portal ein neues Token erzeugt und nur die lokale `.env` aktualisiert werden.

