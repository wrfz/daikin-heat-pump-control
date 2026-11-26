# Referenz: bisherige CAN-Komponente (Funktionsbeschreibung)

Ergebnis der Analyse der ESPHome-Komponente `daikin_rotex_can` (Mount `~/mnt/hpsu_can`,
`components/daikin_rotex_can/`, Branch `main`, Stand `27a0042`). Dient als Spezifikation für die
Neuumsetzung; kein Code übernehmen. Pfade relativ zu `components/daikin_rotex_can/`, sofern nicht anders
angegeben. Zeilenangaben können bei neuen Commits abweichen.

## 1. Protokoll

### 1.1 Bus und IDs
- 20 kbit/s, Standard-IDs (11 Bit). Beispiele: `canbus: esp32_can, can_id: 0x680, bit_rate: 20kbps`
  (`examples/full_de.yaml:185-191`).
- Jeder vom ESP gesendete Frame nutzt die ID 0x680 (Abfragen `entity.cpp:170`, Schreiben
  `entity.cpp:193`, eigene Anfragen `daikin_rotex_can.cpp:405`). Die ID ist die Adresse des Senders.
- Ziel und Art stehen in Byte 0: High-Nibble × 0x80 = Empfänger, Low-Nibble = Art (`0` schreiben,
  `1` lesen, `2` Antwort). Der Simulator im Repo bestätigt das: Antwort-ID folgt der Anfrageart
  (0x31 → 0x180, 0x61 → 0x300, 0xA1 → 0x500; `test/host/components/hpsu_sim/hpsu_sim.cpp:108-109`).

| Lese-Präfix (Byte 0) | antwortende ID | genutzt für |
|---|---|---|
| `0x31` | 0x180 (Standard `can_id`, `__init__.py:2220`) | fast alle Entities (Hauptregler) |
| `0x61` | 0x300 | `t_ext`, `t_room`, `heating_curve_adaptation` (`__init__.py:367,382,1459`) |
| `0xA1` | 0x500 | `status_kompressor`, `bivalence_function`, `bivalence_temperature` (`__init__.py:1148,1390,1406`) |
| – | 0x10A | RoCon-Bedienteil, nur mitgehört |

- Der Simulator antwortet mit Byte 0 = `0xD2` (Empfänger 0x680, Art Antwort), `hpsu_sim.cpp:11,105`.
- Byte 1 ist in Anfragen immer `0x00`; beim Schreiben wird es auf `0x00` gesetzt (`entity.cpp:198`).

### 1.2 Frame-Aufbau (immer 7 Datenbytes, `types.h:9`)
- Langes Register: Byte 2 = `0xFA`, Byte 3–4 = 16-Bit-Registernummer, Daten in Byte 5–6.
  Beispiel `31 00 FA C0 FC 00 00`.
- Kurzes Register: Byte 2 ist das Register, Daten in Byte 3–4. Beispiel `31 00 02 00 00 00 00`.
- Befehlstext wird als Hex-Tokens gelesen (`utils.cpp:75-104`), fehlende Bytes werden `00`
  (5-Byte-Befehle wie `31 00 FA C1 05` sind gültig). Nicht-Hex-Zeichen werden verworfen
  (`building_insulation` hat `"OC"` mit dem Buchstaben O, `__init__.py:166` – funktioniert nur, weil
  „O“ wegfällt → `0x0C`).

### 1.3 Zuordnung empfangener Frames
- Maske (`entity.cpp:72-83`): bei `FA`-Befehl müssen Byte 2, 3, 4 gleich sein, sonst nur Byte 2.
  Byte 0 wird nicht verglichen.
- Annahme (`entity.cpp:89-107`), wenn die Maske passt und entweder die CAN-ID gleich der `can_id` der
  Entity ist (Art egal) oder die CAN-ID 0x10A ist mit Art 0 (setzen) oder 2 (Antwort). Leseanfragen des
  RoCon (Art 1) werden ignoriert.
