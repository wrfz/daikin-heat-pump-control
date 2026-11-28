# Daikin Heat Pump Control – Architektur

Status: freigegeben (26.11.2026).

Funktionsbeschreibung der bisherigen Komponenten und des Dashboards (Protokolldetails, Entity-Tabellen,
Prüfdaten, Fundstellen): `design/reference/can.md`, `design/reference/uart.md`,
`design/reference/dashboard.md`.

## 1. Ziel

Eine Home-Assistant-Integration (Domain `daikin_heat_pump_control`) für Daikin-Wärmepumpen mit
RoCon-Regler (Rotex HPSU, Daikin Altherma, ECH₂O), die den gesamten Funktionsumfang der beiden
ESPHome-Komponenten (CAN: lesen und schreiben, UART: lesen) und des Dashboards in einem Paket bündelt.
Die ESP32-Knoten laufen nur noch als Bridge: sie leiten rohe CAN-Frames bzw. UART-Bytes weiter.
Protokoll, Dekodierung, Abfrageplanung, Schreiben, berechnete Werte, Abtauoptimierung und Oberfläche
liegen in der Integration.

Nicht enthalten (vorerst): Vorlauf-Soll-Regelung (`supply_setpoint_regulated`), Heizprogramm 1, das
Manifest für Fremdsysteme (diese lesen die Entities der Integration direkt).

Rahmen: HA 2026.11, Python 3.14, HACS-fähig, Config-Flow, Diagnostics, Übersetzungen de/en/fr/it,
Code und Kommentare englisch, README englisch + deutsch. Eine Wärmepumpe je HA-Instanz (ein
Config-Entry, im Flow erzwungen; Abschnitt 4). Kein Code aus den Quellprojekten; die Protokolle
werden neu umgesetzt.

Namen: kein Präfix `hpsu`. Bezeichner in Code, Diensten, Firmware und Frontend beginnen mit `daikin`.

Keine Migration: Die Integration legt eigene Entities an und übernimmt nichts von den bisherigen
ESPHome-Entities. Diese bleiben unberührt; wer einen ESP wieder mit der bisherigen Firmware flasht,
hat sie wie vorher. Ob später eine Migration nötig ist, entscheidet der Nutzer am Ende.

## 2. Gesamtbild

```
ESP32-Knoten (Bridge-Firmware: CAN, UART oder beide) ──┐                         ┌─ Entities (sensor, number, select, …)
   CAN 20 kbit/s / UART 9600 8E1, Ringpuffer RX        │  eigene aioesphomeapi-  │
ggf. zweiter ESP32-Knoten ─────────────────────────────┼─ Verbindung je Knoten ──┼─ Logik (berechnete Werte, Abtauen,
                                                       │  (verschlüsselt)        │   Fehlererkennung)
                                                       │                         └─ Panel + Card (Lit/TS), WebSocket-API
ESPHome-Integration (bleibt) ──────────────────────────┘  OTA, Logs, Firmware-Update, eigene Extras des Nutzers
```

- CAN und UART sind beide optional; mindestens einer muss eingerichtet sein.
- Aufbau frei: ein ESP je Bus oder ein ESP mit beiden Bussen.
- Geräte:
  - je Bus ein Gerät „Daikin CAN“ / „Daikin UART“ mit den Werten des Busses – unabhängig davon, auf
    welchem ESP der Bus läuft, damit die Entity-IDs nicht vom Aufbau abhängen;
  - je ESP ein Gerät „Daikin Bridge <ESP-Name>“ mit dessen Diagnose-Entities (Abschnitt 6.4); die
    Bus-Geräte hängen über `via_device` daran. Ein ESP mit beiden Bussen ergibt ein Bridge-Gerät, an dem
    beide Bus-Geräte hängen.

## 3. Transport ESP ↔ Integration

Anforderung: Der Recorder zeichnet nur Entity-Werte auf, nicht die Kommunikation.

Entscheidung: **API-Aktionen mit Antwort, abgefragt von der Integration** über eine eigene
aioesphomeapi-Verbindung (`execute_service(..., return_response=True)`).

Begründung:
- `homeassistant.event` vom ESP scheidet aus: der Knoten bleibt in der ESPHome-Integration, und diese
  feuert jedes Ereignis auf den HA-Bus → der Recorder speichert es in der Tabelle `events`.
- Frames als Text-Sensor scheiden aus: Entity im Recorder, Verlust bei schnellen Folgen.
- Eigener TCP-Socket auf dem ESP: unverschlüsselt und braucht eine eigene C++-Komponente.
- Antworten auf API-Aktionen laufen nur über die Verbindung des Aufrufers, erreichen den HA-Bus nicht
  und sind mit dem Knoten-Schlüssel verschlüsselt. Die ESPHome-Integration sieht nur, dass es die Aktion
  gibt (als Dienst `esphome.<knoten>_…`).

Aktionen der Bridge (Namen vorläufig):

| Aktion | Eingabe | Antwort |
|---|---|---|
| `daikin_bridge_info` | – | angebotene Busse (`can`, `uart` oder beide), Firmware-Version, Puffergrößen, Diagnosewerte (Abschnitt 6.4) |
| `daikin_can_exchange` | 0…n zu sendende Frames (ID + Daten, hex) | alle seit dem letzten Aufruf empfangenen Frames mit ESP-Zeitstempel (ms), Überlauf-Zähler |
| `daikin_uart_exchange` | 0…n zu sendende Bytes (hex) | alle seither empfangenen Bytes mit Zeitstempel des ersten Bytes, Überlauf-Zähler |
| `daikin_bridge_claim` | – | macht den Aufrufer zum Master (Abschnitt 3.1) |

- Takt: die Integration ruft `exchange` alle 200 ms auf (fest; darüber wäre der CAN langsamer als heute), sofort, sobald etwas
  zu senden ist, und beim UART nach einer Anfrage im 100-ms-Takt, bis die Antwort vollständig ist.
- Der ESP puffert empfangene Frames in einem Ringpuffer (CAN mind. 256 Frames, UART 1 KiB). Überlauf
  wird gezählt und als Diagnosewert gemeldet.
- Gleich schnell wie die bisherigen Komponenten: Die Bridge sendet einen übergebenen CAN-Frame erst,
  wenn der Bus 250 ms ruhig war (reine Zeitregel, kein Protokollwissen). Die Integration übergibt die
  nächste Anfrage, sobald sie die Antwort gesehen hat; da der Abruftakt (200 ms) unter der Ruhezeit
  liegt, geht die Verzögerung in der Ruhezeit auf, und der Abstand der Anfragen bleibt bei etwa 0,3 s.
  Schreibvorgänge laufen über dieselbe Regel.
- Zeitüberschreitung (3 s) und Fälligkeit rechnet die Integration anhand der ESP-Zeitstempel, nicht
  anhand der HA-Uhr.
- Verbindungsabbruch: die Werte werden `unavailable`, Wiederverbindung mit Backoff; laufende Schreib-
  wünsche verfallen und werden im Log gemeldet.

