"""The e-mails the site sends (confirm the address, reset the password, account already exists), in English or Urdu, as plain text and as a styled HTML page.
HTML e-mail only works with tables and inline styles, so the markup below is deliberately old-fashioned; every message also has a plain-text version."""

from __future__ import annotations

from html import escape

TEAL, INK, MUTED, MINT, LINE = "#176b63", "#172321", "#5a6866", "#e4f4ee", "#e5e9e6"
URDU_FONTS = "'Noto Nastaliq Urdu','Jameel Noori Nastaleeq','Geeza Pro','Tahoma',serif"
LATIN_FONTS = "'DM Sans',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

TEXT = {
    "en": {
        "brand": "AI Video Creator",
        "verify_subject": "Confirm your e-mail address",
        "verify_title": "Welcome! Confirm your e-mail",
        "verify_intro": "You are one step away from your first video. Type this code on the sign-up page to confirm that this address is yours.",
        "code_intro": "Your confirmation code",
        "link_note": "The code works for {minutes} minutes and only once. If you did not sign up, you can ignore this e-mail.",
        "reset_subject": "Reset your password",
        "reset_title": "Choose a new password",
        "reset_intro": "We received a request to reset the password of your account.",
        "reset_button": "Choose a new password",
        "reset_note": "The button works for one hour. If you did not ask for this, ignore this e-mail: your password stays as it is.",
        "exists_subject": "Your AI Video Creator account",
        "exists_title": "You already have an account",
        "exists_intro": "Someone tried to sign up with this address, but it already has an account. If it was you, log in, or reset your password if you forgot it.",
        "exists_button": "Log in",
        "footer": "Sent by AI Video Creator. Please do not reply to this message.",
        "fallback": "If the button does not work, copy this address into your browser:",
    },
    "ur": {
        "brand": "AI Video Creator",
        "verify_subject": "اپنا ای میل ایڈریس تصدیق کریں",
        "verify_title": "خوش آمدید! اپنی ای میل کی تصدیق کریں",
        "verify_intro": "آپ اپنی پہلی ویڈیو سے بس ایک قدم دور ہیں۔ تصدیق کے لیے سائن اپ کے صفحے پر یہ کوڈ درج کریں۔",
        "code_intro": "آپ کا تصدیقی کوڈ",
        "link_note": "یہ کوڈ {minutes} منٹ تک اور صرف ایک بار کارآمد ہے۔ اگر آپ نے سائن اپ نہیں کیا تو اس ای میل کو نظر انداز کر دیں۔",
        "reset_subject": "پاس ورڈ دوبارہ سیٹ کریں",
        "reset_title": "نیا پاس ورڈ منتخب کریں",
        "reset_intro": "ہمیں آپ کے اکاؤنٹ کا پاس ورڈ دوبارہ سیٹ کرنے کی درخواست موصول ہوئی ہے۔",
        "reset_button": "نیا پاس ورڈ منتخب کریں",
        "reset_note": "یہ بٹن ایک گھنٹے تک کام کرتا ہے۔ اگر آپ نے یہ درخواست نہیں کی تو اس ای میل کو نظر انداز کر دیں، آپ کا پاس ورڈ جوں کا توں رہے گا۔",
        "exists_subject": "آپ کا AI Video Creator اکاؤنٹ",
        "exists_title": "آپ کا اکاؤنٹ پہلے سے موجود ہے",
        "exists_intro": "کسی نے اس ایڈریس سے سائن اپ کرنے کی کوشش کی، لیکن اس پر پہلے سے اکاؤنٹ موجود ہے۔ اگر یہ آپ تھے تو لاگ اِن کریں، یا پاس ورڈ بھول گئے ہوں تو دوبارہ سیٹ کریں۔",
        "exists_button": "لاگ اِن",
        "footer": "یہ پیغام AI Video Creator کی طرف سے بھیجا گیا ہے۔ براہِ کرم اس کا جواب نہ دیں۔",
        "fallback": "اگر بٹن کام نہ کرے تو یہ ایڈریس اپنے براؤزر میں کاپی کریں:",
    },
}


def _lang(lang: str) -> str:
    return "ur" if lang == "ur" else "en"