- Die Entity-Liste wird in Tabellenreihenfolge durchsucht, der erste Treffer gewinnt
  (`entity_manager.cpp:209-221`). Frames kürzer als 7 Bytes werden verworfen
  (`daikin_rotex_can.cpp:559-566`). Unpassende Frames: Log „unhandled“.

### 1.4 Dekodierung
- Rohwert (`entity.cpp:115-123`): Größe 2 → big-endian `(b[off] << 8) + b[off+1]`, Größe 1 → `b[off]`;
  ein `handle_lambda` ersetzt das und liefert uint16.
- Sensor/Zahl (`sensors.cpp:32-76`, `140-150`): `raw / divider` bzw. `int16(raw) / divider` bei
  `signed` (Vorzeichen nur für 16 Bit).
- Bereich `range: [min, max]` (`sensors.h:21-27`, `sensors.cpp:51,70-73`): Werte außerhalb werden nicht
  veröffentlicht und lösen keine abhängigen Werte aus. `[0, 0]` = kein Bereich.
- `no_value`: `total_electrical_energy` hat `no_value: 0x8000` (`__init__.py:599`) → unbekannt
  (`sensors.cpp:33-41`).
- Text-Sensor: genauer Treffer in der Tabelle, sonst `INVALID<0x%04X>` (`sensors.cpp:111-117`).
- Select: nächster Tabellenschlüssel nach Betrag des Abstands (`bidi_map.cpp:11-29`,
  `sensors.cpp:181-186`).
- Binär/Schalter: an, wenn `raw > 0` (`sensors.cpp:121-126`, `199-204`).
- Tabellenschlüssel sind auf den Rohwert skaliert: Python-Schlüssel × Teiler, `& 0xFFFF`
  (`__init__.py:2092`). Beispiel `temperature_antifreeze` (Teiler 10): −4 → `0xFFD8`, „Aus“
  (`0xFF60/10.0`) → `0xFF60`.

### 1.5 Schreiben (`entity.cpp:187-215`)
1. Befehl kopieren, Byte 0 = `0x30`, Byte 1 = `0x00`.
2. `raw = uint16(int32(lround(skalierter Wert)))` (gerundet, negativ als Zweierkomplement).
3. `raw` an `data_offset` (Größe 1: Low-Byte; Größe 2: big-endian; `utils.cpp:136-145`) oder
   `set_lambda`.
4. Auf 0x680 senden, danach sofort Lesen desselben Registers.

Besonderheiten:
- Schreiben geht immer mit Byte 0 = `0x30` (Ziel 0x180), auch für 0x300-Entities. Einzige schreibbare
  davon: `heating_curve_adaptation` (Befehl `61 00 FA 01 15`).
- Skalierung je Art: Zahlen senden `Wert × Teiler` (`sensors.cpp:136`), Selects den Rohschlüssel
  (`sensors.cpp:164`), Schalter 0/1 (`sensors.cpp:195`); interne Logik `sendSet` (skaliert) bzw.
  `sendSetRaw` (`entity_manager.cpp:181-207`).

### 1.6 Beispiele