Die Bridge-Firmware wird im Repo mitgeliefert: eine kleine externe Komponente
`esphome/components/daikin_bridge` (C++), eingebunden über `external_components` (aus dem
GitHub-Repo, Branch oder Release-Tag), und unter `examples/` drei vollständige YAMLs
`daikin-can-bridge.yaml`, `daikin-uart-bridge.yaml` und `daikin-can-uart-bridge.yaml` (beide Busse
auf einem ESP) mit Board, WLAN, API, OTA, Bus-Hardware und `daikin_bridge:`. Der Nutzer kopiert eine
davon und passt sie an. Die Komponente kennt kein Protokoll; sie enthält nur Ringpuffer, Zeitregel,
die Aktionen und die Diagnose. Ihre API-Aktionen registriert sie selbst; in der YAML stehen keine,
damit YAML und Komponente nicht auseinanderlaufen können (eigene Aktionen mit diesen Namen lehnt
die Prüfung der Konfiguration ab, andere Aktionen des Nutzers bleiben möglich). Sie nutzt die
Standard-Schnittstellen `canbus::Canbus` und `uart::UARTComponent`; für den Host-Test werden diese
durch eine Socket-Anbindung an den Simulator ersetzt (Abschnitt 11). Bei beiden Bussen laufen die
Aktionen unabhängig voneinander (eigene Puffer, eigene Zeitregeln). Die Firmware enthält keine
Sensoren für HA; Diagnosewerte liefert sie über `daikin_bridge_info`.

Datenformat (JSON in `response_data`, Zeitstempel `t` in ms seit Start des ESP, 32 Bit mit Überlauf):
- `daikin_can_exchange(frames: string[])`: je Frame `"<id hex>#<daten hex>"`, z. B.
  `"680#3100FAC0FC0000"`. Antwort `{"now": t, "rx": [[t, id, "daten"], …], "tx": [[t, id,
  "daten"], …], "more": bool, "pending": n, "overflows": n, "dropped": n}`; `tx` = seit dem
  letzten Aufruf tatsächlich gesendete Frames, `pending` = noch wartende, `dropped` = abgewiesene
  (volle Sende-Warteschlange, 16 Frames). ESPHome begrenzt eine Aktions-Antwort auf 5120 Byte
  JSON; daher höchstens 100 empfangene Frames je Antwort, `more` = weitere liegen im Puffer, die
  Integration ruft sofort erneut auf.
- `daikin_uart_exchange(data: string)`: zu sendende Bytes hex. Antwort `{"now": t, "rx_t": t,
  "rx": "bytes hex", "tx_t": t, "overflows": n}`.
- `daikin_bridge_info`: `{"bridge": version, "esphome": version, "buses": […], "uptime": s,
  "heap_free": n, "heap_max_block": n, "reset_reason": text, "wifi": {"rssi", "ssid", "ip"},
  "can": {"buffer", "overflows", "state", "tx_errors", "rx_errors", "arbitration_lost",
  "bus_off"}, "uart": {"buffer", "overflows"}}`. Eigene Erweiterungen des Nutzers (z. B. ein
Relais für Smart Grid) bleiben in seiner YAML und damit in der ESPHome-Integration. Die Komponente setzt
das ESPHome-Projekt selbst (Name aus den Bussen, Version = Version der Komponente; ein eigenes
`esphome: project:` lehnt die Prüfung ab): `wrfz.daikin_can_bridge`, `wrfz.daikin_uart_bridge`,
`wrfz.daikin_can_uart_bridge` (in HA nur auf der ESPHome-Geräteseite als Hersteller/Modell sichtbar,
nicht in Entity-Namen).

### 3.1 Mehrere Clients (Master)

Mehrere HA-Instanzen (z. B. Produktiv und Entwicklung) können an derselben Bridge hängen.
- Nur eine Integration kommuniziert mit der Wärmepumpe (Master): nur ihre Anfragen und
  Schreibvorgänge werden gesendet. Die empfangenen Frames bekommen alle angemeldeten Integrationen,
  damit sie dieselben Werte anzeigen. Die `exchange`-Aktionen tragen dazu eine Kennung des Aufrufers
  und melden, ob er Master ist.
- Verabschiedet sich der Master, erkennt das die Bridge und macht eine der übrigen zum Master.
- Jede Integration, die nicht Master ist, zeigt im Dashboard (Panel und Card) einen Knopf „Master
  werden“; ein Druck macht sie zum Master, die bisherige verliert den Status. Keine Entity.
- Option „Bevorzugter Master“ (Options-Flow, Standard aus): die Integration wird nach jedem Verbinden
  Master. Für die Produktiv-Instanz gedacht, damit sie nach einem Neustart wieder steuert.
- Wer nicht Master ist, schreibt nicht (Fehler `not_master`); Abtauoptimierung, Schreibzähler und
  UART-Erkennung laufen nur beim Master.
- Kein anderer Sender auf demselben ESP: `daikin_bridge` lehnt beim Validieren der Konfiguration die
  bisherigen Komponenten und weitere Sender auf dem Bus ab; reines Mitlesen (`on_frame`) bleibt
  erlaubt.
- Ältere Bridge-Firmware ohne diese Funktion: Repair-Issue „Bridge-Firmware aktualisieren“.

## 4. Einrichtung und Erkennung

Config-Flow (ein Eintrag):
1. Kandidaten suchen: alle Config-Entries der ESPHome-Integration und Zeroconf-Funde
   (`_esphomelib._tcp`). Der API-Schlüssel kommt aus dem ESPHome-Eintrag (`noise_psk`), sonst fragt
   der Flow danach.
2. Jeden Kandidaten kurz verbinden und feststellen, welche Busse er anbietet (ein Knoten kann beide
   haben):
   - Bridge-Firmware: `project_name` bzw. Busse laut `daikin_bridge_info`.
   - Bisherige Firmware: wird erkannt (Manifest-Aktion der CAN- bzw. UART-Komponente) und mit dem
     Hinweis „Bridge-Firmware flashen“ angezeigt; auswählbar, die Busse starten dann, sobald der Knoten
     die Bridge-Firmware meldet (Abschnitt 9).
3. Je Bus: kein Fund → Bus aus; genau ein Fund → vorausgewählt; mehrere → Auswahl. Der Nutzer kann
   einen Bus abwählen. Ein Knoten mit beiden Bussen wird für beide vorausgewählt.
4. UART: Außengerät wählen (13 Modelle, bestimmt Lüfterfaktor, Kältemittel R32/R410A, Lage von
   Kältemitteldruck und Sättigungstemperatur) und Protokoll (automatisch / I / S).

Weitere Wege und Regeln:
- Manuelle Eingabe (Host, Port Standard 6053, Schlüssel) als zusätzlicher Weg im Config-Flow und im
  Reconfigure; der Knoten wird wie die gefundenen geprüft (Verbindung, Busse, Firmware).
- Zeroconf im Manifest nur für `_esphomelib._tcp.local.` mit `project_name: wrfz.daikin_*`; der
  Schritt prüft `project_name` trotzdem (sonst Abbruch `not_daikin_bridge`). Die bisherige Firmware
  findet nur die Suche in den ESPHome-Einträgen (plus manuelle Eingabe).
- Ein Eintrag je HA-Instanz, `unique_id` = Domain, im Flow erzwungen (kein `single_config_entry`, damit
  Discovery-Flows den eigenen Schritt erreichen). Knoten werden über ihre MAC zugeordnet.
- Zeroconf bei bestehendem Eintrag: bekannte MAC → Host nachführen, Abbruch `already_configured`;
  unbekannte MAC → Discovery anbieten, der Nutzer weist den ESP je Bus zu (alten Knoten ersetzen / Bus
  hinzufügen / ignorieren). Nicht mehr zugeordnete Knoten werden entfernt (stale devices). Dieselbe
  Zuweisung im Reconfigure.
