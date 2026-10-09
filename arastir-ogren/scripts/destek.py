#!/usr/bin/env python3
"""İddia–kanıt destek kontrolü: notun Özet ve Çıkarımlar cümleleri, kendi alıntılarıyla ve atıf yaptığı sayfalarla destekleniyor mu? (0 LLM jetonu, yalnız standart kütüphane)

Neden: `dogrula.py` her BULGUNUN alıntısını sayfada arar; ama bulgu satırındaki "iddia" çoğu zaman kısa bir etikettir ("Bakım takvimi", "Risk") ve asıl içeriği alıntıdır.
Gerçek desteksiz iddia Özet/Çıkarımlar cümlelerinde doğar: çalışan kaynakta olmayan bir sayıyı, tarihi ya da sürüm/ürün adını özete yazar, ya da doğrulanamadığı için
temizlenen bir bulguya dayanan cümle olduğu gibi kalır. Bu araç o cümleleri tarar ve her SOMUT öğeyi (sayı, tarih, X25519/ML-KEM-768 gibi tanımlayıcı, BÜYÜKHARF kısaltma)
üç katmanda arar; model çağrısı yoktur:

  alıntıda        öğe, aynı sorunun "Alıntılı bulgular" maddelerinde (alıntı + iddia metni) geçiyor        → destekli (sessiz)
  sayfada         alıntılarda yok ama sorunun atıf yaptığı bir sayfada geçiyor                              → bilgi: kanıt alıntıda değil, sayfada
  başka sayfada   bu sorunun sayfalarında yok, notun başka sorusunun sayfalarında geçiyor                  → uyarı: öğe yanlış soruya/özneye yapışmış olabilir
  hiçbir yerde    notun atıf yaptığı hiçbir sayfada yok                                                     → uyarı (güçlü): uydurma, çeviri ya da hesaplanmış değer olabilir

Gürültüyü azaltan kurallar: belge/kayıt numaraları (RFC 9309, FIPS 203, CVE-…), harfe/tireye bitişik rakamlar (X25519, SHA-256, ML-KEM-768) tek TANIMLAYICI sayılır (rakamı ayrı aranmaz),
çalıştırma günü ve not dosyasının tarihi, Türkçe/İngilizce ay adları (Mart 2026 ↔ March 2026 ↔ 2026-03) eşlenir, "(çıkarım)" cümlelerinde yalnız somut öğe aranır.
Sezgiseldir ve kanıt değildir: yalnız SOMUT öğeleri sınar, cümlenin anlamının kaynakla örtüştüğünü söylemez; "temiz" çıktı iddianın doğru olduğu anlamına gelmez.
Not düzeyindeki bu denetim nihai rapor için `rapor_kontrol.py`'nin yerine geçmez (rapor sentezinde doğan atıf hataları orada aranır).

Kullanım: destek.py NOT_DIZINI [--onbellek DIZIN] [--cikti destek.md] [--dosyalar a.md b.md] [--siki]
  --siki  "hiçbir yerde" bulgusu varsa çıkış kodu 1; varsayılan 0.
"""
import argparse
import datetime
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import denetle  # noqa: E402
import dogrula  # noqa: E402
import oku  # noqa: E402

SECTIONS_CHECKED = ("Özet", "Çıkarımlar")
SEV = {"hiçbir-yerde": "uyarı", "başka-sayfada": "uyarı", "sayfada": "bilgi", "okunamayan-sayfa-var": "bilgi"}
SEV_ORDER = {"uyarı": 0, "bilgi": 1}
MAX_PAGES_PER_NOTE = 40