| Entity (`__init__.py`) | Lesen auf 0x680 | Antwort | Dekodierung | Schreiben |
|---|---|---|---|---|
| `tv` (670-684) | `31 00 FA C0 FC 00 00` | 0x180: `D2 00 FA C0 FC 01 2C` | Byte 5-6 = 300 /10 = 30,0 °C; Bereich 1..90 | – |
| `temperature_outside` (318-331), signed | `31 00 FA C0 FF 00 00` | `.. FA C0 FF FF CE` | int16 −50 → −5,0 °C | – |
| `max_target_flow_temp` (963-978), kurz | `31 00 28 00 00 00 00` | `.. 00 28 01 22 ..` | Offset 3: 290 → 29,0 °C | 29,0 → `30 00 28 01 22 00 00`, dann Lesen |
| `water_pressure` (416-427) | `31 00 1C 00 00 00 00` | Offset 3, Größe 2 | /1000 bar | – |
| `temperature_antifreeze` Select (657-669) | `31 00 FA 0A 00` | `FF 60` = Aus, `FF D8` = −4 °C | nächster Schlüssel | −4 °C → `30 00 FA 0A 00 FF D8` (`test/host/test_optimized_defrosting.py:22-23`) |
| `operating_mode` Select (1046-1062) | `31 00 FA 01 12 00 00` | Offset 5, Größe 1 | 0x01 Standby, 0x03 Heizen, 0x04 Absenken, 0x05 Sommer, 0x11 Kühlen, 0x0B Auto 1, 0x0C Auto 2 | Sommer → `30 00 FA 01 12 05 00` |
| `status_kompressor` (1144-1152) | `A1 00 61 00 00 00 00` | 0x500, Byte 2 = 0x61, Daten Byte 3 | > 0 = an | – |
| `1_dhw` Schalter (90-98) | `31 00 FA 01 44 00 00` | Offset 6, Größe 1 | bool | an → `30 00 FA 01 44 00 01` |

Sonderkodierungen:
- `power_dhw`, `power_ehs_1`, `power_ehs_2`, `power_biv` (1235-1323): Lesen `u16 / 100` kW,
  Schreiben `kW × 100` in Byte 5-6.
- `electric_heater` Select (1324-1353): Lesen Bits 3, 2, 1 von Byte 5 je +3 kW (0/3/6/9). Schreiben
  Byte 5 = `0x01` plus Bit 3 ab 3, Bit 2 ab 6, Bit 1 ab 9.
- `external_temp_sensor` (1161-1171): an, wenn `Byte 6 == 0x05`.

## 2. Entity-Katalog

### 2.1 Fundort
- `__init__.py:90-1717` (`sensor_configuration`, 110 Einträge). Hilfen 71-87: `temp_map`, `room_map`
  (15–25 in 1-K-Schritten plus 19,5–23,5 in 0,5 K), `dhw_map` (35–70 in 5 K plus 45–55 in 1 K).
- Maschinell lesbar: Zeilen 71-1717 ausführen mit Platzhaltern für `DEVICE_CLASS_*`, `UNIT_*`,
  `STATE_CLASS_*` (aus `esphome.const`), `UNIT_BAR`/`UNIT_LITER_*` (48-50),
  `ICON_SUN_SNOWFLAKE_VARIANT` (63) und `delayed_translate(key)` → `"DELAYED_TRANSLATE:"+key`
  (`translations/translate.py:73-74`).
- Berechnete und Zusatz-Entities: `__init__.py:1851-1932`; Abhängigkeiten 1935-1957; YAML-Schema
  1977-2018; Code-Erzeugung mit Standardwerten 2080-2237.

### 2.2 Felder (Standardwerte aus `__init__.py:2214-2236`)

| Feld | Bedeutung / Standard |
|---|---|
| `type` | `sensor`, `text_sensor`, `binary_sensor`, `select`, `number`, `switch` |
| `name` | stabiler Schlüssel, auch interne ID |
| `can_id` | erwarteter Antwortender; Standard 0x180 |
| `command` | Hex-Text der Leseanfrage; leer = virtuelle Entity |
| `data_offset` | Standard 5 |
| `data_size` | 1 oder 2; Standard 1 |
| `divider` | Standard 1,0 |
| `signed` | Standard falsch |
| `map` | Rohwert → Text (Übersetzungsschlüssel) |
| `range` | Plausibilität `[min, max]` |
| `no_value` | Rohwert für „unbekannt“ |
| `update_entities` | bei Änderung neu zu berechnende Werte |
| `handle_lambda` / `set_lambda` / `update_lambda` | eigene Dekodierung / Kodierung / Zusammensetzung |
| `min_value` / `max_value` / `step` | Grenzen für Zahlen (Pflicht, `__init__.py:2127-2132`) |
| HA-Metadaten | `device_class`, `unit_of_measurement`, `accuracy_decimals`, `state_class`, `icon` |