- Host beim Verbinden: bevorzugt aus dem ESPHome-Eintrag mit gleicher MAC (samt Schlüssel), sonst
  `<name>.local`, sonst die gespeicherte IP.

Options-Flow: Knoten neu zuordnen, Außengerät/Protokoll, Abfrageintervalle (global und je Gruppe),
Offsets für die Fehlererkennung (`tv`, `tvbh`, `tr`), Grenzwerte der Spreizungsprüfung, Panel in der
Seitenleiste an/aus, Dashboard (externe Werte, Info-Box; Abschnitt 10).

Abfrageintervalle (CAN): jede Entity der Tabelle gehört zu einer Gruppe – Messwerte (Temperaturen,
Druck, Durchfluss, Pumpe, Ventile), Zustände (binäre Werte, Betriebsart, Fehlercode, SG-Zustand),
Einstellungen (number/select/switch) und Zähler (Energie, Laufzeiten, Systemzeit). Intervall einer
Entity: das Gruppenintervall, wenn gesetzt; sonst ihr eigener Standard (Durchfluss 10 s,
Betriebsmodus 5 s), sonst das globale Intervall (Standard 30 s).

## 5. Paketaufbau

Standardaufbau einer eigenen Integration: die Integration liegt im Repo unter
`custom_components/daikin_heat_pump_control/`, alles andere daneben. Der Marketplace installiert
diesen Ordner direkt aus dem Release-Tag (kein Zip, kein Build-Schritt).

```
custom_components/daikin_heat_pump_control/
  __init__.py, manifest.json, config_flow.py, const.py, diagnostics.py, services.yaml,
  strings.json, translations/, icons.json, quality_scale.yaml, py.typed
  bridge/        Verbindung je Knoten (aioesphomeapi), exchange-Takt, Wiederverbindung
  can/           Frame-Kodierung, Entity-Tabelle (Daten), Abfrageplaner, Schreibwarteschlange
  uart/          Protokoll I/S, Erkennung, Rahmen-Parser, Konverter, Entity-Tabelle (Daten),
                 Dampfdrucktabellen (Daten)
  logic/         berechnete Werte, Glättung, Fehlererkennung, Abtauoptimierung, Warmwasser-Taste
  coordinator.py Zustand der CAN-Werte, Verteilung an die Entities, Schreiben
  uart_coordinator.py  Zustand der UART-Werte, Protokollerkennung, Kältekreiswerte
  sensor.py, binary_sensor.py, number.py, select.py, switch.py, button.py
  dashboard.py   Wert-IDs des Dashboards (Tabelle) und ihre Entities
  panel.py       statischer Pfad, Modul im Frontend, Panel in der Seitenleiste
  websocket.py   API für Panel und Card
  frontend/      gebautes JS + SVG-Layouts (aus frontend-src/, eingecheckt)
frontend-src/    TypeScript/Lit: Card, Panel, Editor, gemeinsame Darstellung (src/), SVG-Layouts
                 (layouts/, beim Build kopiert), Vitest (test/)
esphome/         Bridge-Komponente (components/daikin_bridge)
examples/        vollständige Bridge-YAMLs (CAN, UART, beide)
scripts/         Erzeugung der Dampfdrucktabellen (nur Entwicklung)
tests/           pytest-homeassistant, Simulator unter tests/sim/, E2E unter tests/e2e/
design/          dieses Dokument
hacs.json, pyproject.toml, requirements_test.txt, .github/workflows/
```

Ablauf: Push/PR auf `main` → Workflows prüfen (Ruff, mypy, pytest mit Abdeckung ≥ 95 %,
Übersetzungen, hassfest, HACS). Veröffentlichen: `version` in `manifest.json` erhöhen, Tag `vX.Y.Z`
und GitHub-Release; der Workflow `release.yml` prüft, dass Tag und Manifest-Version gleich sind. Der
Marketplace zeigt das Release den Nutzern als Update an. Das gebaute Frontend (`frontend/`) wird
eingecheckt, damit der Ordner ohne Build-Schritt vollständig ist.

In `tests/` liegen keine `__init__.py` (pytest mit `--import-mode=importlib`). `custom_components/`
hat keine `__init__.py` (Namespace-Paket wie in HA). Entwicklung: der Ordner der Integration ist
per Symlink in `config/custom_components/` der HA-core-Dev-Instanz eingebunden.

Protokoll und Logik (`can/`, `uart/`, `logic/`) hängen nicht von Home Assistant ab und sind einzeln
testbar.

## 6. Funktionsumfang

### 6.1 CAN (lesen und schreiben)

- Bus 20 kbit/s, eigene Sender-ID 0x680. Byte 0 = Ziel (High-Nibble × 0x80) + Art (0 schreiben,
  1 lesen, 2 Antwort); Antwortende 0x180 (Regler), 0x300, 0x500; RoCon-Bedienteil 0x10A.
- Register kurz (Byte 2) oder lang (`FA` + 16 Bit in Byte 3–4); Daten 1 oder 2 Byte an einem Offset,
  vorzeichenbehaftet oder nicht, Teiler, Bereichsprüfung, „kein Wert“-Kennung, Wertetabellen;
  Sonderkodierungen (Leistungen in 0,01 kW, Heizstab-Bits 3/6/9 kW, externer Fühler).
- Alle 110 Entities der Komponente plus die Zusatz-Entities: berechnete Sensoren (thermische Leistung
  roh/geglättet, Spreizung roh/geglättet, Tv−TvBH, TvBH−Tr, Vorlauf-Soll−Tv, `tv_max`), Systemzeit und
  -datum, Taste „Warmwasser bereiten“, Schalter „Abtau-Optimierung“.
- Abfrage: je Entity ein Intervall (Standard 30 s, einzelne kürzer, z. B. Durchfluss 10 s,
  Betriebsmodus 5 s; Gruppen Abschnitt 4), immer nur eine offene Anfrage, 250 ms Busruhe, verloren
  nach 3 s, das am längsten überfällige zuerst; `tv` mit `tv_max` intern alle 2 s. Fällig ist ein
  Register, wenn seit der letzten Antwort und der letzten Anfrage das Intervall vergangen ist: eine
  verlorene Anfrage zählt als Versuch, das Register wird erst nach seinem Intervall erneut angefragt
  (ein Register, das die Anlage nicht kennt, blockiert die anderen nicht). Warnung beim ersten
  Verlust, danach Debug, bis wieder eine Antwort kommt.
- Systemzeit: ein Zeitstempel-Sensor aus den sechs Registern Tag/Monat/Jahr/Stunde/Minute/Sekunde
  (RoCon-Uhr als Ortszeit der HA-Zeitzone), standardmäßig deaktiviert; die Teile sind intern.
- Mithören: Antworten an andere Teilnehmer und Schreib-/Antwort-Frames des RoCon werden dekodiert
  (Änderungen am Bedienteil kommen ohne eigene Abfrage an).
- Schreiben: Abschnitt 7.
- Fehlercode: Grundtext aus der Tabelle, ergänzt um die erkannten Zusatzbefunde (3-Wege-Ventil
  Warmwasser defekt, Bypassventil defekt, zu geringe Spreizung, fehlender Durchfluss) mit den Haltezeiten
  10/10/20/5 min und der Mindestspreizung abhängig von Tv.
  Wie bisher läuft die Prüfung bei jedem Lesen von `error_code`; die erste Prüfung, deren Haltezeit
  abgelaufen ist, ergibt den Befund, die folgenden Prüfungen laufen dann nicht. Attribut `finding`
  (`dhw_valve_defect`, `bypass_valve_defect`, `low_temperature_spread`, `missing_flow` oder leer),
  der Zustand bleibt der Fehlercode. Offsets und Grenzwerte im Options-Flow.