TR_MONTHS = {"ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6, "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12}
EN_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
MONTH_NAMES = "|".join(sorted(list(TR_MONTHS) + EN_MONTHS, key=len, reverse=True))
DATE_RES = [
    re.compile(rf"(?P<d>\d{{1,2}})\s+(?P<m>{MONTH_NAMES})\w*\s+(?P<y>(?:19|20)\d{{2}})", re.I),            # 24 Mart 2026
    re.compile(rf"(?P<m>{MONTH_NAMES})\w*\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>(?:19|20)\d{{2}})", re.I),   # March 24, 2026
    re.compile(rf"(?P<m>{MONTH_NAMES})\w*\s+(?P<y>(?:19|20)\d{{2}})", re.I),                                  # Mart 2026
    re.compile(r"(?P<y>(?:19|20)\d{2})-(?P<mn>\d{2})(?:-(?P<d>\d{2}))?(?!\d)"),                             # 2026-03(-24)
]
IDENT_RE = re.compile(r"(?<![\w.-])(?:[A-Za-z]+[-_]?)*[A-Za-z]*\d[\w-]*(?:[A-Za-z]+\d[\w-]*)*(?![\w])")
DOC_ID_RE = re.compile(r"(?<![\w-])(?:RFC|FIPS|PEP|JEP|KEP|CVE|CWE|CAPEC|BCP|ISO(?:/IEC)?|IEC|SP|STD)[\s-]*\d+(?:[.-]\d+)*", re.I)
ACRONYM_RE = re.compile(r"(?<![\w-])[A-Z][A-Z0-9]{2,}(?:-[A-Z0-9]+)*(?![\w-])")
COMMON_ACRONYMS = {"ABD", "AB", "TL", "USD", "EUR", "API", "URL", "HTTP", "HTTPS", "JSON", "HTML", "CSS", "PDF", "SSL", "AND", "THE", "TBD", "OK", "ILE", "ICIN"}
HEDGE_RE = re.compile(r"(?i)\(çıkarım[^)]*\)|çıkarım:")
NUM_CORE = re.compile(r"(?i:\d+(?:[.,]\d+)?\s?(?:KB|MB|GB)(?![\w]))|%\s?\d+(?:[.,]\d+)?(?:\s?[-–]\s?\d+(?:[.,]\d+)?)?|\d+(?:[.,]\d+)?\s?[-–]\s?\d+(?:[.,]\d+)?\s?%?|\d+(?:[.,]\d+)+|\d{1,3}(?:[.,]\d{3})+|\d{3,}|\d+\s?(?:x|×|%|kat|ms|sn|saniye|MB|GB|KB|TL|USD|EUR)(?![\w])")
GENERIC = {"2024", "2025", "2026", "2027", "2028"}
HTTP_STATUS = {"400", "401", "403", "404", "410", "429", "500", "502", "503", "504"}   # çalışanın "sayfa 404 verdi" demesi kaynağın değil getirmenin durumudur


def _strip_links(text):
    text = re.sub(r"\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)", r"\1", text)
    return re.sub(r"https?://\S+", " ", text)


def sentences(lines):
    """Bölüm satırlarından cümle/madde listesi: madde işaretleri atılır, paragraf satırları nokta sonrası bölünür (sürüm/ondalık noktası bölmez)."""
    out = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith(("```", "|", ">", "#")) or re.fullmatch(r"[-–—*\s]*", s) or s.startswith("(belirtilmedi"):
            continue
        s = denetle.BULLET_RE.sub("", s)
        for part in re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ\"“(])", s):
            part = part.strip()
            if len(part) >= 12:
                out.append(part)
    return out


def today_dates(note_path):
    ds = {datetime.date.today()}
    try:
        ds.add(datetime.date.fromtimestamp(Path(note_path).stat().st_mtime))
    except OSError:
        pass
    return ds


def month_forms(month_no):
    en = EN_MONTHS[month_no - 1]
    tr = next(k for k, v in TR_MONTHS.items() if v == month_no)
    return {en, en[:3], tr, f"{month_no:02d}", str(month_no)}


def parse_dates(text, skip):
    """(tarih öğeleri, tarihleri çıkarılmış metin). Öğe: {"etiket", "y", "m", "d"}; çalıştırma günü ve not tarihi sessizce atılır."""
    found, rest = [], text
    for rx in DATE_RES:
        def take(m, rx=rx):
            gd = m.groupdict()
            month = int(gd["mn"]) if gd.get("mn") else (TR_MONTHS.get(gd["m"].lower()) or next((i + 1 for i, e in enumerate(EN_MONTHS) if e.startswith(gd["m"].lower()[:3])), None) if gd.get("m") else None)
            if month is None or not 1 <= month <= 12:
                return m.group(0)
            day = int(gd["d"]) if gd.get("d") else None
            try:
                if day and datetime.date(int(gd["y"]), month, day) in skip:
                    return " "
            except ValueError:
                return m.group(0)
            if not day and any((d.year, d.month) == (int(gd["y"]), month) for d in skip):
                return " "      # "bugün (2026-10)": çalıştırma ayı bir iddia değildir
            found.append({"etiket": m.group(0).strip(), "y": gd["y"], "m": month, "d": day})
            return " "
        rest = rx.sub(take, rest)
    return found, rest