Die erwartete Antwort wird aus `command` berechnet (`entity.h:146-150`, `entity.cpp:72-83`).

### 2.3 Anzahl

| Art | Anzahl | Hinweis |
|---|---|---|
| sensor | 34 | davon 6 Datum-/Zeit-Teile |
| number | 45 | YAML `type: number` (Standard, Modus BOX) oder `type: select` mit `options` (`__init__.py:1820-1849`) |
| select | 14 | |
| switch | 7 | standardmäßig als Select „Aus/An“, außer YAML `type: switch` (`__init__.py:1802-1819`); `optimized_defrosting` virtuell |
| text_sensor | 5 | `system_time`/`system_date` über `update_lambda` |
| binary_sensor | 5 | |

Außerhalb der Tabelle: 8 berechnete Sensoren (`thermal_power`, `thermal_power_raw`,
`temperature_spread`, `temperature_spread_raw`, `tv_tvbh_delta`, `tvbh_tr_delta`,
`vorlauf_soll_tv_delta`, `tv_max`), Tasten `dhw_run` und `dump`, Zahl `supply_setpoint_regulated`
(20–90, 0,1), Texte `log_filter`, `custom_request`, Text-Sensor `project_git_hash`.

### 2.4 Intervalle
- Standard 30 s (`__init__.py:1753`), je Entity per `update_interval` änderbar (2173-2181);
  Schalter-Einträge haben keine eigene Einstellung (immer global).
- `tv` mit `tv_max`: Abfrage alle `min(Intervall, 2000 ms)`, Veröffentlichung im Intervall
  (`__init__.py:1746-1747,2183-2188`).
- `full_de.yaml`: `flow_rate` 10 s, `operating_mode` 5 s, `tv`/`tvbh`/`tr` 30 s.

## 3. Abfrage

### 3.1 Hauptschleife (`daikin_rotex_can.cpp:488-501`)
1. höchstens ein Frame senden; 2. interne Zeitplanung; 3. `update()` aller Entities (Glättung);
4. Vorlauf-Regelung (nicht übernommen).

### 3.2 Auswahl des nächsten Frames (`entity_manager.cpp:165-179`, `241-263`)
1. Schreibwünsche der Logik zuerst (FIFO), wenn die Ruheregel es erlaubt.
2. Ruheregel: mindestens `delay_between_requests` (Standard 250 ms) seit `m_last_handle`; dieser
   Zeitpunkt wird bei **jedem empfangenen Frame** (passend oder nicht) und jedem Schreiben gesetzt,
   nicht beim Abfragen (`entity_manager.h:87-89`, `entity_manager.cpp:202,217`) → 250 ms Busruhe.
3. Immer nur eine offene Anfrage: offen, wenn nach dem letzten Treffer gesendet und jünger als 3 s
   (`entity.cpp:85-87`).
4. Vorrang: von den fälligen Entities (nie beantwortet oder letzter empfangener Wert älter als das
   Intervall, `entity.h:223-230`) die am längsten überfällige (`entity.h:232-240`).

### 3.3 Zeitüberschreitung
Nach 3 s gilt eine Anfrage als verloren; kein Zähler, die Entity bleibt fällig und wird erneut
angefragt (Warnung, `entity.cpp:173-176`).

### 3.4 Mithören
Alle Frames werden empfangen (`daikin_rotex_can.h:145-154`). Dekodiert werden Frames der Antwortenden
0x180/0x300/0x500 mit passendem Register, egal wer gefragt hat (z. B. das RoCon), und Setz-/Antwort-
Frames des RoCon 0x10A – so kommen Änderungen am Bedienteil an (`entity.cpp:89-96`;
`test/host/test_optimized_defrosting.py:76-83`). Jeder Treffer erneuert den Zeitstempel der Entity und
verschiebt ihre nächste Abfrage.