- Fehlersuche ohne Entities: Dienst `daikin_heat_pump_control.send_raw_can` (1–7 Bytes, empfangene
  Antwort als Dienstantwort), Diagnose-Download mit allen Werten und Rohdaten, Log-Level über HA.
  Der Frame geht unverändert (ohne Auffüllen) mit ID 0x680 über die Warteschlange; Antwort ist der
  erste Antwort-Frame eines anderen Teilnehmers mit demselben Register (höchstens 3 s, sonst `null`).
  Frames ohne Leseanfrage kehren nach dem Senden zurück. Optional `config_entry_id`.

### 6.2 UART (nur lesen)

- 9600 8E1, Prüfsumme = Komplement der Byte-Summe.
- Protokoll I (`03 40 <reg> <crc>`, Antwort mit Längenbyte) und S (`02 <reg> <crc>`, feste Längen),
  NAK `15 EA` (beendet die offene Anfrage als Fehlschlag).
- Protokollwahl: Option automatisch / I / S. Automatisch: Erkennung wie die Komponente (Probe 0x60 I,
  2 s, dann 0x53 S, 2 s). Das Ergebnis wird getrennt von der Option im Eintrag gespeichert
  (`uart_detected_protocol`), der Eintrag lädt einmal neu; danach gibt es nur die Entities des
  erkannten Protokolls, überzählige UART-Entities werden aus der Registry entfernt. Vor der ersten
  erfolgreichen Erkennung gibt es keine UART-Wert-Entities (nur die Bridge-Diagnose). Ohne Antwort auf
  beide Proben fragt die Integration mit I weiter (Rückfall, nicht gespeichert); die erste gültige
  I-Antwort gilt als Erkennung. Erneut erkannt wird beim Ändern der UART-Optionen (das gespeicherte
  Ergebnis wird gelöscht) und wenn das gespeicherte Protokoll dauerhaft nicht mehr antwortet (alle
  abgefragten Register ausgefallen, siehe unten; höchstens alle 10 min): ein anderes Ergebnis wird
  gespeichert, der Eintrag lädt neu, einmal Warnung im Log.
- Alle Entities (32 Schlüssel, 11 binär, 3 Text) mit den Varianten je Außengerät und S-Layouts;
  Konverter: Ganzzahl LE/BE, Bits, Nibble, Zieltemperaturen (/256 auf 0,1 abgeschnitten).
- Geräteprofile (Daten, kein Code): je Außengerät Kältemittel, Lüfterfaktor und je Wertegruppe
  (Register bzw. Teil eines Registers) der Status `confirmed` (durch echte Frames belegt → Entity
  angelegt und aktiv), `unconfirmed` (laut Protokoll vorhanden, aber für diese Baureihe nicht belegt →
  angelegt, standardmäßig deaktiviert) oder `absent` (gibt es nicht → nicht angelegt, z. B. 0x62 auf
  RRLQ006CAV3, Druck in 0x20 und 4-Wege-Ventil auf ERGA E). Weitere Geräte brauchen nur einen
  Tabelleneintrag. Werte des Innengeräts (0x60, 0x61, S-Register) sind für alle Außengeräte belegt.
  Thermische Leistung roh/geglättet gibt es nur, wenn das Profil den Durchfluss hat (aktiv wie dieser).
  `discharge_pressure` (dieselben Bytes wie der Kältemitteldruck aus 0x62) entfällt dort, wo der
  Kältemitteldruck schon aus 0x62 kommt (ERGA E).
- Einheiten richtig: Kältemittel-/Hochdruck bar (bisher fälschlich °C). Durchfluss: 0x62 Byte 9–10
  liefert l/min ×10 (Register-Beschreibungen der Daikin-Geräte; echter ERGA-E-Frame 14,8 l/min ≈ CAN
  868 L/h an derselben Anlage); die Integration rechnet in L/h um (×60), gleiche Einheit wie der
  CAN-Durchfluss, die Leistungsformel bleibt dieselbe. Das Display der HPSU zeigt den RoCon-Wert
  (CAN 0x01DA) in L/h.
- Sättigungstemperatur aus dem Kältemitteldruck (absolut = gemessen + 1,01325 bar), R32 bzw. R410A je
  Außengerät. Tabelle: zur Entwicklungszeit mit CoolProp (freie Stoffwert-Bibliothek, Referenz-
  Zustandsgleichungen) in 0,1-K-Schritten erzeugt (`scripts/`, Ergebnis als Datendatei, zur Laufzeit
  keine Abhängigkeit), linear interpoliert, Bereich −65…+71 °C. Ein Test vergleicht mit der bisherigen
  1-K-Tabelle: Abweichung höchstens so groß wie deren Interpolationsfehler. Ist CoolProp nicht nutzbar,
  wird die bisherige Tabelle als Daten übernommen.
- Abfrage: eine offene Anfrage, verloren nach 3 s, jedes Register 5 s nach der letzten gültigen
  Antwort erneut, das am längsten nicht gesendete zuerst. Abgefragt werden nur Register, die eine
  aktive Entity (oder eine Berechnung für eine aktive Entity) braucht. Nach 3 Fehlschlägen in Folge
  (NAK, keine Antwort, Prüfsummenfehler) gilt ein Register als ausgefallen: es wird nur noch alle
  10 min angefragt, seine Werte sind `unavailable`, einmal Warnung im Log (Info, sobald es wieder
  antwortet), Zustand in der Diagnose.
- Berechnet: thermische Leistung roh/geglättet, Spreizung roh/geglättet, Unterkühlung und
  Heißgas-Überhitzung (nur im Heizbetrieb mit laufendem Verdichter, je neuem Außengeräte-Frame).

### 6.3 Gemeinsame Logik

- Glättung (Leistung, Spreizung): gleiches Verhalten wie die Komponenten (Nachführung höchstens alle
  10 s, auf 0,01 gerundet), neu umgesetzt.
- Abtauoptimierung, Verhalten wie heute: Bei Abtauen aus Heizen/Warmwasser in heizähnlichem Modus
  (Heizen, Absenken, Auto 1/2) auf „Sommer“ stellen und den Modus merken; nach dem Abtauen (→ Heizen,
  → Warmwasser, → Standby) den gemerkten Modus zurückstellen; beim Einschalten T-Frostschutz auf „Aus“
  setzen; jede andere Frostschutz-Einstellung schaltet die Optimierung ab. Der Schalter selbst übersteht
  Neustarts, der gemerkte Modus nicht (wie heute).
- Warmwasser bereiten: T-WW-Soll 1 auf 70 °C, nach der Bestätigung den alten Wert zurück.
- Wenn CAN und UART beide laufen, bleiben die Werte beider Busse getrennt erhalten (wie heute).

### 6.4 Diagnose je Knoten

Am Bridge-Gerät je ESP, Kategorie Diagnose: WLAN-Signal, IP, SSID, Laufzeit, freier Heap, größter
Block, Reset-Grund, Firmware-Version (ESPHome + Bridge), Verbindung (binary_sensor), Überläufe der
Puffer je Bus; mit CAN zusätzlich Busstatus, Sende-/Empfangsfehler, Arbitration lost, Bus-Off. Werte
aus `daikin_bridge_info`, abgefragt alle 60 s. „Schreibvorgänge heute“ gehört zum Gerät „Daikin CAN“.

