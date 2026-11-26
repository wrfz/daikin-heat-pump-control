# Referenz: bisheriges Dashboard (Funktionsbeschreibung)

Ergebnis der Analyse der Lovelace-Card unter `/home/bob/git/ha/core/config/www/daikin-rotex-hpsu-dashboard`
(Repo `wrfz/daikin-rotex-hpsu-dashboard`, HEAD `acc46db`). Dient als Spezifikation für Panel und Card
der Integration; kein Code übernehmen. Pfade relativ zu diesem Ordner.

## 1. Anzeige

### 1.1 SVG
- Drei Layouts (`src/svg_item_config.ts:1309-1318`): `glass-dark`, `glass-light` (Standard),
  `glass-petrol`; Dateien `dist/hpsu_glass_{light,dark,petrol}.svg` (im Git, nur `dist/*.js*` ignoriert),
  viewBox 2560×1570, je ~47 KB, unterscheiden sich nur in Farben; eingebettetes `<style>`,
  `#background`, `#layout-art` (Skalierung 1,6).
- Laden zur Laufzeit per `fetch(url, {cache: "no-cache"})` (`src/card.ts:91-108`), URL neben dem
  Skript (`card.ts:911-934`).
- Verarbeitung (`card.ts:225-257`): DOMParser; Stil-Hinweise am `<svg>`: `data-box-radius`,
  `data-box-fill`, `data-box-stroke`, `data-box-stroke-width`, `data-text-color`, `data-label-color`,
  `data-own-state-style`; Konfigurations-Überschreibungen; `preserveAspectRatio="xMidYMid meet"`;
  Label- und Wert-`<text>` erzeugen; Ausgabe per `unsafeSVG` in `<ha-card>`.
- Genutzte Element-IDs: Gruppen/Rechtecke aus der Tabelle 1.2; Symbole `compressor-symbol`,
  `pump-symbol`, `eev-symbol`, `fourway-symbol`, `fan`; Fluss `gas-flow`, `gas-bubbles`, `water-flow`,
  `fw-heat`, `fw-cool`, `fw-bridge`, `buh-schema`; Ventile `dhw-flap`, `bpv-flap`, `dhw-open-arrows`,
  `dhw-closed-arrows`, `bpv-open-arrows`, `bpv-closed-arrows`.
- Root-Attribute: `data-run-map` (Element → `{entity, mode: on|gt0|eq, value}`), `data-temp-vars`
  (`--k-*` → `{entity: [ids], min, max}`), in allen Layouts gleich.

### 1.2 Werte (`svg_item_config.ts:62-1299`)
„Schlüssel“ = Schlüssel der Bus-Komponente. Nachkommastellen Standard 1, Schriftgröße 56.

| Wert-ID | Gruppe / Wert-Rechteck | Bus · Schlüssel | Domain | Einheit | Hinweis |
|---|---|---|---|---|---|
| ta | TA / ta_val | CAN · temperature_outside | sensor | °C | |
| ta2 | TA2 / ta2_val | CAN · ta2 | sensor | °C | optional, Gruppe ohne Entity versteckt |
| expansion_valve | EEV / eev_val | UART · exv | sensor | pls | 0 Stellen |
| four_way_valve | fourway-schema | UART · 4_way_valve | Text | – | nur Symbolzustand |
| pressure_equalization | eev-schema | UART · press_eq | binär | – | nur EEV-Hervorhebung |
| kondensat | Kondensat / kondensat_value | UART · t_liq | sensor | °C | |
| subcooling | Kondensat / subcooling_value | UART · subcooling | sensor | K | optional, „---“ bei unbekannt, Präfix „UK“/„SC“ |
| umwaelzpumpe | Umwaelzpumpe / uwp_value | CAN · circulation_pump | sensor | % | 0 Stellen |
| umwaelzpumpe_an_aus | Umwaelzpumpe-Status | CAN · status_kesselpumpe | binär | – | Rechteck fehlt in den Layouts, nur Symbol |
| durchfluss | Durchfluss / flow_rate_value | CAN · flow_rate | sensor | L/h | 0 Stellen |
| ruecklauf / ruecklauf_2 | Ruecklauf | CAN · tr / UART · tr | sensor | °C | |
| verdampfer | Verdampfer | UART · exch_temp | sensor | °C | |
| hot_gas | hot_gas | UART · temp_after_compr | sensor | °C | |
| discharge_superheat | hot_gas | UART · discharge_superheat | sensor | K | optional, „---“, Präfix „ÜH“/„SH“ |
| saturation_temp | Kondensation | UART · saturation_temp | sensor | °C | optional |
| hot_gas_condenser | hot_gas_condenser | extern | sensor | °C | optional |
| refrigerant_pressure | hot_gas_condenser | UART · refrigerant_pressure | sensor | bar | optional |
| spread | Spreizung | CAN · temperature_spread_raw | sensor | °C | |
| vorlauf_1 / vorlauf_2 | Vorlauf | CAN · tv / UART · tv | sensor | °C | |
| vorlauf_soll | Vorlauf-Soll | CAN · target_supply_temperature | sensor | °C | |
| wasserdruck | Druck | CAN · water_pressure | sensor | bar | |
| vorlauf_bh_1 / vorlauf_bh_2 | Vorlauf-BH | CAN · tvbh / UART · tv_bh | sensor | °C | |
| kompressor_an_aus | compressor_on_off_group | CAN · status_kompressor | binär | – | Rechteck fehlt, nur Symbol |
| luefter | Luefter | UART · fan_speed | sensor | RPM | 0 Stellen |
| verdichter | Verdichter | UART · inv_freq | sensor | RPM | 0 Stellen |
| speicher | Speicher | CAN · tdhw1 | sensor | °C | |
| speicher_soll | Speicher-Soll | CAN · target_hot_water_temperature_1 | (bisher select) | °C | |
| buh_power | buh | extern | sensor | W/kW | optional |
| mischer | DHW-Valve | CAN · dhw_mixer_position | sensor | % | 0 Stellen, 40px |
| bypass | BPV-Valve | CAN · bypass_valve | sensor | % | 0 Stellen, 40px, links |
| Info-Box (sortierbar, `Info`): fehlercode (CAN error_code), betriebsmodus (CAN operating_mode), betriebsart (CAN mode_of_operating), thermische_leistung (CAN thermal_power, kW), el_power (extern, optional), cop (extern, optional), t_room_is (extern, optional), room_setpoint (extern input_number, optional) | | | | | Präfixe „Fehlercode: “, „Modus: “, „Betriebsart: “ je Sprache |

