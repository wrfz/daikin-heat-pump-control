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
Code und Kommentare englisch, README englisch + deutsch. Eine Wärmepumpe je HA-Instanz
(`single_config_entry`). Kein Code aus den Quellprojekten; die Protokolle werden neu umgesetzt.

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

Die Bridge-Firmware wird als ESPHome-YAML im Repo mitgeliefert: Packages `bridge-base`, `bridge-can`,
`bridge-uart` und daraus die Beispiele `daikin-can-bridge.yaml`, `daikin-uart-bridge.yaml` und
`daikin-can-uart-bridge.yaml` (beide Busse auf einem ESP). Bei beiden Bussen laufen die Aktionen
unabhängig voneinander (eigene Puffer, eigene Zeitregeln). Die Firmware enthält keine Sensoren für
HA; Diagnosewerte liefert sie über `daikin_bridge_info`. Eigene Erweiterungen des Nutzers (z. B. ein
Relais für Smart Grid) bleiben in seiner YAML und damit in der ESPHome-Integration. Die Firmware setzt
`esphome.project` zur Erkennung: `wrfz.daikin_can_bridge`, `wrfz.daikin_uart_bridge`,
`wrfz.daikin_can_uart_bridge` (in HA nur auf der ESPHome-Geräteseite als Hersteller/Modell sichtbar,
nicht in Entity-Namen).

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

Options-Flow: Knoten neu zuordnen, Außengerät/Protokoll, Abfrageintervalle (global und je Gruppe),
Offsets für die Fehlererkennung (`tv`, `tvbh`, `tr`), Grenzwerte der Spreizungsprüfung, Panel in der
Seitenleiste an/aus.

## 5. Paketaufbau

```
custom_components/daikin_heat_pump_control/
  __init__.py, manifest.json, config_flow.py, const.py, diagnostics.py, services.yaml,
  strings.json, translations/
  bridge/        Verbindung je Knoten (aioesphomeapi), exchange-Takt, Wiederverbindung
  can/           Frame-Kodierung, Entity-Tabelle (Daten), Abfrageplaner, Schreibwarteschlange
  uart/          Protokoll I/S, Erkennung, Rahmen-Parser, Konverter, Entity-Tabelle (Daten),
                 Dampfdrucktabellen (Daten)
  logic/         berechnete Werte, Glättung, Fehlererkennung, Abtauoptimierung, Warmwasser-Taste
  coordinator.py Zustand aller Werte, Verteilung an die Entities
  sensor.py, binary_sensor.py, number.py, select.py, switch.py, button.py
  websocket.py   API für Panel und Card
  frontend/      gebautes JS + SVG-Layouts (aus frontend-src/)
frontend-src/    TypeScript/Lit: Card, Panel, Editor, gemeinsame Darstellung
esphome/         Bridge-Firmware
scripts/         Erzeugung der Dampfdrucktabellen (nur Entwicklung)
tests/           pytest-homeassistant-custom-component, Protokoll-Simulator
design/          dieses Dokument
```

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
  Betriebsmodus 5 s), immer nur eine offene Anfrage, 250 ms Busruhe, verloren nach 3 s, das am längsten
  überfällige zuerst; `tv` mit `tv_max` intern alle 2 s.
- Mithören: Antworten an andere Teilnehmer und Schreib-/Antwort-Frames des RoCon werden dekodiert
  (Änderungen am Bedienteil kommen ohne eigene Abfrage an).
- Schreiben: Abschnitt 7.
- Fehlercode: Grundtext aus der Tabelle, ergänzt um die erkannten Zusatzbefunde (3-Wege-Ventil
  Warmwasser defekt, Bypassventil defekt, zu geringe Spreizung, fehlender Durchfluss) mit den Haltezeiten
  10/10/20/5 min und der Mindestspreizung abhängig von Tv.
- Fehlersuche ohne Entities: Dienst `daikin_heat_pump_control.send_raw_can` (1–7 Bytes, empfangene
  Antwort als Dienstantwort), Diagnose-Download mit allen Werten und Rohdaten, Log-Level über HA.

### 6.2 UART (nur lesen)

- 9600 8E1, Prüfsumme = Komplement der Byte-Summe.
- Protokoll I (`03 40 <reg> <crc>`, Antwort mit Längenbyte) und S (`02 <reg> <crc>`, feste Längen),
  automatische Erkennung wie die Komponente (Probe 0x60 I, dann 0x53 S, Rückfall I), NAK `15 EA`.
- Alle Entities (32 Schlüssel, 11 binär, 3 Text) mit den Varianten je Außengerät und S-Layouts;
  Konverter: Ganzzahl LE/BE, Bits, Nibble, Zieltemperaturen (/256 auf 0,1 abgeschnitten).