## 7. Schreiben

Die RoCon legt per CAN geänderte Einstellungen vermutlich im EEPROM ab (begrenzte Schreibzyklen). Die
Integration schreibt wie die Komponente heute und sperrt nichts; ein Budget legt der Aufrufer fest
(z. B. eine übergeordnete Regelung).
- geschrieben wird nur bei echter Änderung (nach Rundung auf die Schrittweite bzw. den nächsten
  erlaubten Wert des Registers);
- danach sofort zurücklesen; der Zustand der Entity folgt der Rückmeldung der Wärmepumpe (nicht
  optimistisch);
- Schreibwünsche von HA gehen in dieselbe Warteschlange wie die Abfragen (Busruhe gilt auch für sie);
- Diagnose-Sensor „Schreibvorgänge heute“ am CAN-Gerät (Kalendertag in der HA-Zeitzone, Zeitpunkte im
  Store, übersteht Neustarts; Attribute: Anzahl je Entity).

Umsetzung (Teil 3):
- Ein Schreibauftrag geht der Abfrage vor; die Bridge bekommt den Schreib-Frame (Byte 0 = Ziel des
  Lesebefehls mit Art 0, Byte 1 = 0, übrige Datenbytes 0) zusammen mit dem Lesen desselben Registers.
  Bestätigt ist er durch die Antwort auf dieses Register, die nach dem Senden des Schreib-Frames
  eintrifft (mitgehört oder auf die eigene Anfrage).
- Der Dienstaufruf (number/select/switch) wartet auf diese Bestätigung. Fehler als
  `HomeAssistantError` mit übersetztem Text: nicht gesendet (`write_not_sent`), keine Rückmeldung
  nach 3 s (`write_not_confirmed`), anderer Wert gemeldet (`write_rejected`, mit dem gemeldeten Wert),
  Bus nicht verfügbar (`bus_unavailable`). Unerlaubte Werte: `ServiceValidationError`.
- Gezählt wird jeder tatsächlich gesendete Schreib-Frame: aus HA, aus der Logik (Abtauoptimierung,
  Warmwasser-Taste) und über `send_raw_can` (Attribut `raw`).
- Store `daikin_heat_pump_control.<entry_id>`: Zeitpunkte der Schreibvorgänge des Tages und der
  Schalter „Abtau-Optimierung“; wird mit dem Eintrag entfernt.
- `heating_curve_adaptation` (gelesen von 0x300) bleibt vorerst nur lesbar: die Komponente schreibt
  mit Byte 0 = 0x30 (Ziel 0x180), konsistent wäre 0x60 (Ziel 0x300). Wird am Ende mit der echten
  Anlage geprüft und dann umgesetzt (Teil 6).

## 8. Entities und Namen

- `has_entity_name`; Gerätenamen „Daikin CAN“ / „Daikin UART“ → neue IDs `sensor.daikin_can_<name>`,
  `sensor.daikin_uart_<name>`, gleich ob ein oder zwei ESPs; Diagnose am Bridge-Gerät
  `sensor.daikin_bridge_<esp-name>_<name>`.
- unique_id: `<entry_id>_<bus>_<schlüssel>` (Schlüssel = stabiler Name aus der Komponente, z. B.
  `tv`, `temperature_outside`).
- Zustände sprachunabhängig (HA-Standard):
  - Text-Sensoren → `sensor` mit Geräteklasse `enum`; Zustand ist ein Schlüssel (`heating`,
    `hot_water`, `defrosting`, Fehlercodes `e9001` …), Anzeige übersetzt. Zusatzbefunde des Fehlercodes
    als Attribut.
  - Auswahlen mit Text-Optionen (Betriebsmodus, SG-Modus, HK-Funktion, Gebäudedämmung …) → `select` mit
    übersetzten Optionen.
  - Einstellungen mit festen Zahlenwerten (Raumsoll 1–3, T-WW-Soll 1–3 …) → `number` mit
    Min/Max/Schritt; nicht erlaubte Werte werden auf den nächsten gültigen gerundet.
    Ausnahme: Wertelisten mit Text-Eintrag (T-Frostschutz, Heizgrenze Tag/Nacht, T_HK-Umschaltung,
    jeweils mit „Aus“) bleiben `select`; Optionen `off` und die Zahlenwerte, angezeigt mit Einheit.
  - Ein/Aus-Einstellungen (1× Warmwasser, Raumthermostat, Abtau-Optimierung …) → `switch`;
    Flüsterbetrieb hat drei Stufen (Aus/An/Nur nachts) und bleibt `select`.
- Kategorien: Hauptsteuerung ohne Kategorie (Betriebsmodus, Raumsoll 1–3, T-WW-Soll 1–3,
  1× Warmwasser, Flüsterbetrieb, SG-Modus), alle übrigen Einstellungen „Konfiguration“.
- Namen de/en/fr/it aus den Beispielen der CAN-Komponente, bereinigt (Umlaute, Sprachmischung,
  Schreibweise). HA bildet die entity_id aus dem Namen in der Systemsprache.
- Geräteklassen, Einheiten, Zustandsklassen und Genauigkeit korrekt gesetzt.

## 9. Wechsel der Firmware auf einem Knoten

Während der Tests wechselt der Nutzer zwischen Bridge-Firmware und bisheriger Firmware.
- Die Zuordnung eines Knotens hängt an seiner MAC-Adresse, nicht an der Firmware.
- Meldet ein zugeordneter Knoten keine Bridge-Aktionen (bisherige Firmware), werden die Entities seiner
  Busse `unavailable`, die Integration meldet das einmal im Log und als Repair-Issue
  („keine Bridge-Firmware“) und prüft bei jeder Wiederverbindung erneut.
- Sobald der Knoten wieder die Bridge-Firmware meldet, laufen die Busse ohne Zutun weiter; das
  Repair-Issue verschwindet.
- Die bisherigen ESPHome-Entities und die der Integration bestehen nebeneinander (unterschiedliche
  IDs: `hpsu_…` bzw. `daikin_…`), es gibt keine Konflikte.

## 10. Dashboard (Panel und Card)

- Logik neu in TypeScript/Lit, Build im Repo (`frontend-src/`, Ergebnis nach `frontend/`), mit Tests.
  Die drei SVG-Layouts des bisherigen Dashboards werden als Dateien übernommen und angepasst.
- Die Integration stellt das JS und die drei SVG-Layouts über einen statischen Pfad bereit und lädt das
  Modul im Frontend (`add_extra_js_url`) – die Card ist damit ohne Lovelace-Ressource verfügbar.
- **Panel** in der Seitenleiste (abschaltbar im Options-Flow), **Card** `custom:daikin-heat-pump-card`
  für eigene Dashboards; beide nutzen dieselbe Darstellung. Der Nutzer wählt, was er nutzt.
