import { create } from "zustand";

/** The sign-in pages speak English or Urdu. Texts are keyed by their English wording, so the English side needs no table and an unknown text just stays English. */
export type Lang = "en" | "ur";
const KEY = "avc-lang";

function initial(): Lang {
  try {
    const saved = window.localStorage.getItem(KEY);
    if (saved === "ur" || saved === "en") return saved;
    return window.navigator.language?.toLowerCase().startsWith("ur") ? "ur" : "en";
  } catch {
    return "en";
  }
}

interface LangState {
  lang: Lang;
  set: (l: Lang) => void;
}

export const useLang = create<LangState>((set) => ({
  lang: initial(),
  set: (lang) => {
    try {
      window.localStorage.setItem(KEY, lang);
    } catch {
      /* not saved: it still applies for this visit */
    }
    set({ lang });
  },
}));

const UR: Record<string, string> = {
  // brand panel
  "Your studio, in motion": "آپ کا اسٹوڈیو، حرکت میں",
  "Turn the words in your head into a video people can watch.": "اپنے ذہن کے الفاظ کو ایسی ویڈیو میں بدلیں جسے لوگ دیکھ سکیں۔",
  "Start from a script or a recording": "اسکرپٹ یا ریکارڈنگ سے آغاز کریں",
  "Captions in English and اردو, shaped correctly": "انگریزی اور اردو کیپشنز، درست شکل میں",
  "Pictures found and timed for you": "تصاویر آپ کے لیے تلاش اور ترتیب دی جاتی ہیں",
  "A full editor when you want control": "جب چاہیں مکمل ایڈیٹر کے ساتھ کنٹرول",
  "Language": "زبان",
  // log in / sign up
  "Log in": "لاگ اِن",
  "Logging in…": "لاگ اِن ہو رہا ہے…",
  "E-mail": "ای میل",
  "Password": "پاس ورڈ",
  "Forgot your password?": "پاس ورڈ بھول گئے؟",
  "Create an account": "اکاؤنٹ بنائیں",
  "Create account": "اکاؤنٹ بنائیں",
  "Creating…": "بن رہا ہے…",
  "Already have an account?": "پہلے سے اکاؤنٹ ہے؟",
  "At least 6 characters. A few random words is a good password.": "کم از کم 6 حروف۔ چند بے ترتیب الفاظ ایک اچھا پاس ورڈ ہیں۔",
  "name@example.com": "name@example.com",
  "At least 6 characters": "کم از کم 6 حروف",
  "Your password": "آپ کا پاس ورڈ",
  "Use at least 6 characters.": "کم از کم 6 حروف استعمال کریں۔",
  "That password is too easy to guess.": "یہ پاس ورڈ بہت آسان ہے، کوئی اور منتخب کریں۔",
  "The password must not be your e-mail address.": "پاس ورڈ آپ کا ای میل ایڈریس نہیں ہونا چاہیے۔",
  "Invitation code": "دعوتی کوڈ",
  "Sign-ups are closed": "سائن اپ بند ہیں",
  "New accounts cannot be created at the moment.": "اس وقت نئے اکاؤنٹ نہیں بنائے جا سکتے۔",
  // confirm
  "Check your e-mail": "اپنی ای میل دیکھیں",
  "E-mail confirmed": "ای میل کی تصدیق ہو گئی",
  "We sent a confirmation e-mail to": "ہم نے تصدیقی ای میل بھیجی ہے:",
  "Type the 6-digit code from the e-mail.": "ای میل میں موجود 6 ہندسوں کا کوڈ درج کریں۔",
  "6-digit code": "6 ہندسوں کا کوڈ",
  "Confirm": "تصدیق کریں",
  "Confirming…": "تصدیق ہو رہی ہے…",
  "Send a new e-mail": "نئی ای میل بھیجیں",
  "Use another address": "دوسرا ایڈریس استعمال کریں",
  "Check the spam folder if it does not arrive within a minute.": "اگر ایک منٹ میں نہ آئے تو سپیم فولڈر دیکھیں۔",
  "Your e-mail address is confirmed. You can log in now.": "آپ کا ای میل ایڈریس تصدیق ہو گیا ہے۔ اب آپ لاگ اِن کر سکتے ہیں۔",
  "Go to log in": "لاگ اِن پر جائیں",
  "Confirm your e-mail address": "اپنا ای میل ایڈریس تصدیق کریں",
  "Confirm my address": "میرا ایڈریس تصدیق کریں",
  "This link is incomplete. Open the whole link from the e-mail.": "یہ لنک نامکمل ہے۔ ای میل سے پورا لنک کھولیں۔",
  // forgot / reset
  "Reset your password": "پاس ورڈ دوبارہ سیٹ کریں",
  "Send me a link": "مجھے لنک بھیجیں",
  "Back to log in": "لاگ اِن پر واپس جائیں",
  "Choose a new password": "نیا پاس ورڈ منتخب کریں",
  "New password": "نیا پاس ورڈ",
  "At least 6 characters.": "کم از کم 6 حروف۔",
  "Change password": "پاس ورڈ تبدیل کریں",
  // messages from the server
  "E-mail or password is wrong.": "ای میل یا پاس ورڈ غلط ہے۔",
  "That does not look like an e-mail address.": "یہ ای میل ایڈریس درست نہیں لگتا۔",
  "Please accept the terms of use and the privacy policy.": "براہِ کرم استعمال کی شرائط اور رازداری کی پالیسی قبول کریں۔",
  "Confirm your e-mail address first: open the link we sent you.": "پہلے اپنے ای میل ایڈریس کی تصدیق کریں: ہماری بھیجی ہوئی ای میل کھولیں۔",
  "Too many attempts. Wait a few minutes and try again.": "بہت زیادہ کوششیں۔ چند منٹ انتظار کریں اور دوبارہ کوشش کریں۔",
  "That code is wrong or has expired. Check the e-mail or ask for a new one.": "کوڈ غلط ہے یا اس کی مدت ختم ہو چکی ہے۔ ای میل دیکھیں یا نیا کوڈ منگوائیں۔",
  "If that is possible, an e-mail is on its way. Check your inbox (and the spam folder).": "اگر یہ ممکن ہوا تو ای میل بھیج دی گئی ہے۔ اپنا ان باکس (اور سپیم فولڈر) دیکھیں۔",
  "This link is invalid or has expired. Sign up again or ask for a new link by logging in.": "یہ لنک درست نہیں یا اس کی مدت ختم ہو چکی ہے۔ دوبارہ سائن اپ کریں۔",
  "This link is invalid or has expired. Ask for a new one.": "یہ لنک درست نہیں یا اس کی مدت ختم ہو چکی ہے۔ نیا لنک منگوائیں۔",
  "Your password has been changed. Log in with the new one.": "آپ کا پاس ورڈ تبدیل ہو گیا ہے۔ نئے پاس ورڈ سے لاگ اِن کریں۔",
  "This e-mail already has an account. Log in, or reset your password if you forgot it.": "اس ای میل پر پہلے سے اکاؤنٹ موجود ہے۔ لاگ اِن کریں، یا پاس ورڈ بھول گئے ہوں تو دوبارہ سیٹ کریں۔",
  "This e-mail already has an account.": "اس ای میل پر پہلے سے اکاؤنٹ موجود ہے۔",
  "Sign-ups are closed at the moment.": "اس وقت سائن اپ بند ہیں۔",
  "You need an invitation code to sign up.": "سائن اپ کے لیے دعوتی کوڈ درکار ہے۔",
};

/** The text in the chosen language (English stays as written). `{n}` style values are filled in. */
export function tr(lang: Lang, text: string, vars?: Record<string, string | number>): string {
  let out = lang === "ur" ? (UR[text] ?? text) : text;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.replace(`{${k}}`, String(v));
  return out;
}

export function useT(): { t: (text: string, vars?: Record<string, string | number>) => string; lang: Lang; dir: "ltr" | "rtl" } {
  const lang = useLang((s) => s.lang);
  return { t: (text, vars) => tr(lang, text, vars), lang, dir: lang === "ur" ? "rtl" : "ltr" };
}