def concrete_items(sentence, skip):
    """Cümledeki denetlenebilir somut öğeler: [{"tur": sayi|tarih|tanim|kisaltma, "etiket", "ara": ...}]."""
    s = _strip_links(sentence)
    s = dogrula.META_TAG_RE.sub(" ", s)
    s = re.sub(r'"[^"]*"|[“«][^”»]*[”»]|`[^`]*`', " ", s)                      # tırnak/kod içi: kullanıcının aktardığı alıntı, ayrıca doğrulanır
    dates, rest = parse_dates(s, skip)
    items = [{"tur": "tarih", "etiket": d["etiket"], "ara": d} for d in dates]
    taken = []

    def mask(m):
        taken.append((m.start(), m.end()))

    for m in DOC_ID_RE.finditer(rest):                                          # "PEP 703", "RFC 9309", "FIPS 203": belge numarası, ölçülen değer değil → tanımlayıcı olarak ara
        mask(m)
        items.append({"tur": "tanim", "etiket": re.sub(r"\s+", " ", m.group(0)), "ara": re.sub(r"\s+", " ", m.group(0))})
    for m in IDENT_RE.finditer(rest):                                           # X25519, ML-KEM-768, SHA-256: harf+rakam birleşimi tek tanımlayıcıdır
        tok = m.group(0)
        if not re.search(r"[A-Za-z]", tok) or not re.search(r"\d", tok) or any(a <= m.start() < b for a, b in taken):
            continue
        mask(m)
        items.append({"tur": "tanim", "etiket": tok, "ara": tok})
    masked = rest
    for a, b in sorted(taken, reverse=True):
        masked = masked[:a] + " " * (b - a) + masked[b:]
    for m in ACRONYM_RE.finditer(masked):
        tok = m.group(0)
        if tok in COMMON_ACRONYMS:
            continue
        items.append({"tur": "kisaltma", "etiket": tok, "ara": tok})
    for m in NUM_CORE.finditer(masked):
        raw = m.group(0).strip()
        tok = dogrula.norm(raw).replace(" ", "")
        if tok in GENERIC or tok in HTTP_STATUS or not re.search(r"\d", tok):
            continue
        items.append({"tur": "sayi", "etiket": raw, "ara": tok})
    seen, out = set(), []
    for it in items:
        key = (it["tur"], str(it["ara"]))
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def range_variants(tok):
    """'%5-10' → '5-10%' sayfa yazımı; '5-10' → '5-10 %'."""
    m = re.fullmatch(r"%?(\d+(?:[.,]\d+)?)-(\d+(?:[.,]\d+)?)%?", tok)
    if not m:
        return []
    a, b = m.groups()
    return [f"{a}-{b}%", f"{a}-{b} %", f"{a}-{b}", f"{a} to {b}", f"{a}% to {b}%", f"{a}% - {b}%", f"{a}-{b} percent"]


def derived_size(text_norm, value, unit):
    v = float(value.replace(",", "."))
    places = len(value.replace(",", ".").split(".")[1]) if re.search(r"[.,]\d", value) else 0
    tol = 0.5 * 10 ** -places
    power = {"kb": 1, "mb": 2, "gb": 3}[unit]
    for m in re.finditer(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?![\w])|(?<![\w.,])\d{3,}(?![\w.,])", text_norm):
        n = float(m.group(0).replace(",", ""))
        if any(abs(n / base ** power - v) <= tol for base in (1000, 1024)):
            return True
    return False


def present(item, text_norm):
    if not text_norm:
        return False
    kind, key = item["tur"], item["ara"]
    if kind == "tarih":
        d = key
        if d["y"] not in text_norm:
            return False
        if not any(re.search(rf"(?<![\w]){re.escape(f)}(?![a-z])", text_norm) for f in month_forms(d["m"]) if not f.isdigit()) and \
                not re.search(rf"{d['y']}-{d['m']:02d}|{d['m']:02d}/{d['y']}", text_norm):
            return False
        return d["d"] is None or re.search(rf"(?<![\d]){d['d']}(?![\d])", text_norm) is not None
    if kind in ("tanim", "kisaltma"):
        t = dogrula.norm(key)
        pattern = r"(?<![\w-])" + re.escape(t).replace(r"\-", r"[-\s]?").replace(r"\ ", r"[-\s]*") + r"(?![\w])"
        return re.search(pattern, text_norm) is not None
    tok = key
    if dogrula.number_positions(text_norm, tok):
        return True
    size = re.fullmatch(r"(\d+(?:[.,]\d+)?)(kb|mb|gb)", tok)
    if size:   # "~2.2 KB": sayfa bayt yazar ("2,249"); birim çevirisi (1000 ya da 1024 tabanı) kanıt sayılır
        return derived_size(text_norm, size.group(1), size.group(2))
    if any(v in text_norm for v in range_variants(tok)):
        return True
    m = re.fullmatch(r"(%?)(\d+(?:[.,]\d+)?)-(\d+(?:[.,]\d+)?)(%?)", tok)
    if m:   # "%1-8" aralığı sayfada iki ayrı uç değer olarak yazılmış olabilir ("about 1% on macOS … to 8% on Linux"): iki uç da varsa destekli
        pct = "%" if (m.group(1) or m.group(4)) else ""
        return all(dogrula.number_positions(text_norm, pct + end) for end in (m.group(2), m.group(3)))
    return False


