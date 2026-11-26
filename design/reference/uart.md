# Referenz: bisherige UART-Komponente (Funktionsbeschreibung)

Ergebnis der Analyse der ESPHome-Komponente `daikin_rotex_uart` (Mount `~/mnt/hpsu_uart`,
`components/daikin_rotex_uart/` = C, HEAD `6dcb026` plus nicht committete Änderungen). Dient als
Spezifikation für die Neuumsetzung; kein Code übernehmen. Nur lesen, schreibt nie zur Wärmepumpe.

## 1. Protokoll

### 1.1 Leitung
9600 Baud, 8E1 (Parität EVEN in allen Beispielen, `examples/full_*.yaml:79-86`); TX und RX nötig
(`C/__init__.py:983-991`). X10A-Stecker auf der A1P-Platine, 5 V (`README.md:37-71`); Beispiele ATOM S3,
TX GPIO1, RX GPIO2.

### 1.2 Prüfsumme
`(~sum(bytes)) & 0xFF` über alle vorherigen Bytes (`C/request.cpp:19-25`). Testwerte
(`test/src/test_request.cpp:11-27`): `03 40 10` → `AC`, `03 40 61` → `5B`, `03 40 20` → `9C`,
leer → `FF`, S `02 54` → `A9` (`test/host/test_s_protocol.py:88`).

### 1.3 Protokoll I (übliche HPSU)
- Anfrage `03 40 <reg> <crc>` (`request.cpp:40-48`).
- Antwort `40 <reg> <len> <nutzdaten…> <crc>` (`MessageManager.cpp:207-256`); `len` zählt vom
  Registerbyte bis zur Prüfsumme → Gesamtlänge `2 + len`, Nutzdaten `len − 2`; Prüfsumme über
  `0 … (2+len−2)`. Nutzdaten-Offset 0 = Frame-Byte 3; alle Entity-Offsets relativ dazu.
- Prüfung in dieser Reihenfolge:
  1. Puffer beginnt mit `15 EA` → NAK, 2 Bytes verwerfen (`MessageManager.cpp:164-168`); Anfrage nicht
     beantwortet → Zeitüberschreitung.
  2. erstes Byte ≠ `0x40` → Puffer leeren (209-213).
  3. `len > 32` → Puffer leeren (218-222).
  4. weniger als `2+len` Bytes → warten (Antworten kommen in Stücken; Test teilt bei 7 Bytes).
  5. Prüfsumme falsch → Puffer leeren, Frame verwerfen; Anfrage nach Zeitüberschreitung wiederholt.
  6. Erfolg: alle aktiven Entities mit diesem Register gelten als beantwortet; dekodiert nur, wenn
     `offset + max(dataSize,1)` in die Nutzdaten passt (sonst einmal Warnung); Frame entfernen, Rest
     bleibt (234-247, 258-272).
- Zuordnung über das Registerbyte der Antwort, nicht über das angefragte (`test_uart.py:66-74`).
- Empfangspuffer 64 Bytes (`C/buffer.h:8`).

### 1.4 Protokoll S (ältere Geräte, z. B. RDLQ014AA6V3, RRLQ008BAV3)
- Anfrage `02 <reg> <crc>` (`request.cpp:28-38`).
- Antwort `<reg> <nutzdaten…> <crc>` mit fester Länge, ohne Längenbyte (`MessageManager.cpp:17-30`,
  274-313): 0x50 und 0x56: 6 Bytes; 0x53, 0x54, 0x55 und andere: 18 Bytes (16 Nutzdaten). Nutzdaten ab
  Byte 1.
- Prüfsummenfehler nur Warnung, Frame wird trotzdem genutzt (289-293). NAK wie bei I.
- Echter 0x55-Frame: `test/host/test_s_protocol.py:62`.

### 1.5 Protokollwahl und Erkennung
Option `protocol: I|S`, sonst automatisch (`protocol.h:8-42`, `MessageManager.cpp:77-101`, 177-205),
2000 ms je Probe:
1. I-Probe 0x60 `03 40 60 5C`: Antwort `15 EA` → S; Antwort beginnt mit `0x40` (≥ 3 Bytes) → I.
2. Nach 2 s ohne Antwort S-Probe 0x53 `02 53 AA`: erstes Byte 0x50/0x53/0x54/0x55/0x56 → S;
   `15 EA` → I.