### 1.3 Formatierung (`card.ts:666-765`)
- Keine Entity: „N/D“ orange 30px, optional → versteckt. unknown/unavailable: mit `dash_unknown` „---“,
  sonst „N/A“ orange.
- `binary_sensor.*`: „An“/„Aus“ bzw. „On“/„Off“, `data-state` on/off.
- Sonst `Intl.NumberFormat(hass.language)` mit festen Stellen + Einheit der Entity; Nicht-Zahlen roh.
  Sonderfall „Warmwasserbereitung“ → „Warmwasser“. Präfix je Sprache; `prefix_label` als eigener tspan.
- Dezimal-Ausrichtung über `data-sep=<x>` (Vorlauf, Vorlauf-BH, Ruecklauf, Kondensat, hot_gas,
  hot_gas_condenser).
- Fehlercode rot ist beabsichtigt, greift wegen eines Fehlers nie (`card.ts:740-748`).
- `textState()` setzt `data-state` (`na`/`unavailable`/`on`/`off`/`error`/`normal`); mit
  `data-own-state-style` färbt das SVG-CSS.

### 1.4 Sichtbarkeit
Elterngruppen (`TA2`, `Kondensation`, `hot_gas_condenser`, `buh`) nur mit mindestens einer vorhandenen
Entity. Optionale Zeilen ohne Zustand versteckt; `adjustBox` packt Zeilen, verkleinert `<group>_rect`,
verschiebt Linien mit `data-edge="bottom"`, versteckt `path[data-box=<group>]`. Info-Box in
konfigurierter Reihenfolge. Abgerundete Container aus der Bounding-Box (ohne Pfade gemessen).

### 1.5 Animationen und Farben (überwiegend SVG-CSS)
`data-run-map`: `fan` ← luefter `gt0`; `gas-flow`, `gas-bubbles`, `compressor-symbol`, `fw-bridge`,
`fourway-symbol` ← kompressor_an_aus `on`; `water-flow`, `pump-symbol` ← umwaelzpumpe_an_aus `on`;
`eev-symbol` ← pressure_equalization `on`; `buh-schema` ← buh_power `gt0`; `fw-heat` ← four_way_valve
`eq` „Heizen“; `fw-cool` ← four_way_valve `eq` „Kühlen“ (in der Integration über Zustandsschlüssel).

`data-temp-vars` (Wert → (v − min)/(max − min), 0..1, erster endlicher Wert der Liste):

