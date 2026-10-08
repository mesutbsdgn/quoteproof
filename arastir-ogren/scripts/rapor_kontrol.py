#!/usr/bin/env python3
"""Rapor düzeyi kaynak kontrolü (0 LLM jetonu, yalnız standart kütüphane).

`dogrula.py` çalışan NOTLARINI denetler. Ama atıf hataları çoğu zaman SENTEZ aşamasında doğar: not doğrudur, rapora yazılırken sayı yanlış özneye yapışır
(8 Eki 2026: makalede "saldırılarımız %43–98 başarı oranına sahip" notta doğruydu; rapor tablosu bunu yalnız "drag-and-drop" varyantına yazdı).
Bu araç NİHAİ raporu (Markdown) öğelere böler (tablo satırı · madde · alıntı bloğu · paragraf) ve şunları denetler:

  hata    tırnak içindeki alıntı, öğenin kendi URL'sindeki sayfada birebir YOK (çeviri/özet tırnağa konmaz)
  uyarı   sayı kaynakta yok (birim/çeviri ya da hesaplanmış sayı olabilir) · sayı kaynakta var ama iddianın özgün terimine UZAK ya da terim o sayfada HİÇ yok
          (bağlam şüphesi; URL'siz öğede yalnız öğenin adını andığı kaynakta, örn. "USENIX 2012") · URL'siz alıntı hiçbir kaynakta yok
          raporun atıf yaptığı URL araştırma notlarında hiç geçmiyor (--notlar)
  bilgi   URL'siz öğenin sayısı raporun atıf yaptığı bir sayfada bulundu (kaynak satırda gösterilmemiş) · güven puanı <50 kaynak

Sezgisel ve kanıt değildir: "temiz" çıktı raporun doğru olduğu anlamına gelmez, yalnız bu hata sınıflarının görülmediğini söyler.

Kullanım: rapor_kontrol.py RAPOR.md [--notlar DIZIN] [--onbellek DIZIN] [--plan PLAN.json] [--cikti kontrol.md] [--is 4] [--siki]
  --siki  hata ya da uyarı varsa çıkış kodu 1 (CI/sentez kapısı); varsayılan 0.
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

sys.dont_write_bytecode = True  # skill dizininde __pycache__/.pyc üretme
sys.path.insert(0, str(Path(__file__).resolve().parent))
import denetle  # noqa: E402
import dogrula  # noqa: E402
import guven  # noqa: E402
import oku  # noqa: E402

BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
TABLE_SEP = re.compile(r"^\|?[\s:|-]+\|?$")
MAX_POOL = 60          # raporun atıf yaptığı en çok bu kadar sayfa havuza alınır
SEV_ORDER = {"hata": 0, "uyarı": 1, "bilgi": 2}


def parse_items(text):
    """Markdown → öğeler [{satir, tur, metin, baslik}]. Kod çitleri atlanır; tablo satırı/madde/alıntı bloğu/paragraf ayrı öğedir."""
    items, cur, kind, heading, fence, start = [], [], None, "", False, 0

    def flush():
        nonlocal cur, kind
        if cur:
            items.append({"satir": start, "tur": kind, "metin": re.sub(r"\s+", " ", " ".join(cur)).strip(), "baslik": heading})
        cur, kind = [], None

    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            fence = not fence
            continue
        if fence:
            continue
        if not stripped:
            flush()
            continue
        if stripped.startswith("#"):
            flush()
            heading = stripped.lstrip("# ").strip()
            continue
        if stripped.startswith("|"):
            flush()
            if TABLE_SEP.fullmatch(stripped) and "-" in stripped:
                continue
            items.append({"satir": n, "tur": "tablo", "metin": stripped.strip("|").strip(), "baslik": heading})
            continue
        if stripped.startswith(">"):
            if kind != "alinti":
                flush()
                kind, start = "alinti", n
            cur.append(stripped[1:].strip())
            continue
        if BULLET.match(line):
            flush()
            kind, start = "madde", n
            cur.append(BULLET.sub("", line, count=1))
            continue
        if kind is None:
            kind, start = "paragraf", n
        cur.append(stripped)
    flush()
    return items


def normalize_url(url):
    u = urlparse(url.strip().rstrip(".,;)"))
    path = u.path.rstrip("/")
    return f"{u.netloc.lower().removeprefix('www.')}{path}" + (f"?{u.query}" if u.query else "")


def _finding(sev, kind, msg, num=None):
    return {"seviye": sev, "tur": kind, "mesaj": msg, "sayi": num}


def merge_findings(findings):
    """Aynı seviye/tür/gerekçeye sahip sayı bulgularını tek satıra indirir: "sayı '2012', '%43' ..." (gürültüyü azaltır)."""
    merged, order = {}, []
    for f in findings:
        if f.get("sayi") is None:
            order.append(f)
            continue
        key = (f["seviye"], f["tur"], f["mesaj"].replace(repr(f["sayi"]), "{}"))
        if key not in merged:
            merged[key] = {**f, "sayilar": [f["sayi"]]}
            order.append(merged[key])
        else:
            merged[key]["sayilar"].append(f["sayi"])
    out = []
    for f in order:
        if f.get("sayilar"):
            if len(f["sayilar"]) > 1:
                f = {**f, "mesaj": f["mesaj"].replace(repr(f["sayi"]), ", ".join(repr(n) for n in f["sayilar"]), 1).replace("sayı ", "sayılar ", 1)}
            f = {k: v for k, v in f.items() if k != "sayilar"}
        out.append(f)
    return out


IDENT_PREFIX_RE = re.compile(r"(?i)\b(?:RFC|FIPS|ISO(?:/IEC)?|IEC|SP|CVE|CWE|CAPEC|BCP|STD|AML\.T)[\s\-]*(?:\d+[-.])*$")


def is_identifier_number(text, num):
    """Sayının metindeki HER geçişi bir belge/kayıt numarası bağlamındaysa (RFC 9309, FIPS 203, CVE-2024-1234) True."""
    spans = [m.start() for m in re.finditer(re.escape(str(num).lstrip("v")), text)]
    return bool(spans) and all(IDENT_PREFIX_RE.search(text[:s]) for s in spans)


def host_label(url):
    """'www.usenix.org' → 'usenix'; 'news.cgtn.com' → 'cgtn' (≥4 harf değilse None)."""
    parts = [p for p in urlparse(url).netloc.lower().removeprefix("www.").split(".") if p]
    parts = parts[:-1] if len(parts) > 1 else parts          # TLD'yi at
    label = parts[-1] if parts else ""
    return label if len(label) >= 4 and label not in {"news", "blog", "docs", "info"} else None


def check_item(item, pool, bases, own_urls, readable_pool, all_readable=None):
    """Tek öğe için bulgular. pool: {url: sayfa(+_varyant)}, bases: {url: normalize metin}.

    Kapsam kuralı: öğenin KENDİ URL'si varsa her kontrol yalnız o sayfalarda yapılır. URL'siz öğede sayı/alıntı varlığı raporun tüm havuzunda aranır,
    ama bağlam kontrolleri (özgün terim yakınlığı / terim sayfada yok) yalnız öğenin ADINI andığı kaynakta ("USENIX 2012") yapılır: URL'siz öğede alakasız bir
    sayfada rastlantısal sayı eşleşmesi yanlış alarm üretirdi (ölçüldü)."""
    out = []
    ev = dogrula.evidence(item["metin"])
    own_ok = [u for u in own_urls if u in pool and pool[u]["ok"]]
    has_own = bool(own_urls)
    presence = own_ok if has_own else readable_pool
    named = own_ok if has_own else [u for u in readable_pool if (host_label(u) or "\0") in item["metin"].lower()]
    if not presence:
        return out
    all_readable = all_readable if all_readable is not None else readable_pool

    # 1) alıntı bloğu / tırnaklı alıntı: kaynakta birebir olmalı (tırnak = "birebir" iddiasıdır; çeviri/özet tırnağa konmaz)
    if ev["alinti"]:
        quotes_only = {"alinti": ev["alinti"], "kod": [], "sayi": []}
        verdicts = [dogrula.judge(quotes_only, pool[u]["_varyant"])[0] for u in presence]
        if "Doğrulandı" not in verdicts:
            where = "öğenin kendi URL'sindeki sayfada" if has_own else "raporun atıf yaptığı hiçbir sayfada"
            out.append(_finding("hata" if has_own else "uyarı", "alıntı-yok",
                                f"tırnak içindeki alıntı {where} birebir bulunamadı (çeviri/özet ise tırnak kullanma): “{ev['alinti'][0][:80]}”"))

    # 2) sayılar (alıntı/kod dışındaki): kaynakta var mı; iddianın özgün terimine yakın mı?
    quote_norm = " ".join(dogrula.norm(q) for q in ev["alinti"])
    technical = dogrula.technical_terms(item["metin"], quote_norm)
    for num in ev["sayi"]:
        located = [(u, dogrula.number_positions(bases[u], num)) for u in presence]
        located = [(u, pos) for u, pos in located if pos]
        if not located and is_identifier_number(item["metin"], num):
            continue   # "RFC 9309", "FIPS 203", "CVE-2024-1234": belge/kayıt numarası, ölçülen bir değer değil → "sayı yok" uyarısı gürültü
        if not located:
            where = "öğenin kendi URL'sindeki sayfada" if has_own else "raporun atıf yaptığı hiçbir sayfada"
            hint = " (birim/çeviri ya da türetilmiş/hesaplanmış bir sayı olabilir)"
            out.append(_finding("uyarı", "sayı-yok", f"sayı {num!r} {where} bulunamadı{hint}", num))
            continue
        judged = [(u, pos) for u, pos in located if u in named]
        if not judged:   # URL'siz ve adı anılan kaynak yok: bağlam yargılanamaz; yalnız kaynağı göster
            out.append(_finding("bilgi", "kaynak-gösterilmemiş",
                                f"sayı {num!r} satırda kaynaksız; atıf yapılan bir sayfada bulundu ({urlparse(located[0][0]).netloc})", num))
            continue
        near_any, unknown_any, far, missing = False, False, [], []
        for u, pos in judged:
            anchors = dogrula.anchor_positions(item["metin"], bases[u], quote_norm, u)
            if anchors:
                targets = [(p, p + len(num)) for p in pos]
                dist = {tok: dogrula.anchor_distance(h, targets) for tok, h in anchors.items()}
                if min(dist.values()) <= dogrula.CONTEXT_WINDOW:
                    near_any = True
                    break
                far.append((u, dist))
                continue
            absent_here = [tok for tok in technical if not dogrula.term_on_page(pool[u]["_varyant"], tok)]
            # "sayfada hiç yok" yalnız terim raporun/notların BAŞKA bir sayfasında geçiyorsa anlamlı: hiçbir sayfada yoksa Türkçe tireli sözcük
            # ("lityum-iyon", "son-mil") olabilir → sus
            elsewhere = [tok for tok in absent_here if any(dogrula.term_on_page(pool[o]["_varyant"], tok) for o in all_readable if o != u)]
            if technical and elsewhere and len(absent_here) == len(technical):
                missing.append((u, elsewhere))
            else:
                unknown_any = True               # yargılanacak özgün terim yok: susmak yanlış alarmdan iyidir
        if near_any or unknown_any or not (far or missing):
            continue
        if far:
            u, dist = min(far, key=lambda x: min(x[1].values()))
            terms = ", ".join(f"'{tok}' ({d} karakter uzakta)" for tok, d in sorted(dist.items(), key=lambda kv: kv[1])[:3])
            out.append(_finding("uyarı", "bağlam-şüphesi",
                                f"sayı {num!r} {urlparse(u).netloc} sayfasında var ama iddianın özgün terim(ler)i {terms}: ±{dogrula.CONTEXT_WINDOW} karakter dışında; "
                                "sayının hangi konuya ait olduğunu kaynakta elle doğrula", num))
        else:
            u, terms = missing[0]
            out.append(_finding("uyarı", "terim-sayfada-yok",
                                f"sayı {num!r} {urlparse(u).netloc} sayfasında var ama iddianın özgün terimi {', '.join(repr(x) for x in terms[:3])} bu sayfada HİÇ geçmiyor, "
                                "kaynaklarda başka yerde geçiyor; sayının bu konuya ait olduğunu kaynakta elle doğrula", num))
    return out


def run(report_text, cache_dir=None, notes_urls=None, hints=None, jobs=4, loader=None):
    loader = loader or (lambda u: oku.load(u, cache_dir=cache_dir))
    items = parse_items(report_text)
    item_urls = [[u.rstrip(".,;)") for u in denetle.bullet_urls(it["metin"])] for it in items]
    all_urls = list(dict.fromkeys(u for urls in item_urls for u in urls))[:MAX_POOL]
    note_only = [u for u in dict.fromkeys(notes_urls or []) if u not in all_urls][:MAX_POOL]   # yalnız "terim başka sayfada geçiyor mu" için
    pool = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for u, page in zip(all_urls + note_only, ex.map(loader, all_urls + note_only)):
            pool[u] = page
    for u, p in list(pool.items()):
        if p["ok"]:   # satır sonu tireleme varyantlarıyla genişletilmiş metin: terim "sayfada hiç yok" demeden önce "drag-\nand-drop" da sayılsın
            pool[u] = {**p, "_varyant": dogrula.page_text_norm(p["markdown"])}
    bases = {u: dogrula.norm(p["markdown"]) for u, p in pool.items() if p["ok"]}
    readable = [u for u in all_urls if pool[u]["ok"]]
    all_readable = [u for u in pool if pool[u]["ok"]]
    results = []
    for it, urls in zip(items, item_urls):
        findings = check_item(it, pool, bases, urls, readable, all_readable) if (urls or readable) else []
        results.append({**it, "urls": urls, "bulgular": merge_findings(findings)})
    extra = []
    unreadable = [u for u in all_urls if not pool[u]["ok"]]
    if notes_urls is not None:
        known = {normalize_url(u) for u in notes_urls}
        for u in all_urls:
            if normalize_url(u) not in known:
                extra.append(_finding("uyarı", "notlarda-yok", f"raporun atıf yaptığı URL araştırma notlarında hiç geçmiyor (uydurma/sonradan eklenmiş olabilir): {u}"))
    for u in all_urls:
        score = guven.score(u, hints)
        if score["puan"] < 50:
            extra.append(_finding("bilgi", "zayıf-kaynak", f"zayıf kaynak ({score['sinif']}, {score['puan']}): {u}"))
    return {"ogeler": results, "ekstra": extra, "url_sayisi": len(all_urls), "okunamayan": unreadable, "oge_sayisi": len(items)}


def summarize(res):
    counts = {"hata": 0, "uyarı": 0, "bilgi": 0}
    for r in res["ogeler"]:
        for f in r["bulgular"]:
            counts[f["seviye"]] += 1
    for f in res["ekstra"]:
        counts[f["seviye"]] += 1
    return counts


def render(res, rapor_adi):
    c = summarize(res)
    L = [f"# Rapor düzeyi kaynak kontrolü — {rapor_adi}", "",
         f"Özet: **{c['hata']} hata · {c['uyarı']} uyarı · {c['bilgi']} bilgi** ({res['oge_sayisi']} öğe, {res['url_sayisi']} benzersiz kaynak, "
         f"{len(res['okunamayan'])} sayfa okunamadı).",
         "", "Sezgiseldir: temiz çıktı raporun doğru olduğunu değil, bu hata sınıflarının görülmediğini söyler. "
         "Not düzeyindeki doğrulama (`dogrula.py`) sentezde doğan sayı–özne atıf hatalarını göremez; bu araç onların bir kısmını yakalar.", ""]
    flagged = [r for r in res["ogeler"] if r["bulgular"]]
    flagged.sort(key=lambda r: (min(SEV_ORDER[f["seviye"]] for f in r["bulgular"]), r["satir"]))
    if flagged:
        L += ["## Öğe bulguları", ""]
        for r in flagged:
            L.append(f"- **satır {r['satir']}** ({r['tur']}) — {r['metin'][:150]}")
            for f in sorted(r["bulgular"], key=lambda f: SEV_ORDER[f["seviye"]]):
                L.append(f"  - **{f['seviye']}** `{f['tur']}`: {f['mesaj']}")
        L.append("")
    if res["ekstra"]:
        L += ["## Kaynak/atıf bulguları", ""]
        L += [f"- **{f['seviye']}** `{f['tur']}`: {f['mesaj']}" for f in sorted(res["ekstra"], key=lambda f: SEV_ORDER[f["seviye"]])]
        L.append("")
    if res["okunamayan"]:
        L += ["## Okunamayan kaynaklar (bu sayfalara bağlı öğeler denetlenemedi)", ""] + [f"- {u}" for u in res["okunamayan"]] + [""]
    if not flagged and not res["ekstra"]:
        L += ["Hiçbir bulgu yok.", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rapor", help="nihai rapor (Markdown)")
    ap.add_argument("--notlar", help="araştırma notları dizini: rapordaki URL'ler orada geçiyor mu?")
    ap.add_argument("--onbellek", help="sayfa deposu (varsayılan: rapor dizini/kaynaklar)")
    ap.add_argument("--plan", help="PLAN.json (kaynak güven puanı ipuçları)")
    ap.add_argument("--cikti", help="kontrol raporunun yazılacağı dosya (varsayılan: rapor dizini/rapor-kontrol.md)")
    ap.add_argument("--is", dest="jobs", type=int, default=4)
    ap.add_argument("--siki", action="store_true", help="hata ya da uyarı varsa çıkış kodu 1")
    a = ap.parse_args()
    path = Path(a.rapor)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"rapor_kontrol: rapor okunamadı: {e}", file=sys.stderr)
        return 2
    notes_urls = None
    if a.notlar:
        notes_urls = [u for p in sorted(Path(a.notlar).glob("*.md")) for u in denetle.analyze(p)["urls"]]
    hints = guven.hints_by_slug(a.plan).get("*") if a.plan else None
    cache = a.onbellek or str(path.parent / "kaynaklar")
    res = run(text, cache_dir=cache, notes_urls=notes_urls, hints=hints, jobs=a.jobs)
    report = render(res, path.name)
    out = Path(a.cikti) if a.cikti else path.parent / "rapor-kontrol.md"
    out.write_text(report + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report)
    print(f"(kontrol yazıldı: {out})")
    counts = summarize(res)
    return 1 if a.siki and (counts["hata"] or counts["uyarı"]) else 0


if __name__ == "__main__":
    sys.exit(main())