3. Nach weiteren 2 s ohne Antwort → I.
Danach Puffer leeren, Anfragen neu aufbauen (`apply_protocol`, 36-67); Proben-Antworten werden nicht
dekodiert; keine erneute Erkennung bis zum Neustart. Tests `test_s_protocol.py:22-38`, 111-113.

### 1.6 Ablauf und Zeiten
- Ein Anfrageobjekt je Register der aktiven Entities (`MessageManager.cpp:39-67`; aktiv = konfiguriert,
  für das Außengerät erlaubt, Layout für das aktuelle Protokoll vorhanden).
- Je Schleife (`daikin_rotex_uart.cpp:103-118`): ggf. eine Anfrage senden, Bytes lesen und auswerten,
  berechnete Werte, Glättung.
- Nur eine offene Anfrage; von den fälligen die mit dem ältesten Sendezeitpunkt
  (`MessageManager.cpp:315-350`).
- Offen = gesendet, unbeantwortet, jünger als 3000 ms; danach verloren. Fällig = nicht offen und
  > 5000 ms seit der letzten gültigen Antwort (`request.cpp:51-73`); neue Objekte haben Antwortzeit 0 →
  erster Abruf ab > 5 s Laufzeit.
- Register ohne Antwort (z. B. 0x62 auf HPSU Compact 2013 mit RRLQ006CAV3, `__init__.py:848`) alle
  ~3 s erneut, abwechselnd mit den anderen (`test_uart.py:77-87`).
- Überlaufsichere Zeitrechnung (`utils.h:70-72`).

## 2. Entities

### 2.1 Fundort
`sensor_configuration` in `C/__init__.py:135-849`; berechnete Sensoren 912-964 (Verdrahtung 1113-1143);
`project_git_hash` 973-976.

### 2.2 Felder

| Feld | Bedeutung |
|---|---|
| `type` | `sensor` / `binary_sensor` / `text_sensor` |
| `name` | stabiler Schlüssel |
| `registryID` | I-Register; fehlt → nur S (`__init__.py:1094`) |
| `offset` | Byte-Offset in den Nutzdaten |
| `dataSize` | 1 oder 2; I Standard 0 (wie 1), S Standard 1 |
| `signed` | I Standard wahr, S Standard falsch |
| `endian` | LITTLE/BIG, Standard BIG; alle 2-Byte-Einträge LITTLE |
| `divider` | Wert = roh / Teiler; kann vom Außengerät abhängen (1038-1044) |
| HA-Metadaten | `accuracy_decimals`, `device_class`, `unit_of_measurement`, `state_class`, `icon`, `entity_category` |
| `handle_lambda` | eigene Umwandlung der Bytes ab Offset in 16 Bit |
| `map` | Zahl → Text |
| `update_entities` | auszulösende Berechnungen |
| `outdoor_units` / `not_outdoor_units` | nur für / nicht für diese Außengeräte (127-133) |
| `s` | Layout für Protokoll S; nicht gesetzte Felder werden geerbt, außer `map` und `handle_lambda` (1098-1108) |

Zwei Schlüssel haben zwei Varianten je Außengerät: `refrigerant_pressure`, `saturation_temp`.

### 2.3 Tabelle
Offsets = Nutzdaten-Offsets; LE s16 = vorzeichenbehaftet 16 Bit little endian, LE u16 = ohne Vorzeichen.

