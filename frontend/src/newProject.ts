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

export function buildForm(file: File, v: NewProjectValues): FormData {
  const f = new FormData();
  f.append("file", file);
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
