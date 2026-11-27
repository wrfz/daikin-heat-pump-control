// Entry of the module the integration loads on every page: defines the view,
// the card with its editor and the panel.

import { CARD_TYPE, DaikinHeatPumpCard, EDITOR_TYPE } from "./card";
import { DaikinHeatPumpCardEditor } from "./editor";
import { bundleLanguage, localize } from "./localize";
import { DaikinHeatPumpPanel } from "./panel";
import { DaikinHeatPumpView } from "./view";

const define = (name: string, element: CustomElementConstructor): void => {
  if (!customElements.get(name)) customElements.define(name, element);
};

define("daikin-heat-pump-view", DaikinHeatPumpView);
define(CARD_TYPE, DaikinHeatPumpCard);
define(EDITOR_TYPE, DaikinHeatPumpCardEditor);
define("daikin-heat-pump-panel", DaikinHeatPumpPanel);

interface CustomCard {
  type: string;
  name: string;
  description: string;
  preview: boolean;
  documentationURL?: string;
}

const registry = window as unknown as { customCards?: CustomCard[] };
registry.customCards ??= [];
if (!registry.customCards.some((card) => card.type === CARD_TYPE)) {
  const language = bundleLanguage(
    document.documentElement.lang || navigator.language,
  );
  registry.customCards.push({
    type: CARD_TYPE,
    name: localize(language, "card.name"),
    description: localize(language, "card.description"),
    preview: true,
    documentationURL: "https://github.com/wrfz/daikin-heat-pump-control",
  });
}

declare global {
  interface HTMLElementTagNameMap {
    "daikin-heat-pump-view": DaikinHeatPumpView;
    "daikin-heat-pump-card": DaikinHeatPumpCard;
    "daikin-heat-pump-card-editor": DaikinHeatPumpCardEditor;
    "daikin-heat-pump-panel": DaikinHeatPumpPanel;
  }
}