- Einheiten richtig: Durchfluss L/h, Kältemittel-/Hochdruck bar (bisher fälschlich °C).
- Sättigungstemperatur aus dem Kältemitteldruck (absolut = gemessen + 1,01325 bar), R32 bzw. R410A je
  Außengerät. Tabelle: zur Entwicklungszeit mit CoolProp (freie Stoffwert-Bibliothek, Referenz-
  Zustandsgleichungen) in 0,1-K-Schritten erzeugt (`scripts/`, Ergebnis als Datendatei, zur Laufzeit
  keine Abhängigkeit), linear interpoliert, Bereich −65…+71 °C. Ein Test vergleicht mit der bisherigen
  1-K-Tabelle: Abweichung höchstens so groß wie deren Interpolationsfehler. Ist CoolProp nicht nutzbar,
  wird die bisherige Tabelle als Daten übernommen.
- Abfrage: eine offene Anfrage, verloren nach 3 s, jedes Register 5 s nach der letzten gültigen
  Antwort erneut, das am längsten nicht gesendete zuerst.
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
  - Einstellungen mit festen Zahlenwerten (Raumsoll 1–3, T-WW-Soll 1–3, Heizgrenze Tag/Nacht …) →
    `number` mit Min/Max/Schritt; nicht erlaubte Werte werden auf den nächsten gültigen gerundet.
    Ausnahme: Wertelisten mit Text-Eintrag (z. B. T-Frostschutz mit „Aus“) bleiben `select`.
  - Ein/Aus-Einstellungen (1× Warmwasser, Raumthermostat, Flüsterbetrieb, Abtau-Optimierung …) →
    `switch`.
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
- Entities automatisch: WebSocket-Befehl `daikin_heat_pump_control/entities` liefert Schlüssel →
  entity_id (unabhängig von Sprache und Umbenennungen). Einzelne Werte lassen sich überschreiben
  (Card: in der Card-Konfiguration; Panel: gespeichert in der Integration über einen WebSocket-Befehl).
  Externe Werte ohne Bus (COP, elektrische Leistung, Raum-Ist, Raum-Soll, Heißgas am Kondensator,
  Heizstab-Leistung) nur über diese Zuordnung.
- Inhalt wie heute: Schema mit allen Werten, Info-Box (sortierbar), Animationen (Lüfter, Verdichter,
  Pumpe, Kältemittel- und Wasserfluss, 4-Wege-Ventil, Mischer/Bypass-Klappen), Farben nach Temperatur,
  Layouts hell/dunkel/petrol, Hintergrund/Box/Text anpassbar, Klick → More-Info.
- Logik über Zustandsschlüssel (`heating`, `cooling`, …) statt Texte, Anzeige über die HA-Übersetzung;
  Fehlercode rot bei Fehler; Layout optional automatisch nach Dark-Mode; Texte de/en/fr/it.

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
  der echten Firmware.

Testebenen:
- Unit-Tests (ohne HA): CAN-Kodierung/-Dekodierung je Entity-Art, Planer (Intervalle, Busruhe,
  Zeitüberschreitung, Mithören), Schreiben (Änderung, Rundung, Rücklesen, Zähler), UART-Rahmen (I/S,
  Teilrahmen, CRC-Fehler, NAK, Erkennung), Konverter, Sättigung (Vergleich mit der bisherigen
  Tabelle), berechnete Werte, Glättung, Fehlererkennung, Abtauoptimierung – gegen den Simulator, wo es
  um Abläufe geht.
- Integrationstests mit `pytest-homeassistant-custom-component` gegen simulierte ESPs: Config-Flow
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
  ohne blockierende Aufrufe im Event-Loop; Abhängigkeit nur `aioesphomeapi` (wie die ESPHome-
  Integration, gleiche Version) über `manifest.json` (`dependencies: ["esphome"]` für die Einträge).
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
| Zahlen-Selects | `number`; Ein/Aus-Selects → `switch` |
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

## 14. Umsetzung in Teilen (je Teil eine Session)

1. Grundgerüst (Werkzeuge, CI, Quality-Scale-Datei), Simulator und simulierter ESP, Bridge-Verbindung,
   Bridge-YAML, Config-Flow mit Erkennung, Diagnose je Knoten.
2. CAN: Protokoll, Entity-Tabelle, Planer, Mithören, Entities lesen.
3. CAN: Schreiben, Abtauoptimierung, Warmwasser-Taste, Fehlererkennung, Dienst `send_raw_can`.
4. UART: Protokolle I/S, Erkennung, Konverter, Dampfdrucktabellen, Entities, Kältekreiswerte.
5. Frontend: gemeinsame Darstellung, Panel, Card, Editor, WebSocket-API.
6. README de/en, HACS, Feinschliff, Hardware-Inbetriebnahme durch den Nutzer.