### 3.5 Schreibwege
- Von HA: `CanNumber::control`, `CanSelect::control`, `CanSwitch::write_state` schreiben direkt, an der
  Warteschlange und der Ruheregel vorbei.
- Interne Logik (Abtauen, `dhw_run`, Regelung): über die Warteschlange, wenn die Ruheregel nicht erfüllt
  ist (`entity_manager.cpp:189-194`).
- Nach jedem Schreiben sofort Lesen desselben Registers (`entity.cpp:212`).

### 3.6 Interne Zeitplanung (`scheduler.cpp/.h`)
`call_later(fn, ms)` mit Abbruch und Vorziehen; fällige Aufrufe werden erst entnommen, dann
ausgeführt. Reaktionen auf Änderungen laufen in der nächsten Schleife: je Eintrag in
`update_entities` neu berechnen (`daikin_rotex_can.cpp:153-161`), Handler für Betriebsart/-modus. Nur
bei Wertänderung (`entity.cpp:131-138`).

## 4. Schreibschutz
Keiner. Nur Änderungsprüfung: Zahlen schreiben, wenn Zustand NaN oder `|neu − alt| ≥ 0,001`
(`sensors.cpp:130-138`), Selects bei anderer Option (154-166), Schalter bei anderem Zustand (190-197).
Optimistisch veröffentlicht, das Zurücklesen korrigiert. Gerundet mit `lround`. Einziger gespeicherter
Wert: `optimized_defrosting` (Flash, `persistent_value.h`, `daikin_rotex_can.cpp:144-148`).

## 5. Berechnete Werte

Neu berechnet bei Änderung eines Eingangs, nur wenn das Ziel konfiguriert ist (Ausnahme
`temperature_spread`, immer; `__init__.py:1950-1974`, `daikin_rotex_can.cpp:187-235`).

| Wert | Formel | Auslöser |
|---|---|---|
| `thermal_power_raw` | `(tv − tr) × 4,19 × flow_rate[L/h] / 3600` kW (`daikin_rotex_can.cpp:255`) | tv, tr, flow_rate, mode_of_operating |
| `thermal_power` | dito, geglättet | dito |
| `temperature_spread_raw` / `temperature_spread` | `tv − tr`, roh / geglättet (263-277) | tv, tr |
| `tv_tvbh_delta` | `tv − tvbh` (207-215) | tv, tvbh |
| `tvbh_tr_delta` | `tvbh − tr` (216-224) | tvbh, tr |
| `vorlauf_soll_tv_delta` | `target_supply_temperature − tv` (225-233) | beide |
| `tv_max` | höchstes tv seit der letzten Veröffentlichung von tv, beide zusammen veröffentlicht (`sensors.cpp:54-68`) | jedes Lesen von tv |
| `system_time` | `hh:mm:ss` aus 3 Sensoren (`__init__.py:1576-1586`) | Teile |
| `system_date` | `dd:mm:yyyy` (Jahr + 2000, Doppelpunkte) (1587-1597) | Teile |

Glättung (`sensors.cpp:78-100`, `pid.cpp`, Faktoren `sensors.cpp:19`): Filter, höchstens alle 10 s
`smooth += PID(Soll = letzter Rohwert, Ist = smooth, dt)`; P 0,2, I 0,05, D 0,05, Integral ±0,2,
Tiefpass 0,2 auf P-Fehler, 0,1 auf Ableitung; Ergebnis auf 0,01 gerundet, alle ~10 s veröffentlicht.
PID-Schritt: e = Soll − Ist; P_f = αP·e + (1−αP)·P_f; I = clamp(I + e·dt, ±0,2);
D_f = αD·(e − e_alt)/dt + (1−αD)·D_f; Ausgang = Kp·P_f + Ki·I + Kd·D_f; bei NaN/∞ oder |dt| ≤ 0,1
Ausgang 0 ohne Zeitstempel-Aktualisierung; erster Schritt smooth = Eingang.

