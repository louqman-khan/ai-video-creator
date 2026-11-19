import type { Limits } from "./api/client";

export interface NewProjectValues {
  name: string;
  language: "" | "en" | "ur";
  aspect: "16:9" | "9:16";
  script: string;
  removeSilence: boolean;
  clean: boolean;
  normalize: boolean;
  captions: boolean;
}

export const DEFAULT_VALUES: NewProjectValues = {
  name: "",
  language: "",
  aspect: "16:9",
  script: "",
  removeSilence: false,
  clean: true,
  normalize: true,
  captions: true,
};

export const formatSize = (bytes: number): string =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;

/** Same rules the server enforces, so mistakes are caught before a big upload starts. */
export function validateAudioFile(file: File, limits: Limits): string | null {
  const ext = file.name.includes(".") ? "." + file.name.split(".").pop()!.toLowerCase() : "";
  if (!limits.extensions.includes(ext)) {
    return `“${file.name}” is not a supported audio file. Use ${limits.extensions.join(", ")}.`;
  }
  if (file.size === 0) return "This file is empty.";
  if (file.size > limits.max_upload_mb * 1024 * 1024) {
    return `This file is ${formatSize(file.size)}; the limit is ${limits.max_upload_mb} MB.`;
  }
  return null;
}

export function validateScript(script: string, limits: Limits): string | null {
  return script.length > limits.max_script_chars
    ? `The script is too long (${script.length.toLocaleString()} characters; limit ${limits.max_script_chars.toLocaleString()}).`
    : null;
}

/** Speaking a typed script needs a script, a language, and an installed voice for it. */
export function validateSpeak(v: NewProjectValues, speech: string[]): string | null {
  if (!v.script.trim()) return "Type the script you want spoken.";
  if (v.language === "") return "Choose English or Urdu: the voice needs to know which language to speak.";
  if (!speech.includes(v.language)) return `No ${v.language === "ur" ? "Urdu" : "English"} voice is available here yet. Upload a recording instead, or choose the other language.`;
  return null;
}

/** `file` null: no recording, the script is spoken by a synthetic voice. */
export function buildForm(file: File | null, v: NewProjectValues): FormData {
  const f = new FormData();
  if (file) f.append("file", file);
  if (v.name.trim()) f.append("name", v.name.trim());
  f.append("language", v.language);
  f.append("aspect", v.aspect);
  if (v.script.trim()) f.append("script", v.script);
  f.append("remove_silence", String(v.removeSilence));
  f.append("clean", String(v.clean));
  f.append("normalize", String(v.normalize));
  f.append("captions", String(v.captions));
  return f;
}
