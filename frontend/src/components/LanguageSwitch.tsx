import { useLang, type Lang } from "../i18n";

/** "Choose your language: English | اردو". The choice is remembered and the page turns right-to-left for Urdu. */
export function LanguageSwitch() {
  const { lang, set } = useLang();
  const options: [Lang, string][] = [["en", "English"], ["ur", "اردو"]];
  return (
    <div className="lang-switch" role="group" aria-label={lang === "ur" ? "زبان" : "Language"}>
      <span className="lang-label">{lang === "ur" ? "اپنی زبان منتخب کریں" : "Choose your language"}</span>
      <span className="seg">
        {options.map(([l, label]) => (
          <button key={l} type="button" lang={l} className={`seg-b${lang === l ? " seg-on" : ""}`} aria-pressed={lang === l} onClick={() => set(l)}>{label}</button>
        ))}
      </span>
    </div>
  );
}
