#!/usr/bin/env python3
"""Kaynak güvenilirlik puanı (0 jeton, ağ yok, yalnız standart kütüphane).

URL → {"puan": 0-100, "sinif": ..., "gerekce": [...]}. Şeffaf bir buluşsaldır: alan adı sınıfı + URL kalıp sinyalleri
+ (isteğe bağlı) PLAN.json `kaynaklar` ipuçları. Puan KANIT DEĞİLDİR; hangi bulguyu önce elle doğrulayacağını ve hangisinin
tek başına rapora girmemesi gerektiğini söyleyen bir ÖNCELİK sinyalidir. İçerik doğruluğu `dogrula.py` + Claude'a aittir.

Sınıflar (taban puan): resmî/standart 90 · akademik 85 · resmî doküman 80 · ön baskı 70 · haber 70 · sektör basını 68 · teknik basın 65 ·
kod deposu 65 · ansiklopedi 60 · topluluk 25-55 · belirsiz 50. Sinyaller: planda beklenen kaynak +10, http −10, IP adresi −15,
SEO/derleme URL kalıbı −8, şüpheli TLD −10, izleme parametresi −3.

Kullanım:
  guven.py URL [URL ...] [--plan PLAN.json] [--slug SLUG]
"""
import argparse
import datetime
import ipaddress
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.dont_write_bytecode = True  # skill dizininde __pycache__/.pyc üretme (taranamayan ikili dosya)

# (sınıf, taban puan, [alan adı sonekleri])  — ilk eşleşen kazanır; sıra özelden genele
CLASSES = [
    ("resmî/standart", 90, ["gov", "gov.tr", "gov.uk", "edu", "edu.tr", "ac.uk", "mil", "europa.eu", "int", "ietf.org", "rfc-editor.org",
                           "w3.org", "whatwg.org", "iso.org", "nist.gov", "ecma-international.org", "unicode.org", "tubitak.gov.tr",
                           "resmigazete.gov.tr", "mevzuat.gov.tr", "who.int", "oecd.org", "worldbank.org", "imf.org"]),
    ("akademik", 85, ["nature.com", "science.org", "acm.org", "ieee.org", "springer.com", "sciencedirect.com", "ncbi.nlm.nih.gov",
                      "pubmed.ncbi.nlm.nih.gov", "aclanthology.org", "openreview.net", "doi.org", "jstor.org", "cell.com", "thelancet.com",
                      "nejm.org", "bmj.com", "plos.org", "pnas.org", "wiley.com"]),
    ("ön baskı", 70, ["arxiv.org", "biorxiv.org", "medrxiv.org", "ssrn.com", "researchgate.net", "semanticscholar.org"]),
    ("resmî doküman", 80, ["readthedocs.io", "readthedocs.org", "pypi.org", "npmjs.com", "crates.io", "pkg.go.dev", "docs.rs", "rubygems.org",
                           "developer.mozilla.org", "learn.microsoft.com", "man7.org", "kernel.org", "python.org", "nodejs.org", "rust-lang.org",
                           "go.dev", "developer.apple.com", "developer.android.com", "cloud.google.com", "docs.aws.amazon.com", "kubernetes.io",
                           "postgresql.org", "sqlite.org"]),
    ("kod deposu", 65, ["github.com", "gitlab.com", "codeberg.org", "bitbucket.org", "raw.githubusercontent.com", "github.io"]),
    ("ansiklopedi", 60, ["wikipedia.org", "wikimedia.org", "britannica.com"]),
    ("haber", 70, ["reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com", "ft.com", "economist.com", "wsj.com", "bloomberg.com",
                   "theguardian.com", "aa.com.tr", "trthaber.com"]),
    # 8 Eki 2026 (İHA araştırması): 83 savunma kaynağı "belirsiz" göründü; yerleşik savunma/havacılık sektör yayınları ayrı sınıf.
    ("sektör basını", 68, ["breakingdefense.com", "defensenews.com", "janes.com", "aviationweek.com", "airandspaceforces.com", "twz.com",
                           "thedrive.com", "flightglobal.com", "militarytimes.com", "airforcetimes.com", "armytimes.com", "navytimes.com",
                           "defenseone.com", "c4isrnet.com", "defensescoop.com", "thedefensepost.com", "news.usni.org", "usni.org",
                           "nationaldefensemagazine.org", "insidedefense.com", "defense.info", "euractiv.com", "kyivindependent.com",
                           "csis.org", "rusi.org", "iiss.org", "cnas.org", "brookings.edu", "rand.org", "warontherocks.com", "thediplomat.com"]),
    ("teknik basın", 65, ["arstechnica.com", "theregister.com", "infoq.com", "lwn.net", "theverge.com", "wired.com", "techcrunch.com"]),
    ("topluluk", 55, ["stackoverflow.com", "stackexchange.com", "serverfault.com", "superuser.com", "askubuntu.com"]),
    ("topluluk", 45, ["substack.com", "hashnode.dev", "gist.github.com"]),
    ("topluluk", 40, ["medium.com", "dev.to", "news.ycombinator.com", "blogspot.com", "wordpress.com", "tumblr.com", "linkedin.com"]),
    ("topluluk", 35, ["reddit.com", "youtube.com", "youtu.be", "pinterest.com", "slideshare.net"]),
    ("topluluk", 25, ["quora.com", "x.com", "twitter.com", "facebook.com", "instagram.com", "tiktok.com"]),
]
# `docs.` gibi alt alan adı ön ekleri üretici dokümanına İŞARET EDEBİLİR ama kimse de açabilir (docs.evil.com): resmî sayılmaz, hafif artı.
DOC_PREFIXES = ("docs.", "doc.", "developer.", "developers.", "dev.", "learn.", "help.", "support.", "manual.", "reference.", "api.")
DOC_PREFIX_SCORE = 55
# Herkesin alt alan adı açabildiği (çok kiracılı) platformlar: plan ipucu alt alan adına YAYILMAZ (evil.medium.com ≠ medium.com).
MULTI_TENANT = ("medium.com", "github.io", "gitlab.io", "blogspot.com", "wordpress.com", "substack.com", "tumblr.com", "hashnode.dev",
                "netlify.app", "vercel.app", "pages.dev", "herokuapp.com", "web.app", "firebaseapp.com", "notion.site", "readthedocs.io")