- Keine Entity-Zuordnung in Card oder Panel: alles Inhaltliche wird zentral in der Integration
  eingestellt, damit jede Ansicht dasselbe zeigt.
  - Bus-Werte automatisch: WebSocket-Befehl `daikin_heat_pump_control/entities` liefert Wert-ID →
    entity_id (unabhängig von Sprache und Umbenennungen), dazu die externen Werte und die Info-Box.
  - Wert-IDs nach Bedeutung, ohne Bus (`tv`, `tr`, `error_code`, `cop`, …); sie stehen in den
    SVG-Attributen `data-run-map`/`data-temp-vars` und in der WebSocket-Antwort, die Element-IDs der
    SVGs bleiben. Liefern CAN und UART denselben Wert, gilt CAN; UART nur, wenn es den Wert per CAN
    nicht gibt oder kein CAN eingerichtet ist (fest, keine Einstellung). Ausnahme wie im bisherigen
    Dashboard: TV, TVBH und TR zeigen in einer zweiten Zeile den UART-Wert (`tv_uart`, `tvbh_uart`,
    `tr_uart`), solange die erste Zeile von CAN kommt; sonst bleibt sie leer (kein Wert doppelt).
  - Externe Werte ohne Bus (COP, elektrische Leistung, Raum-Ist, Raum-Soll, Heißgas am Kondensator,
    Heizstab-Leistung): Options-Flow, Schritt „Dashboard“, je Wert ein Entity-Selector (Domain und
    Geräteklasse eingeschränkt).
  - Info-Box (welche Werte, Reihenfolge): ebenfalls im Options-Flow, Schritt „Dashboard“.
- Card-Editor nur für die Darstellung: Layout hell/dunkel/petrol oder automatisch nach Dark-Mode,
  Animationen an/aus, Hintergrund/Box/Text.
- Inhalt wie heute: Schema mit allen Werten, Info-Box, Animationen (Lüfter, Verdichter,
  Pumpe, Kältemittel- und Wasserfluss, 4-Wege-Ventil, Mischer/Bypass-Klappen), Farben nach Temperatur,
  Layouts hell/dunkel/petrol, Hintergrund/Box/Text anpassbar, Klick → More-Info.
- Logik über Zustandsschlüssel (`heating`, `cooling`, …) statt Texte, Anzeige über die HA-Übersetzung;
  Fehlercode rot bei Fehler; Texte de/en/fr/it.

Umsetzung (Teil 5):

- Wert-IDs: eine Datentabelle in Python (`dashboard.py`, Wert-ID → CAN-Schlüssel, UART-Schlüssel); „CAN
  zuerst“ ergibt sich daraus. Paare nach Bedeutung englisch benannt:

  | Wert-ID | CAN | UART |
  |---|---|---|
  | `temperature_outside` | `temperature_outside` (RoCon-Fühler) | `outdoor_temp` (Luftfühler Außengerät) |
  | `ta2` | `ta2` | – |
  | `tv` / `tr` / `tvbh` | `tv` / `tr` / `tvbh` | `tv` / `tr` / `tv_bh` |
  | `tv_uart` / `tr_uart` / `tvbh_uart` | – | `tv` / `tr` / `tv_bh`, nur wenn die erste Zeile von CAN kommt |
  | `target_supply_temperature` | `target_supply_temperature` | `supply_setpoint` |
  | `temperature_spread` | `temperature_spread` (geglättet; die rohe ist standardmäßig aus) | `temperature_spread` |
  | `thermal_power` | `thermal_power` (wie bisher geglättet) | `thermal_power` |
  | `flow_rate` / `circulation_pump` | `flow_rate` / `circulation_pump` | `flow_rate` / `circulation_pump` |
  | `pump_running` | `status_kesselpumpe` | `water_pump` |
  | `compressor_running` | `status_kompressor` | – |
  | `water_pressure` | `water_pressure` | – |
  | `hot_water_temperature` | `tdhw1` | `dhw_temp` |
  | `hot_water_setpoint` | `target_hot_water_temperature_1` | `dhw_setpoint` |
  | `dhw_mixer_position` / `bypass_valve` | `dhw_mixer_position` / `bypass_valve` | – |
  | `error_code` / `operating_mode` | `error_code` / `operating_mode` | – |
  | `mode_of_operating` | `mode_of_operating` | `mode_of_operating` |
  | `liquid_temperature` | `tliq` | `t_liq` |
  | `expansion_valve`, `four_way_valve`, `pressure_equalization`, `evaporator_temperature`, `hot_gas_temperature`, `discharge_superheat`, `subcooling`, `saturation_temperature`, `refrigerant_pressure`, `fan_speed`, `compressor_speed` | – | `exv`, `4_way_valve`, `press_eq`, `exch_temp`, `temp_after_compr`, `discharge_superheat`, `subcooling`, `saturation_temp`, `refrigerant_pressure`, `fan_speed`, `inv_freq` |

  Externe Werte: `cop`, `electric_power`, `room_temperature`, `room_setpoint`, `hot_gas_condenser`,
  `backup_heater_power`. Info-Box zur Auswahl: `error_code`, `operating_mode`, `mode_of_operating`,
  `thermal_power`, `electric_power`, `cop`, `room_temperature`, `room_setpoint` (Standard: alle, in
  dieser Reihenfolge).
- Quelle eines Werts: die CAN-Entity, wenn sie in der Registry steht und nicht deaktiviert ist
  (`hidden` zählt als vorhanden), sonst die UART-Entity unter derselben Bedingung, sonst fehlt der Wert
  in der Antwort und das Schema zeigt ihn nicht. Kein Umschalten zur Laufzeit: eine `unavailable`
  CAN-Entity bleibt die Quelle. Der Befehl liest die Registry bei jedem Aufruf; Card und Panel fragen
  beim Verbinden und bei `entity_registry_updated` neu an.
- WebSocket-Befehle (nur mit geladenem Eintrag, sonst Fehler `not_loaded`):
  - `daikin_heat_pump_control/entities` → `{"entities": {Wert-ID: entity_id}, "info": [Wert-IDs]}`
    (externe Werte sind in `entities` enthalten; `info` = gewählte Info-Zeilen in Reihenfolge);
  - `daikin_heat_pump_control/panel_config` → `{"config": {…}}` (Darstellung des Panels, leer = Standard);
  - `daikin_heat_pump_control/panel_config/set` (nur Admins) mit `config`; geprüft wie die
    Card-Darstellung.
- SVG-Layouts als `frontend/daikin_glass_{light,dark,petrol}.svg`: die Wert-Rechtecke tragen
  `data-value="<Wert-ID>"`, die Symbole mit More-Info `data-more-info="<Wert-ID>"`, `data-run-map` und
  `data-temp-vars` nennen Wert-IDs, das 4-Wege-Ventil vergleicht mit `heating`/`cooling`. Die zweite
  Zeile von Vorlauf, Vorlauf-BH und Rücklauf trägt `tv_uart`/`tvbh_uart`/`tr_uart`; fehlende Werte
  werden ausgeblendet. Ein Test prüft: jede Wert-ID kommt in jedem SVG vor und umgekehrt.
- Darstellung (Card und Panel gleich): Layout `auto` (Standard; hell/dunkel nach `hass.themes.darkMode`),
  `light`, `dark`, `petrol`; `animations` (Standard an; `false` hält alle Animationen an, das Layout
  pausiert sie über `svg[data-animations="off"]`); `background {show, color [r,g,b], opacity 0–100}`, `box {fill, fill_opacity,
  border, border_opacity}`, `text {value_color, label_color}`. Gespeichert werden nur Abweichungen vom
  Layout. Der Card-Editor (ha-form) bearbeitet genau diese Felder.
- Panel: `panel_custom.async_register_panel`, URL `daikin-heat-pump`, Icon `mdi:heat-pump`, Titel in
  der Systemsprache (`hass.config.language`: Wärmepumpe / Heat pump / Pompe à chaleur / Pompa di
  calore, sonst Heat pump; ändert sich erst nach Neuladen des Eintrags), `require_admin=False`.
  Registriert beim Einrichten des Eintrags, wenn die Option `show_panel` (Standard an) gesetzt ist,
  entfernt beim Entladen. Ein Zahnrad (nur Admins) öffnet den Card-Editor in einem Dialog; die
  Darstellung des Panels gilt für alle Nutzer und liegt im Store
  `daikin_heat_pump_control.<entry_id>.panel` (wird mit dem Eintrag entfernt).
