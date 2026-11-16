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

export const FONT_SUGGESTIONS = ["Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", "Arial", "Helvetica", "Georgia", "Verdana"];