def _page(lang: str, title: str, intro: str, button: str | None, url: str | None, note: str, code: str | None = None, code_intro: str = "", center: bool = False) -> str:
    ur = lang == "ur"
    t = TEXT[lang]
    font = URDU_FONTS if ur else LATIN_FONTS
    align = "center" if center else ("right" if ur else "left")
    lh = "2" if ur else "1.6"
    code_block = ""
    if code:
        boxes = "".join(f'<span style="display:inline-block;width:46px;height:60px;line-height:60px;margin:0 4px;border-radius:10px;background:{MINT};border:1px solid #cfe6dd;font:700 30px {LATIN_FONTS};color:{TEAL};text-align:center;">{escape(c)}</span>' for c in code)
        code_block = f'''<tr><td align="center" style="padding:22px 32px 6px 32px;font:600 13px {font};letter-spacing:{'0' if ur else '.08em'};text-transform:{'none' if ur else 'uppercase'};color:{MUTED};">{escape(code_intro)}</td></tr>
<tr><td align="center" style="padding:8px 24px 6px 24px;" dir="ltr">{boxes}</td></tr>'''
    button_block = (f'<tr><td align="{align}" style="padding:16px 32px 8px 32px;"><a href="{escape(url)}" style="display:inline-block;background:{TEAL};color:#ffffff;text-decoration:none;font:600 16px {font};padding:13px 26px;border-radius:10px;">{escape(button)}</a></td></tr>'
                    if button and url else "")
    fallback = (f'<tr><td style="padding:16px 32px 28px 32px;text-align:{align};font:12px/1.6 {LATIN_FONTS};color:#8a9593;" dir="ltr">{escape(t["fallback"])}<br><a href="{escape(url)}" style="color:{TEAL};word-break:break-all;">{escape(url)}</a></td></tr>'
                if url else '<tr><td style="padding:0 0 22px 0;"></td></tr>')
    return f'''<!doctype html>
<html lang="{lang}" dir="{'rtl' if ur else 'ltr'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:#f7f8f6;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7f8f6;padding:32px 12px;"><tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:#ffffff;border:1px solid {LINE};border-radius:16px;overflow:hidden;">
<tr><td style="background:{TEAL};padding:22px 32px;" dir="ltr"><table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="width:34px;height:34px;border-radius:10px;background:rgba(255,255,255,.18);text-align:center;vertical-align:middle;"><span style="display:inline-block;width:0;height:0;border-top:7px solid transparent;border-bottom:7px solid transparent;border-left:11px solid #ffffff;margin-left:4px;"></span></td>
<td style="padding-left:10px;font:700 18px {LATIN_FONTS};color:#ffffff;">{escape(t['brand'])}</td></tr></table></td></tr>
<tr><td style="padding:32px 32px 8px 32px;text-align:{align};font:700 24px/1.3 {font};color:{INK};">{escape(title)}</td></tr>
<tr><td style="padding:4px 32px 8px 32px;text-align:{align};font:16px/{lh} {font};color:{MUTED};">{escape(intro)}</td></tr>
{button_block}
{code_block}
<tr><td style="padding:18px 32px 0 32px;text-align:{align};font:13px/{lh} {font};color:{MUTED};">{escape(note)}</td></tr>
{fallback}
<tr><td style="background:{MINT};padding:14px 32px;text-align:center;font:12px/1.6 {font};color:{MUTED};">{escape(t['footer'])}</td></tr>
</table></td></tr></table></body></html>'''


def _text(lang: str, title: str, intro: str, url: str, note: str, code: str | None, code_intro: str) -> str:
    parts = [title, "", intro, url, ""]
    if code:
        parts += [code_intro, code, ""]
    parts += [note, ""]
    return "\n".join(parts)


def verify(lang: str, code: str, minutes: int = 30) -> tuple[str, str, str]:
    """Confirm the address with a code only (no link): the code is typed on the sign-up page."""
    lang = _lang(lang)
    t = TEXT[lang]
    note = t["link_note"].format(minutes=minutes)
    code_intro = t["code_intro"]
    return (t["verify_subject"], _text(lang, t["verify_title"], t["verify_intro"], "", note, code, code_intro).replace("\n\n\n", "\n\n"),
            _page(lang, t["verify_title"], t["verify_intro"], None, None, note, code, code_intro, center=True))


def reset(lang: str, url: str) -> tuple[str, str, str]:
    lang = _lang(lang)
    t = TEXT[lang]
    return (t["reset_subject"], _text(lang, t["reset_title"], t["reset_intro"], url, t["reset_note"], None, ""),
            _page(lang, t["reset_title"], t["reset_intro"], t["reset_button"], url, t["reset_note"]))


def exists(lang: str, url: str) -> tuple[str, str, str]:
    lang = _lang(lang)
    t = TEXT[lang]
    return (t["exists_subject"], _text(lang, t["exists_title"], t["exists_intro"], url, "", None, ""),
            _page(lang, t["exists_title"], t["exists_intro"], t["exists_button"], url, ""))