- Bereitstellung: statischer Pfad `/daikin_heat_pump_control/frontend` (in `async_setup`, einmal je
  HA-Start), `add_extra_js_url` mit `frontend/daikin-heat-pump.js?v=<Manifest-Version>`; die SVGs werden
  neben dem Modul mit derselben Version geladen.
- Options-Flow: Einstieg ist ein Menü mit „Bus und Abfrage“ (bisheriges Formular) und „Dashboard“
  (`show_panel`, je externer Wert ein Entity-Selector mit Domain/Geräteklasse, Info-Box als
  `SelectSelector` mit `multiple` im Dropdown-Modus; Reihenfolge = Reihenfolge der Auswahl, weil
  core 2026.11 `reorder` im SelectSelector-Schema nicht erlaubt – offen: auf `reorder` umstellen,
  sobald core es erlaubt). Jeder Punkt speichert für sich und übernimmt die
  übrigen Optionen unverändert.
- Texte: Zustände, Optionen, Einheiten und Entity-Namen aus HA (`hass.formatEntityState` usw.); im
  Bundle (`frontend-src/src/translations/{de,en,fr,it}.json`) nur Schema-Beschriftungen,
  Info-Präfixe und die Texte von Editor und Panel. Sprache aus `hass.locale.language`
  (`de-CH` → `de`), Rückfall `en`.
- Build: Vite im Library-Modus, ein ES-Modul `frontend/daikin-heat-pump.js` ohne Hash, Lit
  mitgebündelt; Node-Version in `frontend-src/.nvmrc` und `package.json` (`engines`), Lockfile
  eingecheckt. CI-Job `frontend`: `npm ci`, Lint (ESLint, Prettier), Vitest, Build, danach
  `git diff --exit-code` auf `frontend/`.

## 11. Tests (ohne Hardware)

Grundsatz: so weit wie möglich gegen eine simulierte Wärmepumpe und simulierte ESPs; Mocks nur, wo
eine Simulation nicht möglich oder nicht sinnvoll ist (z. B. Zeroconf-Funde, Verbindungsfehler auf
Socket-Ebene).

Bausteine (unter `tests/sim/`, Teil des Repos):
- **Wärmepumpen-Simulator** (Python, ohne HA): bildet die RoCon am CAN (Register, Antworten der
  Teilnehmer 0x180/0x300/0x500, Schreiben mit Rückmeldung, RoCon-Bedienteil 0x10A, Betriebsarten
  einschließlich Abtauen und Warmwasser) und den UART (Protokoll I und S, Außengeräte-Varianten,
  NAK, Teilrahmen, Prüfsummenfehler) nach. Zustand und Fehler gezielt einstellbar.
- **Simulierter ESP** (Python): echter ESPHome-API-Server-Ersatz auf einem lokalen Port, spricht das
  native API-Protokoll mit Verschlüsselung, bietet die Bridge-Aktionen (Abschnitt 3) mit derselben
  Zeitregel (250 ms Busruhe, Ringpuffer, Überlauf) und hängt am Simulator. Ein, zwei oder ein
  kombinierter ESP (CAN + UART) sind möglich, ebenso „bisherige Firmware“ (nur Manifest-Aktion) für
  den Firmware-Wechsel. Die Integration verbindet sich damit über die echte aioesphomeapi – kein Mock
  der Verbindung.
- **Echte Bridge-Firmware auf der ESPHome-Host-Plattform** (Ende-zu-Ende, eigene Markierung, läuft
  nicht bei jedem Testlauf): dieselbe Bridge-YAML, nur die Bus-Anbindung ist ein Test-Package, das die
  Frames über einen lokalen Socket mit dem Simulator austauscht. Prüft Aktionen, Zeitregel und Puffer
  der echten Firmware. Umsetzung: CAN über UDP (Test-Komponente `tests/e2e/components/daikin_sim_can`),
  UART über ein Pseudo-Terminal (Host-UART von ESPHome); Markierung `e2e`, Aufruf `pytest -m e2e`.

Testebenen:
- Unit-Tests (ohne HA): CAN-Kodierung/-Dekodierung je Entity-Art, Planer (Intervalle, Busruhe,
  Zeitüberschreitung, Mithören), Schreiben (Änderung, Rundung, Rücklesen, Zähler), UART-Rahmen (I/S,
  Teilrahmen, CRC-Fehler, NAK, Erkennung), Konverter, Sättigung (Vergleich mit der bisherigen
  Tabelle), berechnete Werte, Glättung, Fehlererkennung, Abtauoptimierung – gegen den Simulator, wo es
  um Abläufe geht.
- Integrationstests mit `pytest-homeassistant` gegen simulierte ESPs: Config-Flow
  (Erkennung, Auswahl, bisherige Firmware; je ein ESP pro Bus und ein ESP mit beiden Bussen,
  Reconfigure), Entities, Schreiben, Wiederverbindung, Wechsel der Firmware (Abschnitt 9),
  WebSocket-API, Dienste, Diagnostics, Repairs, Entladen. Snapshot-Tests (syrupy) für Entities und
  Diagnostics. Zeit über `freezer`/`async_fire_time_changed`, kein `sleep`.
- Frontend: Unit-Tests der Zuordnung und Formatierung (Vitest), Darstellung gegen eine Mock-`hass`.
- Bridge-YAML: `esphome config` und Kompilierung (ESP32 und Host) im lokalen venv.
- Abdeckung ≥ 95 % für die Integration.

## 12. Qualität und Muster

Referenz für Muster und Regeln ist der aktuelle Stand von `~/git/ha/core` und `~/git/ha/frontend`
(dev, Version 2027.1); verwendet wird nur, was es in HA 2026.11 schon gibt (Mindestversion im
Manifest und in `hacs.json`).

Integration – Ziel Quality Scale **Platinum**, mit `quality_scale.yaml` im Repo und hassfest-Prüfung:
- `ConfigEntry[RuntimeData]` mit `entry.runtime_data` (typisiert), kein `hass.data`.
- Push statt Polling: eigener Koordinator je Bus (Werte kommen aus dem Bus, Entities abonnieren);
  `PARALLEL_UPDATES` je Plattform.
- Entity-Descriptions (dataclass, `kw_only`, `frozen`) aus der Entity-Tabelle; `has_entity_name`,
  `translation_key` für Namen, Zustände und Optionen, `icons.json` statt `icon=`, Geräteklasse,
  Kategorie, selten Genutztes `entity_registry_enabled_default=False`.
- Geräte mit `DeviceInfo`, `via_device`, veraltete Geräte/Entities werden entfernt (stale devices).
- Config-Flow mit Discovery (Zeroconf, ESPHome-Einträge), `unique_id` aus der MAC, Reconfigure- und
  Reauth-Flow (geänderter API-Schlüssel), Options-Flow; Test vor dem Einrichten.
- Fehler: `ConfigEntryNotReady`, `HomeAssistantError`/`ServiceValidationError` mit übersetzten Texten
  (`exception-translations`), Repairs für Firmware- und Verbindungsprobleme, einmaliges Log bei
  Nichterreichbarkeit und Wiederkehr.
