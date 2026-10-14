import logging

logger = logging.getLogger("MavonAntibot")

def decode_cloudflare_email(cfemail_hex: str) -> str:
    """Decodes Cloudflare email protection XOR obfuscation."""
    try:
        hex_clean = cfemail_hex.strip()
        if len(hex_clean) < 4:
            return ""
        k = int(hex_clean[:2], 16)
        email_chars = []
        for i in range(2, len(hex_clean), 2):
            email_chars.append(chr(int(hex_clean[i:i+2], 16) ^ k))
        return "".join(email_chars)
    except Exception:
        return ""

async def detect_and_handle_cookies(page) -> str:
    """
    Identifies cookie banners and consent modals, attempts to accept them,
    and returns exact status: 'Accepted', 'Detected (Unaccepted)', or 'None'.
    """
    banner_selectors = [
        '#onetrust-banner-sdk',
        '#onetrust-consent-sdk',
        '#CybotCookiebotDialog',
        'div[id*="Cookiebot" i]',
        '.cmplz-cookiebanner',
        'div[id*="cmplz" i]',
        '.osano-cm-window',
        '.osano-cm-dialog',
        '.qc-cmp2-container',
        '#qc-cmp2-container',
        'div.fc-consent-root',
        'div[id*="cookie" i]:not(body):not(html)',
        'div[class*="cookie-banner" i]',
        'div[class*="cookie-notice" i]',
        'div[class*="cookie-consent" i]',
        'div[class*="cookie-modal" i]',
        'div[class*="cookie-popup" i]',
        'aside[class*="cookie" i]',
        'section[class*="cookie" i]',
        'div[aria-label*="cookie" i]',
        'div[aria-label*="consent" i]',
    ]

    button_selectors = [
        'button#onetrust-accept-btn-handler',
        '#onetrust-accept-btn-handler',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
        '#CybotCookiebotDialogBodyButtonAccept',
        'button.cmplz-accept',
        '.cmplz-btn.cmplz-accept',
        'button.osano-cm-accept-all',
        '.qc-cmp2-summary-buttons button[mode="primary"]',
        'button:has-text("Accept All Cookies")',
        'button:has-text("Accept all cookies")',
        'button:has-text("Accept All")',
        'button:has-text("Accept all")',
        'button:has-text("Allow all cookies")',
        'button:has-text("Allow All")',
        'button:has-text("Allow all")',
        'button:has-text("I Accept")',
        'button:has-text("I accept")',
        'button:has-text("I Agree")',
        'button:has-text("Agree & Close")',
        'button:has-text("Agree")',
        'button:has-text("Accept")',
        'button:has-text("Got it")',
        'button:has-text("OK")',
        'button.cookie-banner__btn',
        'button[data-testid*="cookie-accept" i]',
        'button[aria-label*="Accept" i]',
        'button[id*="cookie-accept" i]',
        'a:has-text("Accept All")',
        'a:has-text("Accept Cookies")',
        '#cookie-accept',
        '.cc-btn.cc-allow',
        '.cc-accept-all',
        'form[action*="consent"] button',
    ]

    banner_present = False
    for sel in banner_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=150):
                banner_present = True
                break
        except Exception:
            continue

    for b_sel in button_selectors:
        try:
            btn = page.locator(b_sel).first
            if await btn.is_visible(timeout=150):
                banner_present = True
                await btn.click(timeout=1000)
                await page.wait_for_timeout(350)
                return "Accepted"
        except Exception:
            continue

    try:
        dismissed = await page.evaluate("() => window.MavonScraper && window.MavonScraper.autoDismissCookies()")
        if dismissed:
            return "Accepted"
    except Exception:
        pass

    if banner_present:
        return "Detected (Unaccepted)"
    return "None"

async def attempt_turnstile_solve(page) -> bool:
    """Attempts to click Cloudflare Turnstile checkbox if visible in iframe or DOM."""
    try:
        frames = page.frames
        for frame in frames:
            if "challenges.cloudflare.com" in frame.url or "turnstile" in frame.url:
                box = frame.locator('input[type="checkbox"], div.ctp-checkbox-label, #challenge-stage input, span.mark').first
                if await box.is_visible(timeout=800):
                    await box.click(timeout=1500)
                    await page.wait_for_timeout(1500)
                    return True
    except Exception:
        pass
    return False

def detect_anti_bot_protection(html: str, title: str, has_extracted_data: bool = False) -> str:
    """Detects if website landing page has Cloudflare or anti-bot challenge active and mentions Access Granted vs Access Denied."""
    t_lower = (title or "").lower()
    h_lower = (html or "").lower()
    content_len = len(html or "")

    is_hard_blocked = (
        "just a moment..." in t_lower
        or "attention required! | cloudflare" in t_lower
        or "403 forbidden" in t_lower
        or "access denied" in t_lower
        or ("security check" in t_lower and content_len < 3500)
        or ("verify you are human" in h_lower and content_len < 2500)
    ) and not has_extracted_data

    # Cloudflare detection
    if "just a moment..." in t_lower or "attention required! | cloudflare" in t_lower:
        return "Cloudflare (Access Denied)"
    if "challenges.cloudflare.com" in h_lower or "cf-turnstile" in h_lower or "cf-browser-verification" in h_lower:
        return "Cloudflare Turnstile (Access Denied)" if is_hard_blocked else "Cloudflare Turnstile (Access Granted)"
    if "cloudflare" in t_lower and ("verification" in t_lower or "security" in t_lower or "blocked" in t_lower or "access denied" in t_lower):
        return "Cloudflare (Access Denied)"
    if "cf-ray" in h_lower or "cloudflare ray id" in h_lower:
        return "Cloudflare (Access Denied)" if is_hard_blocked else "Cloudflare (Access Granted)"
    if "datadome" in h_lower or "dd.datadome.co" in h_lower:
        return "Datadome (Access Denied)" if is_hard_blocked else "Datadome (Access Granted)"
    if "perimeterx" in h_lower or "px-captcha" in h_lower or "press & hold" in h_lower:
        return "PerimeterX (Access Denied)" if is_hard_blocked else "PerimeterX (Access Granted)"
    if "g-recaptcha" in h_lower or "recaptcha/api.js" in h_lower or "hcaptcha" in h_lower:
        return "Captcha Challenge (Access Denied)" if is_hard_blocked else "Captcha Challenge (Access Granted)"
    if "akamai" in h_lower and ("access denied" in t_lower or "incident" in h_lower):
        return "Akamai Shield (Access Denied)"
    if "imperva" in h_lower or "incapsula" in h_lower:
        return "Imperva / Incapsula (Access Denied)" if is_hard_blocked else "Imperva / Incapsula (Access Granted)"
    if "please verify you are a human" in h_lower or "robot or human" in h_lower or "access denied" in t_lower or "security check" in t_lower:
        return "Anti-Bot Challenge (Access Denied)" if is_hard_blocked else "Anti-Bot Challenge (Access Granted)"

    if is_hard_blocked:
        return "Access Denied"

    return "Clean"