| Schlüssel | Art | I: Reg / Offset / Format | S: Reg / Offset / Format | Zeilen |
|---|---|---|---|---|
| outdoor_inv_compressors | sensor | 0x00 / 1 / u8 | – | 137-148 |
| outdoor_std_compressors | sensor | 0x00 / 2 / u8 | – | 149-160 |
| outdoor_fans | sensor | 0x00 / 3 / u8 | – | 161-172 |
| outdoor_expansion_valves | sensor | 0x00 / 4 / u8 | – | 173-184 |
| outdoor_4_way_valves | sensor | 0x00 / 5 / u8 | – | 185-196 |
| outdoor_crankcase_heaters | sensor | 0x00 / 6 / u8 | – | 197-208 |
| outdoor_solenoid_valves | sensor | 0x00 / 7 / u8 | – | 209-220 |
| indoor_units_max | sensor | 0x00 / 8 / u8 | – | 221-232 |
| indoor_units_connected | sensor | 0x00 / 9 / u8 | – | 233-244 |
| press_eq | binär | 0x10 / 1 / Bit 0x04 | – | 245-254 |
| defrost_operation | binär | 0x10 / 1 / Bit 0x10 | – | 256-266 |
| startup_control | binär | 0x10 / 1 / Bit 0x20 | – | 267-277 |
| tgt_evap_temp | sensor °C | 0x10 / 6 / besonders (3.2) | – | 278-296 |
| tgt_cond_temp | sensor °C | 0x10 / 8 / besonders (3.2) | – | 297-315 |
| outdoor_temp | sensor °C | 0x20 / 0 / LE s16 /10 | – | 317-331 |
| temp_after_compr | sensor °C | 0x20 / 4 / LE s16 /10 | – | 332-346 |
| exch_temp | sensor °C | 0x20 / 8 / LE s16 /10 | – | 347-361 |
| heat_sink_temp | sensor °C | 0x20 / 12 / LE s16 /10; nicht ERGA E | – | 362-378 |
| refrigerant_pressure (a) | sensor bar | 0x20 / 14 / LE s16 /10; nicht ERGA E | – | 379-393 |
| refrigerant_pressure (b) | sensor bar | 0x62 / 15 / LE s16 /10; nur ERGA E | – | 394-408 |
| saturation_temp (a) | sensor °C | 0x20 / 14 / Sättigung (3.3); nicht ERGA E | – | 409-425 |
| saturation_temp (b) | sensor °C | 0x62 / 15 / Sättigung; nur ERGA E | – | 426-442 |
| inv_prim_current | sensor A | 0x21 / 0 / LE s16 /10 | – | 444-457 |
| inv_sec_current | sensor A | 0x21 / 2 / LE s16 /10 | – | 458-471 |
| voltage | sensor V | 0x21 / 4 / LE s16 /1 | – | 472-485 |
| inv_freq | sensor rpm | 0x30 / 0 / u8 ×60 | – | 487-499 |
| fan_speed | sensor rpm | 0x30 / 1 / u8 ×10 oder ×100 (3.4) | – | 500-511 |
| exv | sensor „pls“ | 0x30 / 3 / LE u16 | – | 512-523 |
| 4_way_valve | Text | 0x30 / 7 / Bit 0x80 → 1 Heizen, 0 Kühlen (auch beim Abtauen); nicht ERGA E | – | 524-539 |
| mode_of_operating | Text | 0x60 / 2 / High-Nibble, Tabelle 0-6 | 0x55 / 0 / u8, Tabelle 0-0x12 | 541-586 |
| thermostat | binär | 0x60 / 2 / Bit 0x08 | – | 587-597 |
| dhw_setpoint | sensor °C | 0x60 / 7 / LE s16 /10 | – | 598-613 |
| supply_setpoint | sensor °C | 0x60 / 9 / LE s16 /10 | – | 614-628 |
| flow_switch | binär | 0x60 / 11 / Bit 0x80 | – | 629-639 |
| water_pump | binär | 0x60 / 12 / Bit 0x02 | – | 640-650 |
| 3_way_valve | Text | 0x60 / 12 / Bit 0x40 → 1 Warmwasser, 0 Heizen | – | 651-665 |
| buh1 | binär | 0x60 / 12 / Bit 0x10 | – | 666-675 |
| buh2 | binär | 0x60 / 12 / Bit 0x08 | – | 676-685 |
| buh_bsh | binär | 0x60 / 12 / Bit 0x20 | – | 686-695 |
| tv | sensor °C | 0x61 / 2 / LE s16 /10 | 0x54 / 4 / LE u16 /256 | 697-717 |
| tv_bh | sensor °C | 0x61 / 4 / LE s16 /10 | – | 718-731 |
| t_liq | sensor °C | 0x61 / 6 / LE s16 /10 | 0x54 / 0 / LE u16 /256 | 732-751 |
| tr | sensor °C | 0x61 / 8 / LE s16 /10 | 0x54 / 2 / LE u16 /256 | 752-772 |
| dhw_temp | sensor °C | 0x61 / 10 / LE s16 /10 | 0x54 / 8 / LE u16 /256 | 773-792 |
| circulation_pump | binär | 0x62 / 8 / Bit 0x04 | 0x53 / 0 / Byte > 0 | 794-808 |
| dhw_priority | binär | – (nur S) | 0x53 / 5 / Byte > 0 | 809-818 |
| flow_rate | sensor (bisher fälschlich °C; L/h) | 0x62 / 9 / LE s16 /10 | – | 819-832 |
| discharge_pressure | sensor (bisher fälschlich °C; bar) | 0x62 / 15 / LE s16 /10 | – | 833-846 |