APOSTROPHE_RE = re.compile(r"(?<=\d)['’](?=[A-Za-zÇĞİÖŞÜçğıöşü])")


def _norm(text):
    """norm() kesme işaretini siler ("3.14'te" → "3.14te") ve sayı sınırını bozar; rakamdan sonraki ek kesmesi boşluğa çevrilir."""
    return dogrula.norm(APOSTROPHE_RE.sub(" ", text))


def _line_search_text(line):
    body = denetle.BULLET_RE.sub("", line.strip())
    body = dogrula.META_TAG_RE.sub(" ", body)
    return _norm(_strip_links(body))


def check_question(q, title, skip, all_note_pages):
    """Bir sorunun Özet/Çıkarımlar cümlelerini sına. Döner: {"cumleler": [...], "sayfa_sayisi": n, "okunamayan": [...]}."""
    quote_text = " ".join(_line_search_text(l) for l in q["bolumler"].get("Alıntılı bulgular", []) if denetle.BULLET_RE.match(l.strip()))
    quote_text = _norm(f"{title} {q['baslik']}") + " " + quote_text   # konu başlığındaki ad/sürüm ("Python 3.14") iddia değil, verilmiştir
    urls = []
    for lines in q["bolumler"].values():
        for l in lines:
            urls += [u.rstrip(".,;)") for u in denetle.bullet_urls(l)]
    urls = list(dict.fromkeys(urls))[:MAX_PAGES_PER_NOTE]
    read_text = " \n ".join(all_note_pages.get(u, "") for u in urls)
    page_text = read_text + " \n " + " ".join(u.lower() for u in urls)   # adres dizgisi de kanıt: /howto/ , /pep-0779/ adlandırır
    other_text = " \n ".join(t for u, t in all_note_pages.items() if u not in urls)
    unreadable = [u for u in urls if not all_note_pages.get(u)]
    out = []
    for sec in SECTIONS_CHECKED:
        for sent in sentences(q["bolumler"].get(sec, [])):
            inferred = bool(HEDGE_RE.search(sent))
            findings = []
            for it in concrete_items(sent, skip):
                if present(it, quote_text):
                    continue
                if present(it, page_text):
                    kind = "sayfada"
                elif unreadable and not read_text.strip():
                    continue      # bu sorunun hiçbir sayfası okunamadı: "yok" denemez
                elif present(it, other_text):
                    kind = "başka-sayfada"
                else:
                    kind = "okunamayan-sayfa-var" if unreadable else "hiçbir-yerde"   # okunamayan sayfa varken "hiçbir yerde" denemez: sayı orada olabilir
                if it["tur"] == "kisaltma" and kind not in ("hiçbir-yerde", "okunamayan-sayfa-var"):
                    continue      # kısaltma zayıf sinyal: yalnız hiçbir sayfada yoksa söylenir
                findings.append({"seviye": SEV[kind], "tur": kind, "oge": it["etiket"], "oge_turu": it["tur"]})
            if findings:
                out.append({"bolum": sec, "cumle": sent, "cikarim": inferred, "bulgular": findings})
    return {"cumleler": out, "sayfa_sayisi": len(urls), "okunamayan": unreadable}


def load_pages(notes, cache_dir, jobs=4, loader=None):
    """Notların atıf yaptığı tüm sayfalar {url: normalize metin ("" = okunamadı)}."""
    loader = loader or (lambda u: oku.load(u, cache_dir=cache_dir))
    urls = []
    for _, questions in notes:
        for q in questions:
            for lines in q["bolumler"].values():
                for l in lines:
                    urls += [u.rstrip(".,;)") for u in denetle.bullet_urls(l)]
    urls = list(dict.fromkeys(urls))
    pages = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for u, p in zip(urls, ex.map(loader, urls)):
            pages[u] = dogrula.page_text_norm(APOSTROPHE_RE.sub(" ", p["markdown"])) if p.get("ok") and not dogrula.thin_page(p) else ""
    return pages