Fehlercode-Zusätze (`daikin_rotex_can.cpp:585-675`), nur beim erneuten Lesen von `error_code`, mit tv,
tvbh, tr plus YAML-Offsets `tv_offset`, `tvbh_offset`, `tr_offset`; die erste zutreffende Bedingung
hängt `|<Text>` an den Grundtext (Tabelle `__init__.py:1076-1143`, 0 = „kein Fehler“):

| Zusatz | Bedingung |
|---|---|
| `3UV DHW <defekt>` | flow > 600, `dhw_mixer_position == 0`, `|tvbh − tv| > max_spread_tvbh_tv` (0,3), 10 min |
| `3UV BPV <defekt>` | flow > 600, `bypass_valve == 100`, `|tvbh − tr| > max_spread_tvbh_tr` (0,3), 10 min |
| `<zu geringe Spreizung>` | Betriebsart Warmwasser oder Heizen, Verdichter an, geglättete Spreizung unter Minimum, 20 min |
| `<fehlender Durchfluss>` | Betriebsart Warmwasser, `tdhw1 < 48`, (flow == 0 oder Mischer == 0 oder Verdichter aus), 5 min |

Mindestspreizung: `−0,00004012·tv⁴ + 0,006683·tv³ − 0,4152·tv² + 11,5006·tv − 117,7908`
(angepasst an 50 → 4,0; 40 → 3,0; 35 → 2,5; 29 → 1,2; 27 → 0,3; Zeilen 637-651).
Zeitgeber (`ErrorDetection`, 53-80): Start bei der ersten Fehlerbeobachtung, Rücksetzen bei einer
fehlerfreien. Nur bei der Spreizungsprüfung: nach einem guten Fall ruht die Erkennung, bis sich der
Verdichterzustand oder die Betriebsart ändert (182-184, 358-360).

Tabellen: Betriebsart (`__init__.py:1030-1045`): 0 Standby, 1 Heizen, 2 Kühlen, 3 Abtauen,
4 Warmwasser. SG-Zustände `ext`: 1354-1369. COP nicht in der Komponente (HA-Template
`templates/Berechnung COP.yaml`).

## 6. Sonderlogik

### 6.1 Abtauoptimierung (`daikin_rotex_can.cpp:279-380`)
Zweck: Beim Abtauen den Betriebsmodus auf Sommer stellen → Bypassventil 100 %, weniger Wärmeverlust
aus dem Fußboden (`entities/README.md:3-13`). Virtueller Schalter (Select Aus/An), gespeichert; braucht
die Selects `operating_mode` und `temperature_antifreeze`.

Frostschutz-Kopplung: Einschalten schreibt T-Frostschutz = „Aus“ (`0xFF60`, roh) und speichert `true`;
Ausschalten schreibt nichts. Wird T-Frostschutz anders als „Aus“ gesetzt (HA, RoCon oder HPSU),
schaltet die Optimierung ab (gespeichert).

Zustandsautomat (`on_betriebsart`, 313-361), nur wenn eingeschaltet. Eingänge: Übergang der
Betriebsart `prev → cur`, aktueller Modus `modus`. Heizähnlich: Heizen, Absenken, Auto 1, Auto 2
(581-583). `saved` im RAM, Start Standby.

| Übergang | Bedingung | neuer Modus |
|---|---|---|
| Heizen → Abtauen | modus heizähnlich | Sommer; `saved = modus` |
| Warmwasser → Abtauen | modus heizähnlich | Sommer; `saved = modus` |
| Abtauen → Heizen | modus == Sommer | `saved`, dann `saved = Standby` |
| Abtauen → Warmwasser | modus == Sommer und `saved` heizähnlich | `saved`, dann `saved = Standby` |
| Abtauen → Standby | modus == Sommer | `saved`, dann `saved = Standby` |