ERGA-E-Geräte = ERGA04EAV3, ERGA06EAV3, ERGA08EAV3, ERGA08EAV3H (`:107-110`): kein Kältemitteldruck in
0x20, kein 4-Wege-Ventil in 0x30. `discharge_pressure` liest dieselben Bytes wie
`refrigerant_pressure (b)` ohne Filter. Auf S haben nur tv, t_liq, tr, dhw_temp, mode_of_operating,
circulation_pump, dhw_priority ein Layout; abgefragt werden nur 0x53, 0x54, 0x55.

Anzahl: 34 Tabellen-Sensoren (32 Schlüssel), 6 berechnete (thermal_power, thermal_power_raw,
temperature_spread, temperature_spread_raw, subcooling, discharge_superheat), 11 binär, 3 Text +
`project_git_hash`.

## 3. Umwandlung

### 3.1 Allgemein (`C/entity.cpp:21-41`, `sensors.cpp:28-51`)
Rohwert: Lambda, sonst Byte bzw. LE/BE 16 Bit. Lambda-Ergebnis 0x8000 → unbekannt. Signed: als int16,
dann / Teiler; 1-Byte-„signed“ wird nicht erweitert. Binär: roh > 0. Text: Tabelle des aktiven
Protokolls, sonst `INVALID<n>` (dezimal); hat nur ein Protokoll eine Tabelle, gilt sie für beide.

### 3.2 Bits, Nibble
Bit: `(Byte & Maske) != 0`. `mode_of_operating` (I): `Byte >> 4`. `tgt_evap_temp`/`tgt_cond_temp`:
LE u16; 0x8000 → 0 (also 0,0 °C, nicht unbekannt); sonst Zehntel = trunc(int16(roh) / 2,56), dann /10
(≈ roh/256 auf 0,1 abgeschnitten). Test: 18,7 °C ↔ roh 479 (`conftest.py:92`).

### 3.3 Sättigungstemperatur (`__init__.py:115-125`, `C/unit_converter.cpp:6-313`)
Druck bar(g) = int16 LE / 10; + 1,01325 → bar(a); lineare Interpolation in einer Tabelle des
Sättigungsdrucks je ganzem °C von −65 bis +71 °C (R410A `:7-145`, R32 `:147-285`): erste Zeile mit
Druck ≥ p, zwischen ihr und der vorigen interpolieren (`:287-303`). R32 für ERGA04/06/08EAV3,
ERGA08EAV3H, ERGA08DAV3, RRGA08DAV3, sonst R410A. Außerhalb → unbekannt; Ergebnis auf 0,1 gerundet.
Prüfwerte: 18,0 bar(g) → 30,2 °C (R410A), 29,5 °C (R32) (`test_uart.py:192-196`, `test_erga_e.py:46-47`);
48 bar(g) → unbekannt (`test_uart.py:236-246`).

### 3.4 Teiler je Außengerät
`inv_freq` ×60 (Test 58 → 3480). `fan_speed` ×100 für RRLQ011CAW1, ERLQ016CAW1, ERGA08DAV3, RRGA08DAV3,
sonst ×10 (`__init__.py:88-105`).

### 3.5 Texttabellen
- `mode_of_operating` I (`:549-557`): 0 Standby, 1 Heizen, 2 Kühlen, 3 „???“, 4 Warmwasser,
  5 Heizen+Warmwasser, 6 Kühlen+Warmwasser.
- `mode_of_operating` S (`:564-584`): 0 nur Lüfter, 1 Heizen, 2 Kühlen, 3 Auto, 4 Lüftung, 5 Auto
  Kühlen, 6 Auto Heizen, 7 Entfeuchten, 8 Zusatz, 9 Kühlspeicher, 0x0A Wärmespeicher, 0x0B-0x0E
  „UseStrdThrm(cl)1…4“, 0x0F-0x12 „UseStrdThrm(ht)1…4“.
- `4_way_valve`: 0 Kühlen (auch beim Abtauen), 1 Heizen. `3_way_valve`: 0 Heizen, 1 Warmwasser.

## 4. Ablauf
Kein `update_interval`; eine Anfrage, verloren nach 3 s, jedes Register 5 s nach der letzten gültigen
Antwort, nächstes = ältester Sendezeitpunkt. I (voll): 0x00, 0x10, 0x20, 0x21, 0x30, 0x60, 0x61, 0x62
(0x62 nur bei konfigurierter 0x62-Entity); S: 0x53, 0x54, 0x55. Das Innengerät übernimmt neue Werte
vom Außengerät nur alle 15–20 s und wiederholt 0x20 dazwischen; 0x62 (ERGA E) ist alle 5 s frisch
(`daikin_rotex_uart.cpp:212-215`). Geglättete Sensoren höchstens alle ~10 s.

