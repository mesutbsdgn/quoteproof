#!/usr/bin/env python3
"""Araştırma notlarını 0 token ile denetler (yalnız standart kütüphane).

Kontroller (not başına):
  - biçim: her soru bölümünde Özet / Alıntılı bulgular / Çıkarımlar / Boşluklar
  - kaynaksız bulgu: "Alıntılı bulgular" altında URL'si olmayan madde
  - bağlantılar: canlılık (HEAD, gerekirse GET), arama-sonuç sayfası, plan bağlamında tek alan adına bağımlılık
  - kaynak güvenilirliği: alan adı sınıfı/puanı (guven.py), 'birincil' iddiası uyuşmazlığı, bildirilen tarih eskiliği
  - doğrulama adayları: sayısal/tarihli, tek kaynaklı, ikincil kaynaklı iddialar (Claude'un kaynakta açması için)

Kullanım:
  denetle.py NOTLAR_DIZINI [--cikti denetim.md] [--link-yok] [--aday 8] [--plan PLAN.json]
Çıkış kodu 0; sorunlar raporda.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # skill dizininde __pycache__/.pyc üretme (taranamayan ikili dosya)
import datetime
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

URL_RE = re.compile(r"\]\((https?://(?:[^()\s]|\([^()\s]*\))+)\)|(?<![(\[])\bhttps?://[^\s)<>\]]+")
SECTIONS = ("Özet", "Alıntılı bulgular", "Çıkarımlar", "Boşluklar")
SEARCH_HOSTS = ("google.", "bing.com", "duckduckgo.com", "search.yahoo.", "yandex.")
COMMUNITY = ("reddit.com", "quora.com", "medium.com", "blogspot.", "wordpress.com", "pinterest.", "facebook.com", "x.com", "twitter.com")
NUMERIC = re.compile(r"\d")
BULLET_RE = re.compile(r"^(?:[-*]|\d+[.)])\s+")
SAME_SOURCE = re.compile(r"\b(a[yı]n[ıi]\s+kaynak|ayn[ıi]\s+sayfa|ayn[ıi]\s+belge|ibid)\b", re.I)
STRONG_NUMERIC = re.compile(r"(%|\$|€|£|₺|\bTL\b|\bUSD\b|\bEUR\b|\bv?\d+\.\d+(\.\d+)?\b|\b(19|20)\d\d\b|\b\d{2,}\b)")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import guven  # noqa: E402
import oku  # noqa: E402

UA = "arastir-ogren/1.0 (baglanti-kontrolu)"
# Çalışan web aramasını yapamadığını notuna yazmışsa (ör. arama sağlayıcısı kapalı) sonuç yalnız bildiği URL'lere dayanır.
NO_SEARCH = re.compile(r"ECONNREFUSED|web[_ ]?search[^.\n]{0,60}(kapal|devre dışı|çalışm|erişilem|failed|unavailable)|web aramas[ıi][^.\n]{0,40}(kapal|devre dışı|yapılamad|çalışm)", re.I)


def bullet_urls(text):
    urls = []
    for m in URL_RE.finditer(text):
        urls.append((m.group(1) or m.group(0)).rstrip(".,;:`'\"*>"))
    return urls


def host(url):
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def planned_publishers(path):
    """Açıkça planlanan tek yayımlayıcıyı konu slug'ına bağla."""
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return {}
    return {item["slug"]: item["single_publisher_host"] for item in data
            if isinstance(item, dict) and isinstance(item.get("slug"), str)
            and isinstance(item.get("single_publisher_host"), str)}


def parse_note_text(text):
    """İşçi kabul kapısı ve denetim için ortak, ağsız bölüm ayrıştırıcısı."""
    questions, current, sub = [], None, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = {"baslik": line[3:].strip(), "bolumler": {}}
            questions.append(current)
            sub = None
        elif line.startswith("### ") and current is not None:
            sub = line[4:].strip()
            current["bolumler"].setdefault(sub, [])
        elif current is not None and sub is not None:
            current["bolumler"][sub].append(line)
    return questions