def run(notes_dir, cache_dir=None, files=None, jobs=4, loader=None):
    paths = sorted(p for p in Path(notes_dir).glob("*.md") if p.name != "DISLANAN.md" and (files is None or p.name in set(files)))
    parsed = [(p, denetle.parse_note(p)[1]) for p in paths]
    pages = load_pages([(p, qs) for p, qs in parsed], cache_dir, jobs, loader)
    res = {}
    for p, questions in parsed:
        skip = today_dates(p)
        title = next((l[2:].strip() for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("# ")), "")
        note_urls = {u.rstrip(".,;)") for q in questions for lines in q["bolumler"].values() for l in lines for u in denetle.bullet_urls(l)}
        note_pages = {u: t for u, t in pages.items() if u in note_urls}
        qs = []
        for q in questions:
            r = check_question(q, title, skip, note_pages)
            qs.append({"soru": q["baslik"], **r})
        sent_total = sum(len(sentences(q["bolumler"].get(s, []))) for q in questions for s in SECTIONS_CHECKED)
        res[p.stem] = {"sorular": qs, "cumle_sayisi": sent_total}
    return res


def summarize(res):
    c = {"uyarı": 0, "bilgi": 0, "cumle": 0, "isaretli": 0}
    for r in res.values():
        c["cumle"] += r["cumle_sayisi"]
        for q in r["sorular"]:
            c["isaretli"] += len(q["cumleler"])
            for s in q["cumleler"]:
                for f in s["bulgular"]:
                    c[f["seviye"]] += 1
    return c


def strong_count(res):
    return sum(1 for r in res.values() for q in r["sorular"] for s in q["cumleler"] for f in s["bulgular"] if f["tur"] == "hiçbir-yerde")


def render(res):
    c = summarize(res)
    L = ["# İddia–kanıt destek kontrolü (Özet ve Çıkarımlar cümleleri)", "",
         f"Özet: {c['cumle']} cümleden **{c['isaretli']}** tanesinde somut öğe (sayı, tarih, tanımlayıcı, kısaltma) alıntılarda yok: **{c['uyarı']} uyarı · {c['bilgi']} bilgi**.",
         "", "Katmanlar: `hiçbir-yerde` = notun atıf yaptığı hiçbir sayfada yok (güçlü) · `başka-sayfada` = yalnız notun başka sorusunun sayfasında var · "
         "`sayfada` = alıntıda yok ama bu sorunun sayfasında var (kanıt alıntıya taşınmamış). Yalnız somut öğeleri sınar; cümlenin anlamının kaynakla örtüştüğünü söylemez. "
         "Sezgiseldir: türetilmiş/hesaplanmış değer, birim çevirisi ya da çeviri farkı yanlış alarm verebilir.", ""]
    any_flag = False
    for slug, r in res.items():
        block = []
        for q in r["sorular"]:
            for s in q["cumleler"]:
                block.append(f"- **{q['soru'][:60]} / {s['bolum']}**{' (çıkarım)' if s['cikarim'] else ''} — {s['cumle'][:200]}")
                for f in sorted(s["bulgular"], key=lambda f: SEV_ORDER[f["seviye"]]):
                    block.append(f"  - **{f['seviye']}** `{f['tur']}`: {f['oge_turu']} `{f['oge']}`")
            if q["okunamayan"]:
                block.append(f"- ({q['soru'][:40]}) okunamayan {len(q['okunamayan'])} sayfa: bu sayfalara bağlı öğeler denetlenemedi")
        if block:
            any_flag = True
            L += [f"## {slug}", ""] + block + [""]
    if not any_flag:
        L += ["Hiçbir bulgu yok.", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("notlar", help="not dizini (notlar-temiz/ önerilir: doğrulanamayan bulgular çıkarılmıştır)")
    ap.add_argument("--onbellek", help="sayfa deposu (varsayılan: not dizininin yanındaki kaynaklar)")
    ap.add_argument("--cikti", help="rapor dosyası (varsayılan: ekrana)")
    ap.add_argument("--json", help="makine okur sonuç dosyası")
    ap.add_argument("--dosyalar", nargs="*")
    ap.add_argument("--is", dest="jobs", type=int, default=4)
    ap.add_argument("--siki", action="store_true")
    a = ap.parse_args(argv)
    d = Path(a.notlar)
    if not d.is_dir():
        print(f"destek: dizin yok: {d}", file=sys.stderr)
        return 2
    cache = a.onbellek or str(d.resolve().parent / "kaynaklar")
    res = run(d, cache_dir=cache, files=a.dosyalar, jobs=a.jobs)
    text = render(res)
    if a.cikti:
        Path(a.cikti).write_text(text, encoding="utf-8")
    else:
        print(text)
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if a.siki and strong_count(res) else 0


if __name__ == "__main__":
    sys.exit(main())
