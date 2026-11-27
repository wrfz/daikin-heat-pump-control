import de from "./translations/de.json";
import en from "./translations/en.json";
import fr from "./translations/fr.json";
import it from "./translations/it.json";

type Texts = typeof en;

export const TRANSLATIONS: Record<string, Texts> = { de, en, fr, it };

/** Language of the bundle texts for a locale such as `de-CH`; English otherwise. */
export function bundleLanguage(language: string | undefined): string {
  const base = (language ?? "").split("-")[0]?.toLowerCase() ?? "";
  return base in TRANSLATIONS ? base : "en";
}

/** Return the text `section.key` in a language, falling back to English. */
export function localize(language: string | undefined, path: string): string {
  const [section, key] = path.split(".", 2) as [string, string];
  const lookup = (texts: Texts): string | undefined =>
    (texts as Record<string, Record<string, string> | undefined>)[section]?.[
      key
    ];
  const texts = TRANSLATIONS[bundleLanguage(language)] ?? en;
  return lookup(texts) ?? lookup(en) ?? path;
}