SUSPICIOUS_TLDS = {"xyz", "top", "click", "buzz", "icu", "monster", "rest", "cyou", "sbs", "cfd", "gq", "tk", "ml", "ga", "cf"}
SEO_PATH = re.compile(r"(?:^|[/-])(best|top-?\d+|\d+-best|vs|review|reviews|coupon|coupons|alternatives|cheap|affiliate|ultimate-guide|deals?)(?:[/-]|$)", re.I)
TRACKING = re.compile(r"(?:^|&)(utm_[a-z]+|aff[a-z_]*|ref|fbclid|gclid)=", re.I)
# Çalışan künyesi: parantez içinde birincil|ikincil geçen grup. Gerçek çıktılarda görülen biçimler: (2026-08, birincil) ·
# (2024-08-08; birincil) · (2024-09/2026-08, birincil) · (v2; 2024-09/2026-08, birincil) · (tarih belirtilmemiş; birincil)
TAG_GROUP = re.compile(r"\(([^()]*\b(?:birincil|ikincil)\b[^()]*)\)", re.I)
DATE_RE = re.compile(r"(\d{4})-(\d{2})")
URL_HINT_RE = re.compile(r"(?<![\w@])((?:[a-z0-9-]+\.)+[a-z]{2,})(/[\w./%-]*)?", re.I)
STALE_MONTHS = 18


def host_of(url):
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def _suffix_match(host, suffix):
    return host == suffix or host.endswith("." + suffix)


def classify(host):
    """En ÖZEL (en uzun) alan adı sonekinin sınıfı kazanır: gist.github.com → topluluk, github.com → kod deposu."""
    best = None
    for name, base, suffixes in CLASSES:
        for suffix in suffixes:
            if _suffix_match(host, suffix) and (best is None or len(suffix) > best[0]):
                best = (len(suffix), name, base)
    if best:
        return best[1], best[2]
    if host.startswith(DOC_PREFIXES):
        return "doküman benzeri alt alan (doğrulanmadı)", DOC_PREFIX_SCORE
    return "belirsiz", 50


def is_ip(host):
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def hints_for(table, slug):
    """Konunun kendi ipuçları; konu planda var ama ipucusu BOŞSA başka konuların ipuçları devralınmaz."""
    if not table:
        return None
    return table[slug] if slug in table else table.get("*")


def hints_from_text(text):
    """PLAN.json `kaynaklar` metninden alan adı (+yol) ipuçları: 'docs.astral.sh, github.com/astral-sh/uv' → [(host, path)]."""
    out = []
    for m in URL_HINT_RE.finditer(text or ""):
        out.append((m.group(1).lower().removeprefix("www."), (m.group(2) or "").lower().rstrip("/")))
    return out


def hints_by_slug(plan_path):
    """{slug: [(host, path)...], '*': tümü}. Okunamayan/bozuk plan boş döner (puanlama ipucusuz sürer)."""
    try:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    result, every = {}, []
    for item in plan if isinstance(plan, list) else []:
        if isinstance(item, dict) and isinstance(item.get("slug"), str) and isinstance(item.get("kaynaklar"), str):
            result[item["slug"]] = hints_from_text(item["kaynaklar"])
            every += result[item["slug"]]
    result["*"] = every
    return result