Schreiben `sendSetRaw(operating_mode, key)`, übersprungen bei Schlüssel 0. `on_betriebsmodus`
(363-380): wechselt der Modus außerhalb des Abtauens auf etwas nicht Heizähnliches, wird `saved` auf
Standby gesetzt. `saved` wird nicht gespeichert (Neustart während des Abtauens bzw. Abtauen → Standby
bei selbst gewähltem Sommer → Standby, Schlüssel 0x01). Tests:
`test/host/test_optimized_defrosting.py:111-152`.

### 6.2 Weitere Logik
- `dhw_run` (`daikin_rotex_can.cpp:421-454`): aktuellen `target_hot_water_temperature_1` lesen (Select:
  Schlüssel/Teiler); wenn > 0: 70 °C schreiben; Rückschreiben des alten Werts nach 10 s geplant, wird
  vorgezogen, sobald eine Änderung von `target_hot_water_temperature_1` dekodiert wird (normalerweise
  das Zurücklesen von 70) → läuft meist sofort (164-168).
- Raumthermostat `room_therm`: einfacher Schalter `FA 06 78`, Byte 6 (`__init__.py:1443-1450`); sperrt
  das Heizen (`entities/README.md:15-22`).
- `supply_setpoint_regulated` (nicht übernommen, 503-557).
- `custom_request`: 1–7 Hex-Bytes roh auf 0x680 (383-418). `log_filter`: Log-Filter
  (`texts.cpp:11-14`). `dump`: alle Zustände ins Log.
- Manifest: API-Aktion `rotex_can_manifest(page:int)` mit JSON-Seiten ≤ 16 KiB (`manifest.py`,
  `manifest_action.h`); dient der Erkennung „bisherige Firmware“.

### 6.3 Branch `auto_heating` (nicht übernommen)
Heizprogramm 1 (`hz_programm_1`): 30 Register `61 00 FA 14 <reg>` auf 0x300, Register
`0x10+w … 0xA0+w` für Mo, Di, Mi, Do, Fr, Sa, So, MF, SS, MS, w = 0..2 Zeitfenster; High-Byte Start,
Low-Byte Ende in Viertelstunden, `0x80` = unbenutzt.

## 7. Übersetzungen
de, en, it, fr, je 99 Schlüssel (`translations/*.py`), Rückfall Englisch. Tabellen enthalten
`DELAYED_TRANSLATE:<key>`, beim Build für die YAML-`language` aufgelöst; Select-Optionen und
Text-Zustände sind sprachabhängige Texte. Die Schlüssel sind gute Vorlagen für die Zustandsschlüssel
der Integration.

## 8. YAML-Optionen (`__init__.py:1977-2018`)
`canbus_id`, `update_interval` (30 s), `delay_between_requests` (250 ms), `tv_offset`, `tvbh_offset`,
`tr_offset` (0,0; nur Fehlererkennung), `max_spread_tvbh_tv`, `max_spread_tvbh_tr` (0,3), `language`,
`log_filter`, `custom_request`, `dump`, `project_git_hash`, `entities`. Hardware im `canbus:`-Abschnitt:
`esp32_can`, TX GPIO5 / RX GPIO6 in den vollen Beispielen; ESP32-S3 mit SN65HVD230 oder M5 Atom CAN.

## 9. Namen in HA (bisher)
Gerät `hpsu-can` / „HPSU.CAN“; entity_id `<domain>.hpsu_can_<slug(Name)>`; text_sensor → `sensor.`,
Schalter-Einträge → `select.`. Beispiele aus der laufenden Installation: `sensor.hpsu_can_betriebsart`,
`select.hpsu_can_betriebsmodus`, `number.hpsu_can_max_t_vorlauf`, `number.hpsu_can_heizkurve`,
`select.hpsu_can_abtau_optimierung`, `select.hpsu_can_t_frostschutz`, `select.hpsu_can_t_ww_soll1`,
`button.hpsu_can_warmwasser_bereiten`, `sensor.hpsu_can_tv`, `binary_sensor.hpsu_can_status_kompressor`.
Die Integration legt eigene `daikin_…`-Entities an (keine Migration).