## 5. Berechnete Werte

### 5.1 Auslöser
Nach jedem dekodierten Wert werden die `update_entities` eingeplant und am Ende des Frames ausgeführt.
„Geändert“ ist praktisch immer wahr (Vergleich mit nie gesetztem 0,0). Auslöser: `outdoor_temp`,
`temp_after_compr`, `exch_temp`, `heat_sink_temp`, `saturation_temp` → Kältekreis;
`defrost_operation`, `inv_freq`, `4_way_valve` → Kältezustand; `tv`, `tr` → Leistung und Spreizung.

### 5.2 Spreizung: `tv − tr`, roh direkt, geglättet (intern immer berechnet).
### 5.3 Leistung: nur mit `flow_rate`; kW = (tv − tr) × 4,19 × flow_rate / 3600; roh und geglättet.
### 5.4 Glättung: wie CAN (`sensors.cpp:53-75`, `C/pid.cpp:11-54`), Kp 0,2, Ki 0,05, Kd 0,05,
Integral ±0,2, αP 0,2, αD 0,1, höchstens alle 10 s, auf 0,01 gerundet.

### 5.5 Unterkühlung, Heißgas-Überhitzung (`daikin_rotex_uart.cpp:187-282`)
Nur bei Heizen mit laufendem Verdichter, geprüft in dieser Reihenfolge:
1. `inv_freq` vorhanden und nicht > 0 → nein; 2. `defrost_operation` vorhanden und an → nein;
3. `4_way_valve` vorhanden → ja nur bei „Heizen“; 4. sonst `mode_of_operating` = Kühlen (0x02) → nein;
5. sonst ja.
Kältezustand (238-250): Wechsel auf Heizen → aktuellen „0x20-Fingerabdruck“ (outdoor_temp,
temp_after_compr, exch_temp, heat_sink_temp, saturation_temp) merken; nicht Heizen → beide unbekannt.
Kältekreis (257-282): erst Kältezustand; bei Heizen und neuem Fingerabdruck (NaN = NaN gilt gleich):
merken, Unterkühlung = saturation_temp − t_liq, Überhitzung = temp_after_compr − saturation_temp
(fehlender Eingang → unbekannt). Also ein Wert je neuem Außengeräte-Frame, nach Start/Abtauen erst beim
nächsten neuen Frame. Einheit K ohne Geräteklasse. Tests `test_uart.py:185-246`, `test_erga_e.py:68-100`.

### 5.6 Manifest
API-Aktion `rotex_uart_manifest(page)` (`C/manifest.py`), Kopf `id: "rotex_hpsu_uart"`; dient der
Erkennung „bisherige Firmware“.

## 6. Übersetzungen
de, en, it, je 15 Schlüssel (standby, heating, cooling, hot_water, heating_hot_water,
cooling_hot_water, fan_only, auto, ventilation, auto_cool, auto_heat, dry, aux, cooling_storage,
heating_storage), nur für Text-Zustände; Namen aus der YAML.

## 7. YAML-Optionen (`__init__.py:966-981`)
`uart_id`, `outdoor_unit` (Pflicht, einer von 13: RRLQ004CAV3, RRLQ006CAV3, RRLQ008CAV3, RRLQ011CAW1,
ERLQ016CAW1, ERGA04EAV3, ERGA06EAV3, ERGA08DAV3, ERGA08EAV3, ERGA08EAV3H, RRGA08DAV3, RRLQ008BAV3,
RDLQ014AA6V3), `language`, `protocol` (optional), `project_git_hash`, `entities`. Wirkung des
Außengeräts: Lüfterfaktor, Kältemittel-Tabelle, ERGA-E-Varianten (Druck/Sättigung aus 0x62 Byte 15-16,
ohne `heat_sink_temp` und `4_way_valve`).

## 8. Prüfdaten (echte Frames)
`test/host/conftest.py:88-108` (Standard), `test/host/test_uart.py:90-93` (0x30 Heizen/Abtauen, 0x21),
`test/host/test_uart.py:139-144` (0x60, 0x10, 0x20), `test/host/test_erga_e.py:11-16`,
`test/host/test_s_protocol.py:62`; erwartete Werte in den Asserts derselben Dateien.