def _hint_match(parsed, host, hints):
    path = parsed.path.lower().rstrip("/")
    for h_host, h_path in hints or []:
        same = host == h_host if any(_suffix_match(h_host, t) for t in MULTI_TENANT) else _suffix_match(host, h_host)
        if same and (not h_path or path == h_path or path.startswith(h_path + "/")):
            return f"{h_host}{h_path}"
    return None


def score(url, hints=None):
    """Tek URL için puan. hints: [(host, path)] — planda beklenen kaynaklar."""
    parsed = urllib.parse.urlparse(url)
    host = host_of(url)
    reasons = []
    if parsed.scheme not in ("http", "https") or not host:
        return {"puan": 0, "sinif": "geçersiz", "gerekce": ["geçerli http(s) adresi değil"]}
    cls, points = classify(host)
    reasons.append(f"{cls} alan adı ({host})")
    if is_ip(host):
        points -= 15
        reasons.append("IP adresi (−15)")
    if parsed.scheme == "http":
        points -= 10
        reasons.append("şifresiz http (−10)")
    if host.rsplit(".", 1)[-1] in SUSPICIOUS_TLDS:
        points -= 10
        reasons.append("şüpheli TLD (−10)")
    if SEO_PATH.search(parsed.path):
        points -= 8
        reasons.append("SEO/derleme URL kalıbı (−8)")
    if TRACKING.search(parsed.query or ""):
        points -= 3
        reasons.append("izleme/ortaklık parametresi (−3)")
    matched = _hint_match(parsed, host, hints)
    if matched:
        points += 10
        reasons.append(f"planda beklenen kaynak: {matched} (+10)")
    return {"puan": max(0, min(100, points)), "sinif": cls, "gerekce": reasons, "planli": bool(matched)}


def claim(finding_text):
    """Çalışanın künyesi: (YYYY-AA[-GG], birincil|ikincil) → {'yil','ay','tur'} ya da None. Bildirimdir, doğrulanmış değildir."""
    groups = TAG_GROUP.findall(finding_text or "")
    if not groups:
        return None
    group = groups[-1]   # künye satırın sonunda olur
    dates = [(int(y), int(m)) for y, m in DATE_RE.findall(group) if 1 <= int(m) <= 12]
    year, month = max(dates) if dates else (None, None)   # aralık "ilk yayın/güncelleme" ise EN SON tarih güncelliği belirler
    return {"yil": year, "ay": month, "tur": "birincil" if re.search(r"birincil", group, re.I) else "ikincil"}


def age_months(claimed, today=None):
    if claimed.get("yil") is None:
        return None
    today = today or datetime.date.today()
    return (today.year - claimed["yil"]) * 12 + (today.month - claimed["ay"])


def assess(finding, hints=None, today=None):
    """Bulgu düzeyi değerlendirme: en iyi/en kötü kaynak puanı + bayraklar.
    Bayraklar: zayıf (en iyi kaynak <50), uyumsuz ('birincil' dendi ama en iyi kaynak <65), eski (bildirilen tarih ≥18 ay)."""
    urls = finding.get("urls") or []
    scored = [dict(score(u, hints), url=u) for u in urls]
    if not scored:
        return {"en_iyi": None, "kaynaklar": [], "bayrak": []}
    best = max(s["puan"] for s in scored)
    best_row = max(scored, key=lambda s: s["puan"])
    flags = []
    if best < 50:
        flags.append(f"zayıf kaynak ({best_row['sinif']}, {best}) — tek başına kanıt sayma")
    c = claim(finding.get("metin", ""))
    if c:
        planned = any(s.get("planli") for s in scored)   # plan bu kaynağı zaten beklenen birincil olarak adlandırmış
        if c["tur"] == "birincil" and best < 65 and not planned:
            flags.append(f"'birincil' denmiş ama en iyi kaynak {best_row['sinif']} ({best})")
        months = age_months(c, today)
        if months is not None and months >= STALE_MONTHS:
            flags.append(f"bildirilen tarih {c['yil']}-{c['ay']:02d} ({months} ay önce) — güncelliği kontrol et")
    return {"en_iyi": best, "sinif": best_row["sinif"], "kaynaklar": scored, "bayrak": flags}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="+")
    ap.add_argument("--plan", help="PLAN.json (kaynaklar ipuçları)")
    ap.add_argument("--slug", help="ipucu alınacak konu (yoksa tüm plan)")
    a = ap.parse_args()
    hints = None
    if a.plan:
        table = hints_by_slug(a.plan)
        hints = table.get(a.slug) if a.slug else table.get("*")
    for u in a.url:
        r = score(u, hints)
        print(f"{r['puan']:>3}  {r['sinif']:<16} {u}\n       " + "; ".join(r["gerekce"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
