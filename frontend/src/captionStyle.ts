import type { CaptionStyle } from "./api/types";

export const DEFAULT_STYLE: CaptionStyle = {
  font: null,
  size_pct: null,
  color: "#FFFFFF",
  outline_color: "#000000",
  outline_width: 3,
  position: "bottom",
  margin_pct: 7,
  bold: false,
  words_per_line: 7,
  max_chars: 40,
};

/** The server stores a partial style; the form always works with a complete one. */
export const toForm = (stored: Partial<CaptionStyle>): CaptionStyle => ({ ...DEFAULT_STYLE, ...stored });

/** font / size_pct are only sent when set: empty means "automatic for this language". */
export function toPayload(form: CaptionStyle): CaptionStyle {
  const { font, size_pct, ...rest } = form;
  return { ...rest, ...(font?.trim() ? { font: font.trim() } : {}), ...(size_pct ? { size_pct } : {}) };
}

export function sameStyle(a: CaptionStyle, b: CaptionStyle): boolean {
  return JSON.stringify(toPayload(a)) === JSON.stringify(toPayload(b));
}

/** Ready-made looks: a click sets colour, outline and weight (never the font, size or position, which the person may have chosen). */
export const LOOKS: { id: string; name: string; values: Pick<CaptionStyle, "color" | "outline_color" | "outline_width" | "bold"> }[] = [
  { id: "classic", name: "Classic", values: { color: "#FFFFFF", outline_color: "#000000", outline_width: 3, bold: false } },
  { id: "bold", name: "Bold", values: { color: "#FFFFFF", outline_color: "#000000", outline_width: 4, bold: true } },
  { id: "warm", name: "Warm", values: { color: "#FFF3D6", outline_color: "#1B2826", outline_width: 3, bold: false } },
  { id: "pop", name: "Pop", values: { color: "#FFE066", outline_color: "#000000", outline_width: 4, bold: true } },
  { id: "clean", name: "Clean", values: { color: "#FFFFFF", outline_color: "#000000", outline_width: 0, bold: false } },
];

export const lookIsActive = (style: CaptionStyle, look: (typeof LOOKS)[number]): boolean =>
  style.color.toUpperCase() === look.values.color && style.outline_color.toUpperCase() === look.values.outline_color
  && style.outline_width === look.values.outline_width && style.bold === look.values.bold;

export const FONT_SUGGESTIONS = ["Noto Nastaliq Urdu", "Gulzar", "Jameel Noori Nastaleeq", "Arial", "Helvetica", "Georgia", "Verdana"];