def parse_note(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    return text, parse_note_text(text)


def analyze(path):
    text, questions = parse_note(path)
    findings, problems, inherited = [], [], 0
    if not questions:
        problems.append("hiç '## Soru' bölümü yok (biçim bozuk)")
    for q in questions:
        missing = [s for s in SECTIONS if s not in q["bolumler"]]
        if missing:
            problems.append(f"'{q['baslik'][:50]}': eksik bölüm → {', '.join(missing)}")
        local, unparsed = [], 0
        for line in q["bolumler"].get("Alıntılı bulgular", []):
            stripped = line.strip()
            if not stripped or stripped in ("-", "- —", "* —", "—") or stripped.startswith(("```", "|", ">")):
                continue
            m = BULLET_RE.match(stripped)
            if not m:
                unparsed += 1  # madde biçiminde olmayan satır sessizce atlanmaz, raporlanır
                continue
            body = stripped[m.end():].strip()
            if body in ("—", ""):
                continue
            urls = bullet_urls(body)
            # "aynı kaynak" diyen madde AYNI sorudaki önceki maddenin URL'sini devralır (soru sınırını aşmaz).
            if not urls and SAME_SOURCE.search(body) and local and local[-1]["urls"]:
                urls, inherited = list(local[-1]["urls"]), inherited + 1
            item = {"soru": q["baslik"], "metin": body, "urls": urls}
            local.append(item)
            findings.append(item)
        if unparsed:
            problems.append(f"'{q['baslik'][:40]}': {unparsed} satır madde biçiminde değil (atlandı)")
    uncited = [f for f in findings if not f["urls"]]
    urls = sorted({u for f in findings for u in f["urls"]})
    return {
        "dosya": path.name, "bulgu": len(findings), "kaynaksiz": uncited,
        "urls": urls, "sorunlar": problems, "findings": findings,
        "devralan": inherited,
        "bos": len(text.strip()) < 300,
        "aramasiz": bool(NO_SEARCH.search(text[:1500])),
    }


def check_url(url, timeout=8):
    """Bağlantı canlılığı. Ağ, oku.py'nin SSRF-güvenli istemcisinden geçer (özel/yerel adresler ve yönlendirmeler engellenir)."""
    h = host(url)
    if any(h.startswith(s) or s in h for s in SEARCH_HOSTS) and "/search" in url:
        return url, "arama-sayfası", ""
    try:
        final, ctype, body, status, headers = oku.request(url, method="HEAD", read_body=False, timeout=timeout, total=timeout * 2)
        if status in (400, 403, 405, 501):
            final, ctype, body, status, headers = oku.request(url, method="GET", headers={"Range": "bytes=0-0"}, read_body=False, timeout=timeout, total=timeout * 2)
    except ValueError as e:
        if "engellendi" in str(e):
            return url, "engellendi", "yerel/özel ağ adresi (SSRF koruması)"
        return url, "ulaşılamadı", str(e)[:60]
    except Exception as e:  # zaman aşımı, DNS, TLS
        return url, "ulaşılamadı", type(e).__name__
    if status in (404, 410):
        return url, "ölü", f"HTTP {status}"
    if status in (401, 403, 429, 999):
        return url, "doğrulanamadı", f"HTTP {status} (engelli/oran sınırı)"
    if status >= 400:
        return url, "hata", f"HTTP {status}"
    return url, "ok", "" if final == url else f"→ {host(final)}"


GITHUB_RE = re.compile(r"https?://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]+)")
GITHUB_SKIP = {"orgs", "features", "topics", "search", "marketplace", "sponsors", "settings", "about", "pricing", "login", "collections", "trending", "explore"}
STALE_DAYS = 365
STALE_FLAG_PREFIX = "bildirilen tarih"   # guven.assess eski-tarih bayrağının başı


def github_repos(results):
    repos = {}
    for r in results:
        for u in r["urls"]:
            m = GITHUB_RE.match(u)
            if m and m.group(1).lower() not in GITHUB_SKIP:
                repos[f"{m.group(1)}/{m.group(2).removesuffix('.git')}"] = u
    return sorted(repos)


def check_repo(full_name, today=None):
    """`gh api` ile depoyu doğrular (0 token). Dönüş: sözlük (durum: ok|yok|arşivli|durgun|hata)."""
    try:
        proc = subprocess.run(["gh", "api", f"repos/{full_name}", "--jq",
                               "[.stargazers_count,.archived,.pushed_at,.fork,.description]|@json"],
                              capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return {"repo": full_name, "durum": "hata", "not": "gh zaman aşımı"}
    if proc.returncode != 0:
        text = (proc.stderr or "").lower()
        if "404" in text or "not found" in text:
            return {"repo": full_name, "durum": "yok", "not": "depo bulunamadı (uydurma ya da silinmiş olabilir)"}
        return {"repo": full_name, "durum": "hata", "not": (proc.stderr.strip().splitlines() or ["gh hatası"])[-1][:80]}
    stars, archived, pushed, fork, desc = json.loads(proc.stdout)
    today = today or datetime.datetime.now(datetime.timezone.utc)
    age = (today - datetime.datetime.fromisoformat(pushed.replace("Z", "+00:00"))).days if pushed else None
    status = "arşivli" if archived else "durgun" if age is not None and age > STALE_DAYS else "ok"
    return {"repo": full_name, "durum": status, "yildiz": stars, "son_push_gun": age, "fork": fork, "not": (desc or "")[:70]}


def verify_github(results, jobs=6):
    if not shutil.which("gh"):
        return None
    repos = github_repos(results)
    if not repos:
        return []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        return list(pool.map(check_repo, repos))


def verification_candidates(results, link_status, limit, hints=None):
    """Doğrulanması en değerli iddialar: sayısal/tarihli, tek kaynaklı, ikincil kaynaklı, canlı bağlantılı."""
    url_counts = {}
    for r in results:
        for u in r["urls"]:
            url_counts[u] = url_counts.get(u, 0) + 1
    hints = hints or {}
    scored = []
    for r in results:
        for f in r["findings"]:
            if not f["urls"] or not NUMERIC.search(f["metin"]):
                continue
            score = 0
            if STRONG_NUMERIC.search(f["metin"]):
                score += 3
            if len(f["urls"]) == 1:
                score += 2
            if any(any(c in host(u) for c in COMMUNITY) for u in f["urls"]):
                score += 2
            trust = guven.assess(f, guven.hints_for(hints, Path(r["dosya"]).stem))
            if trust["en_iyi"] is not None and trust["en_iyi"] < 55:
                score += 2   # zayıf kaynaklı iddia önce elle doğrulanır
            if "ikincil" in f["metin"].lower():
                score += 1
            if any(link_status.get(u, ("ok",))[0] in ("ölü", "ulaşılamadı") for u in f["urls"]):
                score -= 5  # önce bağlantıyı düzelt; açılamayan kaynak doğrulanamaz
            scored.append((score, r["dosya"], f))
    scored.sort(key=lambda x: -x[0])
    return scored[:limit]


def trust_section(results, hints):
    """Kaynak güvenilirliği bölümü: alan adı tablosu + bulgu bayrakları (zayıf / uyumsuz / eski)."""
    hints = hints or {}
    rows, flagged = {}, []
    for r in results:
        h = guven.hints_for(hints, Path(r["dosya"]).stem)
        for f in r["findings"]:
            a = guven.assess(f, h)
            for s in a["kaynaklar"]:
                key = host(s["url"])
                if key not in rows or s["puan"] > rows[key]["puan"]:
                    rows[key] = s
            for flag in a["bayrak"]:
                flagged.append((r["dosya"], f["metin"], flag))
    if not rows:
        return []
    L = ["## Kaynak güvenilirliği (buluşsal; kanıt değil, öncelik sinyali — guven.py)", "",
         "| Alan adı | Sınıf | Puan | Gerekçe |", "|---|---|---:|---|"]
    for key, s in sorted(rows.items(), key=lambda kv: kv[1]["puan"]):
        L.append(f"| {key} | {s['sinif']} | {s['puan']} | {'; '.join(s['gerekce'][1:]) or '—'} |")
    avg = sum(s["puan"] for s in rows.values()) / len(rows)
    L += ["", f"Ortalama alan adı puanı: {avg:.0f}/100 ({len(rows)} alan adı)."]
    stale = [(d, t, f) for d, t, f in flagged if f.startswith(STALE_FLAG_PREFIX)]
    flagged = [x for x in flagged if not x[2].startswith(STALE_FLAG_PREFIX)]
    if flagged:
        L += ["", "Bayraklı bulgular (rapora almadan önce Claude kontrol etmeli):"]
        L += [f"- `{d}` — {t[:110]} → **{flag}**" for d, t, flag in flagged[:20]]
    if stale:   # tek tek sıralamak gürültü: 10 bulgunun 9'u "26 ay önce" bayrağı alıyordu (yayımlanmış standart tarihi tek başına sorun değildir)
        dates = sorted(re.findall(r"bildirilen tarih (\d{4}-\d{2})", " ".join(f for _, _, f in stale)))
        span = f" ({dates[0]} … {dates[-1]})" if dates else ""
        L += ["", f"Eski tarih: {len(stale)} bulgunun bildirilen tarihi {guven.STALE_MONTHS} aydan eski{span}. "
                  "Hızlı değişen konularda (sürüm, fiyat, ürün özelliği) güncelliği kontrol et; yayımlanmış standart ve resmî belgelerde tarih tek başına sorun değildir."]
    return L + [""]


def render(results, link_status, candidates, link_checked, github=None, hints=None, publishers=None):
    L = ["# Araştırma notu denetimi", ""]
    L += ["| Not | Bulgu | Kaynaksız | URL | Farklı alan adı | Sorun |", "|---|---:|---:|---:|---:|---|"]
    publisher_info = []
    for r in results:
        hosts = {host(u) for u in r["urls"]}
        documents = {urllib.parse.urldefrag(u).url for u in r["urls"]}
        issues = list(r["sorunlar"])
        if r["bos"]:
            issues.append("not boş/çok kısa")
        if len(hosts) == 1 and r["bulgu"] >= 3:
            expected = (publishers or {}).get(Path(r["dosya"]).stem)
            if expected in hosts and len(documents) >= 2:
                publisher_info.append(f"- `{r['dosya']}`: {len(documents)} farklı belge, {len(hosts)} alan adı "
                                      f"(`{expected}`); planla uyumlu. Bağımsız yayımlayıcı teyidi sayılmaz.")
            else:
                issues.append("tüm kaynaklar tek alan adı")
        if r["devralan"]:
            issues.append(f"{r['devralan']} madde URL'yi 'aynı kaynak' diye devraldı (kendi URL'si yok)")
        if r["aramasiz"]:
            issues.append("çalışan web araması yapamadı (yalnız bildiği URL'leri açtı → kapsam sınırlı)")
        if r["bulgu"] == 0 and not r["bos"]:
            issues.append("alıntılı bulgu yok")
        L.append(f"| {r['dosya']} | {r['bulgu']} | {len(r['kaynaksiz'])} | {len(r['urls'])} | {len(hosts)} | {'; '.join(issues) or '—'} |")
    L.append("")
    if publisher_info:
        L += ["## Kaynak çeşitliliği (planla uyumlu)", "", *publisher_info, ""]
    unc = [(r["dosya"], f) for r in results for f in r["kaynaksiz"]]
    if unc:
        L += ["## Kaynaksız bulgular (rapora ALMA, Claude bulana kadar boşluk say)", ""]
        L += [f"- `{d}` — {f['metin'][:160]}" for d, f in unc[:25]]
        L.append("")
    if link_checked:
        bad = {u: v for u, v in link_status.items() if v[0] != "ok"}
        L += [f"## Bağlantılar ({len(link_status)} benzersiz, {len(bad)} sorunlu)", ""]
        if bad:
            L += [f"- **{st}** {u} {note}".rstrip() for u, (st, note) in sorted(bad.items(), key=lambda kv: kv[1][0])]
        else:
            L.append("Tüm bağlantılar erişilebilir.")
        L.append("")
        comm = sorted({u for u in link_status if any(c in host(u) for c in COMMUNITY)})
        if comm:
            L += ["Topluluk/ikincil kaynak (tek başına kanıt sayma): " + ", ".join(host(u) for u in comm[:8]), ""]
    L += trust_section(results, hints)
    if github:
        L += [f"## GitHub depoları (gh api ile doğrulandı: {len(github)})", "",
              "| Depo | Durum | ⭐ | Son push | Not |", "|---|---|---:|---:|---|"]
        for g in sorted(github, key=lambda x: -(x.get("yildiz") or 0)):
            push = f"{g['son_push_gun']} gün önce" if g.get("son_push_gun") is not None else "—"
            L.append(f"| {g['repo']} | {g['durum']}{' (fork)' if g.get('fork') else ''} | {g.get('yildiz', '—')} | {push} | {g.get('not', '')} |")
        bad = [g for g in github if g["durum"] in ("yok", "arşivli", "durgun")]
        if bad:
            L += ["", "Dikkat: " + "; ".join(f"{g['repo']} → {g['durum']}" for g in bad)]
        L.append("")
    if candidates:
        L += ["## Doğrulama adayları (Claude kaynağı açıp iddiayı sayfada aramalı)", ""]
        for i, (score, dosya, f) in enumerate(candidates, 1):
            L.append(f"{i}. [{score:+d}] `{dosya}` — {f['metin'][:200]}")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("notlar", help="notların bulunduğu dizin (*.md)")
    ap.add_argument("--cikti", help="raporun yazılacağı dosya (varsayılan: notlar/../denetim.md)")
    ap.add_argument("--link-yok", action="store_true", help="bağlantı canlılık denetimini atla (çevrimdışı)")
    ap.add_argument("--aday", type=int, default=8, help="doğrulama adayı sayısı")
    ap.add_argument("--github-yok", action="store_true", help="GitHub depo doğrulamasını (gh api) atla")
    ap.add_argument("--is", dest="jobs", type=int, default=8, help="eşzamanlı bağlantı kontrolü")
    ap.add_argument("--plan", help="PLAN.json: kaynak ipuçları ve beklenen tek yayımlayıcı alan adı")
    ap.add_argument("--dosyalar", nargs="+", help="yalnız bu not dosyaları (plan dışı eski notlar karışmasın)")
    a = ap.parse_args()

    d = Path(a.notlar)
    files = sorted(p for p in d.glob("*.md") if p.is_file() and (not a.dosyalar or p.name in set(a.dosyalar)))
    if not files:
        print(f"denetle: {d} içinde (seçilen) .md yok", file=sys.stderr)
        return 2
    results = [analyze(p) for p in files]
    link_status = {}
    if not a.link_yok:
        urls = sorted({u for r in results for u in r["urls"]})
        with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
            for url, st, note in pool.map(check_url, urls):
                link_status[url] = (st, note)
    hints = guven.hints_by_slug(a.plan) if a.plan else {}
    candidates = verification_candidates(results, link_status, a.aday, hints)
    github = None if (a.github_yok or a.link_yok) else verify_github(results)
    report = render(results, link_status, candidates, not a.link_yok, github, hints,
                    planned_publishers(a.plan))
    out = Path(a.cikti) if a.cikti else d.parent / "denetim.md"
    out.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n(denetim yazıldı: {out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