| Variable | Werte | Bereich |
|---|---|---|
| `--k-hotgas` | hot_gas | 25–100 |
| `--k-hotgas-cond` | hot_gas_condenser, dann hot_gas | 25–100 |
| `--k-evap` | verdampfer | 25–100 |
| `--k-liquid` | kondensat | 25–100 |
| `--k-vorlauf` | vorlauf_1, dann vorlauf_2 | 20–45 |
| `--k-vorlauf-bh` | vorlauf_bh_1, dann vorlauf_bh_2 | 20–45 |
| `--k-ruecklauf` | ruecklauf, dann ruecklauf_2 | 20–45 |
| `--k-speicher-p` | speicher | 20–45 |
| `--k-speicher` | speicher | 20–70 |
| `--k-mischer` | mischer | 0–100 |
| `--k-bypass` | bypass | 0–100 |
| `--k-fan` | luefter | 0–1000 |

Farben: Wasser `color-mix(in oklab)` blau → orange → rot; Kältemittel kalt ↔ heiß; abgeleitete
Variablen für Speicherwendel (`--k-coilin/mid/out`, Rest `0,4·m²`), Ventilmischung (`--k-valve`),
Fußboden-Rücklauf (`--k-floorret`, Energiebilanz mit Bypass). Animationen: `.flow` 4,2 s, Lüfter
`4s / max(--k-fan, .02)`, Verdichter `.stripes` 4,8 s / `.orbit` 2,4 s, Pumpe `.blink` 3,6 s, EEV-Blasen
14,7 s (Richtung kehrt bei Umkehrbetrieb); Pause bei off/unknown und bei `svg[data-animations="off"]`.
Aus: Verdichter/Pumpe grau 0,55; Heizstab grau; EEV gelb mit Leuchten bei Druckausgleich. 4-Wege-Ventil:
ohne `fw-heat` Rotor 90°, Flüsse und Blasen umgekehrt, EEV gespiegelt. Ventilklappen (`card.ts:863-899`):
Drehung zwischen `data-a0` (48°) und `data-a1` (−48°) um `data-pivot` nach %; Pfeilgruppen Deckkraft
m/100 bzw. 1 − m/100. Hintergrund `--bg-color`, `--bg-opacity`, `data-bg="off"`.

## 2. Konfiguration (bisher)
`layout`, `language`, `animations`, `background{show, color[r,g,b], opacity}`, `box{fill, fill_opacity,
border, border_opacity}`, `text{value_color, label_color}`, `can_device`, `uart_device`,
`can_entities{id: entity}`, `uart_entities{…}`, `info_entities: [{key, entity?}]` (Reihenfolge = Zeilen)
(README.md:69-85, `svg_item_config.ts:1349-1389`). Keine automatische Erkennung zur Laufzeit; nur der
Editor-Knopf über das Manifest.

## 3. Editor (`src/editor.ts`)
Reiter **Darstellung** (`ha-form`: Layout, Animationen, aufklappbar Hintergrund/Box/Text mit „eigene
Werte“-Schaltern; nur Abweichungen vom Standard werden gespeichert), **Geräte** (CAN/UART-Gerät,
Zähler zugeordnet, Laden aus dem Manifest mit Vorher/Nachher-Tabelle), **Sensoren** (gruppiert nach
Funktion: Kältekreis, Heizen, Warmwasser, Info, Sonstige – oder nach Bus; Suche; CAN/UART-Paare
nebeneinander; Info-Zeilen per Ziehen sortierbar; Entity-Auswahl gefiltert nach Gerät, Domain und
Einheit; Warnung bei falscher Einheit). Texte de/en.

## 4. Interaktion
Klick auf einen Wert (`<value_rect_id>_text`) → `hass-more-info`. Symbole: Verdichter →
kompressor_an_aus, Pumpe → umwaelzpumpe_an_aus, EEV → pressure_equalization, 4-Wege → four_way_valve.
Keine tap/hold-Aktionen, keine Dienstaufrufe.

## 5. Layout, Theme, Sprache
SVG 100 % breit; in Panel-Ansicht Breite `calc(100vw - var(--mdc-drawer-width, 256px))`, Höhe bis
`100vh - header`; unter 767px Höhe `100vh - header`. Theme-Variablen `--ha-card-background`,
`--ha-card-border-color` (Rückfall `--divider-color`), `--ha-card-border-width`,
`--ha-card-border-radius`, `--secondary-text-color`, `--primary-text-color`; Layout-Attribute und
Konfiguration überschreiben. Kein automatisches Dunkel-Layout. Sprachen de/en/it (Rückfall de).

## 6. Bekannte Schwächen (in der Neuumsetzung beheben)
- deutsche Zustandstexte in der Logik („Heizen“, „Kühlen“, „Warmwasserbereitung“, Fehlercodes);
- Fehlercode rot greift nie;
- tote Rechtecke `circ_pump_rect`, `comp_rect`;
- Fehlermeldung nur deutsch, Fehlerzustand nie gesetzt (`card.ts:104-107, 217`);
- kein `getStubConfig`, `getCardSize`, keine Grid-Optionen.