- Dienste in `async_setup` registriert, `services.yaml` + Übersetzungen, Antwort über
  `SupportsResponse`.
- Diagnostics mit Schwärzung (API-Schlüssel, IP, SSID).
- Vollständig typisiert, `mypy --strict`, Ruff mit den Regeln von HA core, `py.typed`; asynchron
  ohne blockierende Aufrufe im Event-Loop; Abhängigkeit nur `aioesphomeapi` über `manifest.json`,
  als Mindestversion (`>=` die Version der ESPHome-Integration in 2026.11; hassfest verbietet eine
  feste Version für Pakete, die HA selbst mitbringt). Die ESPHome-Einträge werden nur gelesen, daher
  `after_dependencies: ["esphome"]` (keine harte Abhängigkeit, die ESPHome mit Bluetooth, Assist usw.
  mitlädt) und `dependencies: ["zeroconf"]` für die mDNS-Auflösung.
- Speicherung über `helpers.storage.Store` mit Versionen; Aufräumen über `entry.async_on_unload`.

Frontend:
- TypeScript strict, Lit 3, Web-Components wie im HA-Frontend (`ha-card`, `ha-form`,
  `ha-entity-picker`, `ha-selector`), Theme-Variablen, ESLint + Prettier, Build mit einem aktuellen
  Bundler (Vite/Rollup), Panel über `panel_custom`, Übersetzungen aus der Integration.

Werkzeuge: `pre-commit` (Ruff, mypy, Prettier, ESLint), GitHub-Actions für hassfest, HACS-Prüfung,
Tests und Frontend-Build.

## 13. Entscheidungen

| Punkt | Entscheidung |
|---|---|
| Zustände | übersetzte Schlüssel (HA-Standard) |
| Einheiten UART | korrigiert (L/h, bar) |
| Schreibschutz | nur bei Änderung + Zähler, keine Sperre |
| Zahlen-Selects | `number`; Ein/Aus-Selects → `switch`; Wertelisten mit „Aus“ bleiben `select` |
| Verlorene CAN-Anfrage | zählt als Versuch, erneut nach dem Intervall |
| Systemzeit | ein Zeitstempel-Sensor, standardmäßig aus |
| Abfrageintervalle | global + Gruppen Messwerte/Zustände/Einstellungen/Zähler |
| Heizprogramm 1 | vorerst nicht |
| Abtauoptimierung | Verhalten wie heute |
| Dampfdrucktabelle | CoolProp, feiner; Qualität mindestens gleich |
| Fehlersuche | Dienst, Log-Level, Diagnose statt Entities |
| Dashboard | SVG-Layouts übernehmen und anpassen, Card-/Editor-Logik neu |
| Präfix | `daikin`; Geräte „Daikin CAN“ / „Daikin UART“ / „Daikin Bridge <ESP>“ |
| Aufbau | ein ESP je Bus oder ein ESP mit beiden Bussen |
| Migration | vorerst keine; eigene Entities, bisherige bleiben unberührt |
| Tests | gegen simulierte Wärmepumpe und simulierte ESPs, Mocks nur wo nötig |
| Qualität | Quality Scale Platinum, Muster nach aktuellem HA core/frontend |
| Projektname der Firmware | `wrfz.daikin_can_bridge` / `wrfz.daikin_uart_bridge` / `wrfz.daikin_can_uart_bridge` |
| Firmware | kleine Komponente `daikin_bridge` (ohne Protokollwissen, registriert ihre Aktionen selbst) + vollständige Beispiel-YAMLs unter `examples/` |
| Einrichtung | ESPHome-Einträge, Zeroconf (gefiltert) und manuelle Eingabe; ein Eintrag, Knoten per MAC |
| Repo-Aufbau | Standard `custom_components/<domain>/`, Releases über Tags, kein Zip |
| Test-Umgebung | `pytest-homeassistant==2026.11.3` (offizieller Nachfolger von `pytest-homeassistant-custom-component`, das ab 2026.11 nicht mehr funktioniert) |
| Schreiben aus HA | Dienstaufruf wartet auf das Rücklesen, Fehler übersetzt |
| Zusatzbefunde Fehlercode | wie bisher: nur der erste, Attribut `finding` |
| Zähler Schreibvorgänge | alle gesendeten Schreib-Frames, auch Logik und `send_raw_can` |
| `send_raw_can` | erste passende Antwort (gleiches Register), höchstens 3 s |
| Heizkurvenadaption schreiben | zurückgestellt bis zum Test an der Anlage (Teil 6) |
| Durchfluss UART | 0x62 liefert l/min ×10; umgerechnet in L/h wie CAN |
| UART-Werte je Gerät | Geräteprofile als Daten: belegt → aktiv, unbelegt → angelegt und deaktiviert, fehlt → nicht angelegt |
| UART ohne Antwort | nach 3 Fehlschlägen nur noch alle 10 min, Werte `unavailable`, einmal Warnung |
| Dashboard-Konfiguration | zentral im Options-Flow (externe Werte, Info-Box); Card-Editor nur Darstellung |
| Wert-IDs Dashboard | nach Bedeutung ohne Bus (`tv`, `cop`); CAN vor UART, fest; deaktivierte Entity zählt als fehlend |
| TV/TVBH/TR im Dashboard | wie bisher beide Werte: CAN oben, UART in der zweiten Zeile (nur wenn oben CAN steht) |
| Panel | `daikin-heat-pump`, Titel in der Systemsprache, Darstellung im Store für alle Nutzer, Zahnrad nur Admins |
| Options-Flow | Menü „Bus und Abfrage“ / „Dashboard“, jeder Punkt speichert für sich |
| Reihenfolge Info-Box | Reihenfolge der Auswahl (SelectSelector `multiple`, Dropdown); `reorder`, sobald core es erlaubt (offen) |
| Frontend-Build | Vite, ein ES-Modul ohne Hash, `?v=<Version>`, Build eingecheckt und in CI geprüft |
| UART-Protokoll automatisch | Ergebnis gespeichert, einmal neu laden, nur passende Entities; neu erkennen bei Optionsänderung oder dauerhaftem Ausfall |
| Mehrere Clients | ein Master sendet, alle empfangen; Wechsel automatisch oder per Knopf im Dashboard; Option „Bevorzugter Master“ |

## 14. Umsetzung in Teilen (je Teil eine Session)

1. Grundgerüst (Werkzeuge, CI, Quality-Scale-Datei), Simulator und simulierter ESP, Bridge-Verbindung,
   Bridge-YAML, Config-Flow mit Erkennung, Diagnose je Knoten.
2. CAN: Protokoll, Entity-Tabelle, Planer, Mithören, Entities lesen (auch number/select/switch, die
   bis Teil 3 nur lesen), berechnete Werte mit Glättung, Systemzeit, Abfrageintervalle im Options-Flow.
3. CAN: Schreiben, Abtauoptimierung, Warmwasser-Taste, Zusatzbefunde des Fehlercodes, Dienst
   `send_raw_can`.
4. UART: Protokolle I/S, Erkennung, Konverter, Dampfdrucktabellen, Entities, Kältekreiswerte.
5. Frontend: gemeinsame Darstellung, Panel, Card, Editor, WebSocket-API.
6. README de/en, HACS, Feinschliff, Hardware-Inbetriebnahme durch den Nutzer; dabei Schreiben von
   `heating_curve_adaptation` an der Anlage prüfen (Ziel 0x180 oder 0x300) und umsetzen.
