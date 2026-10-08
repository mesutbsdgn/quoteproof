#!/usr/bin/env python3
"""İddia–kaynak otomatik doğrulama (0 LLM jetonu, yalnız standart kütüphane).

Araştırma notlarındaki "Alıntılı bulgular" maddelerinden kanıt dizgilerini (tırnak içi alıntılar, `kod` parçaları, rakam/sürüm/tarih)
çıkarır; maddenin kendi URL'lerini oku.py ile çekip bu dizgilerin sayfada GERÇEKTEN geçip geçmediğini denetler.

Kararlar:
  Doğrulandı   TÜM kanıt dizgileri sayfada bulundu (metinsel eşleşme; anlamı Claude denetler)
  Kısmen       kanıtın bir kısmı bulundu (eksikler raporda)
  Bulunamadı   kanıtın çoğu sayfada yok
  Erişilemedi  sayfa okunamadı (JS, engel, PDF aracı yok...)
  Kanıt yok    maddede otomatik aranabilir dizgi yok → Claude elle bakar
Sayılar sınır duyarlı eşleşir (1.2, 11.20 içinde sayılmaz); eksik kanıt varken "Doğrulandı" verilmez.

Kullanım: dogrula.py NOTLAR_DIZINI [--cikti dogrulama.md] [--en-cok N (0=tümü, varsayılan)] [--temiz-yaz DIZIN] [--is 4] [--onbellek DIZIN] [--dosyalar a.md b.md] [--plan PLAN.json]
Her satıra kaynağın güvenilirlik puanı (guven.py) eklenir; 'Doğrulandı' ama puanı <50 olan kaynaklar ayrıca uyarılır
(alıntı sayfada VAR demektir, sayfanın DOĞRU olduğu demek değildir).
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

sys.dont_write_bytecode = True  # skill dizininde __pycache__/.pyc üretme (taranamayan ikili dosya)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import denetle  # noqa: E402
import guven  # noqa: E402
import oku  # noqa: E402

QUOTE_RE = re.compile(r"[\"“”«]([^\"“”«»]{12,320})[\"“”»]")  # 320 karakter ≈ istemin izin verdiği 25 kelime
CODE_RE = re.compile(r"`([^`\n]{3,80})`")
NUM_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}"                                             # ISO tarih
    r"|v?\d+(?:[.,]\d+)+(?:-[\w.]+)?"                                 # sürüm / ondalık
    r"|\d+(?:[.,]\d+)?\s?[-–]\s?\d+(?:[.,]\d+)?\s?[x×%]?"            # aralık: 8-10x
    r"|%\s?\d+(?:[.,]\d+)?"                                           # %75
    r"|[$€₺]\s?\d[\d.,]*"                                             # $12, ₺500
    r"|\d+(?:[.,]\d+)?\s?(?:x|×|%|ms|saniye|sn|MB|GB|KB|kat|TL|USD|EUR)(?![\w])"   # 500 TL, 20x
    r"|\d{1,3}(?:[.,]\d{3})+(?![\d])|\d{4,}",                         # 1.000 / 21409
    re.I)
GENERIC_NUMS = {"2024", "2025", "2026", "2027"}
RANK = {"Doğrulandı": 4, "Kısmen": 3, "Bulunamadı": 2, "Erişilemedi": 1, "Kanıt yok": 0}


# Çalışanın künyesi kanıt değildir: (2026-08, birincil) · (2024-08-08; birincil) · (2024-09/2026-08, birincil) · (v2; ..., birincil)
META_TAG_RE = re.compile(r"\([^()]*\b(?:birincil|ikincil)\b[^()]*\)", re.I)
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
ASCII_QUOTE_RE = re.compile(r'"([^"]{12,320})"')
# Alıntıdaki EDİTÖR eki: boşluk içeren ([1.86 miles]) ya da saf sözcük ([the], [sic]). `values[0]`, `[a-z]` gibi kod/regex köşeli parantezleri
# ekleme DEĞİL, anlamın parçasıdır: birebir korunur (aksi halde values0 ile values[0] eşitlenirdi).
EDITORIAL_RE = r"\[(?=[^\]]*\s)[^\]]*\]|\[[A-Za-z]{3,}\]"


def norm(text):
    text = MD_LINK_RE.sub(r"\1", text)   # sayfada [10-100x faster](url) than pip → "10-100x faster than pip"
    text = text.lower().replace("̇", "").replace("–", "-").replace("—", "-").replace("×", "x").replace(" ", " ")
    text = re.sub(r"\[(`[^`]*`)\]", r"\1", text)      # çalışan [`kod`] yazar, sayfada bağlantı metne iner; yalnız KOD aralığını saran köşeliler düşer
    text = text.replace("|", " ")   # HTML tablo hücre ayırıcısı: sayfada "Context: | server config" ↔ alıntıda "Context: server config"
    text = re.sub(r"[`*_\"'“”‘’«»]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _pairs(pattern, text):
    """Tırnak çiftlerini UZUNLUKTAN BAĞIMSIZ eşler, sonra uzunlukla süzer: kısa bir "Optional" sonraki çiftlerin eşleşmesini kaydırmasın."""
    return [q.strip() for q in pattern.findall(text) if 12 <= len(q.strip()) <= 320]


def page_text_norm(markdown):
    """Sayfa metninin eşleşmeye hazır hâli. Satır sonunda tireyle bölünmüş sözcükler (PDF sütun sonu: "tar-\nget", "drag-\nand-drop") iki biçimde de
    aranabilsin diye üç varyant tek dizgide birleştirilir: ham · tire silinmiş ("target", "dragand-drop") · tire korunmuş ("tar-get", "drag-and-drop").
    Alıntı bu ayırıcı satırı kesmez, dolayısıyla varyantlar arası sahte eşleşme oluşmaz."""
    base = norm(markdown)
    if not re.search(r"-[ \t]*\r?\n[ \t]*\w", markdown):
        return base
    return "\n".join([base, norm(re.sub(r"-[ \t]*\r?\n[ \t]*", "", markdown)), norm(re.sub(r"-[ \t]*\r?\n[ \t]*", "-", markdown))])


def evidence(finding_text):
    """Maddeden kanıt dizgileri çıkarır. Alıntı/kod ham metinden (içlerindeki bağlantı/URL korunur, sayfa tarafı norm() ile aynı biçime iner);
    sayılar kaynak bağlantıları ve künye etiketi atıldıktan sonra çıkarılır."""
    raw = finding_text.replace('\\"', "'")      # çalışan JSON gibi \" kaçırmış olabilir (künye burada SİLİNMEZ: alıntı içindeki parantez içerik olabilir)
    # Dış tırnak ASCII " ise içteki “ ” tırnaklar alıntıyı bölmesin; ASCII yoksa kıvrık/«» tırnaklara düş.
    quotes = _pairs(re.compile(r'"([^"]*)"'), raw) or _pairs(re.compile(r"[“«]([^“”«»]*)[”»]"), raw)
    codes = [c.strip() for c in CODE_RE.findall(raw)]
    body = re.sub(r"\[[^\]]*\]\((?:[^()]|\([^()]*\))*\)", " ", raw)   # [Kaynak](URL) kaldır
    body = re.sub(r"https?://\S+", " ", body)
    nums = []
    outside = META_TAG_RE.sub(" ", re.sub(r'"[^"]*"|[“«][^”»]*[”»]', " ", CODE_RE.sub(" ", body)))   # künye yalnız tırnak/kod DIŞINDAN atılır
    for m in NUM_RE.finditer(outside):
        token = norm(m.group(0))
        token = token[1:] if re.match(r"v\d", token) else token
        token = token.replace(" ", "")
        if token and token not in GENERIC_NUMS and token not in nums:
            nums.append(token)
    return {"alinti": quotes[:3], "kod": [c for c in codes if c not in quotes and not any(c in q for q in quotes)][:4], "sayi": nums[:5]}


def has_token(page_norm, token, kind):
    """Sayı/kod için sınır duyarlı, ifade (alıntı) için alt dize eşleşmesi."""
    t = norm(token)
    if not t:
        return False
    if kind == "alinti":
        # Alıntıdaki kasıtlı kısaltma (...) ve editör eki [1.86 miles] sınırında parçalara bölünür; her anlamlı parça (>=8 karakter)
        # sayfada aynen geçmeli. Aksi halde "…" içeren DOĞRU alıntılar tümden reddedilir (8 Eki 2026: Epirus, Iron Beam).
        raw = MD_LINK_RE.sub(r"\1", token)
        parts = [norm(x) for x in re.split(r"\.{3,}|…|" + EDITORIAL_RE, raw)]
        parts = [x for x in parts if len(x) >= 8]
        # Tire-duyarsız ikinci şans: `pdftotext` satır sonu tirelemesini kendisi birleştirir ("drag-\nand-drop" → "dragand-drop") ve sözcük içi
        # tireyi yutabilir; HTML'de de "co-operate"/"cooperate" gibi yazım farkları olur. Yalnız ALINTI için (sayı/kodda tire anlamlıdır: "1-2").
        flat = None
        def present(x):
            nonlocal flat
            if x in page_norm:
                return True
            if "-" not in x and "-" not in page_norm:
                return False
            flat = page_norm.replace("-", "") if flat is None else flat
            return x.replace("-", "") in flat
        if not parts:
            return present(t)
        return all(present(x) for x in parts)
    if kind == "kod":
        return re.search(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", page_norm) is not None
    # sayı: sayfada "8-10x" ya da "8-10 x" yazılabilir; önü/arkası rakam-harf-nokta-virgülle bitişik olmasın
    # 8 Eki 2026: Türkçe not ("%26,2", "1,37", "100.000") ile İngilizce kaynak ("26.2%", "1.37 billion", "100,000") yazım farkı yüzünden
    # doğru rakamlar "bulunamadı" sayılıyordu → ondalık/binlik ayırıcı ve yüzde yazımı varyantları denenir.
    for variant in number_variants(t):
        lead = r"v?" if re.match(r"\d+\.\d", variant) else ""   # sürüm: iddia "1.2.3", sayfa "v1.2.3" yazabilir
        pattern = r"(?<![\w.,-])" + lead + r"\s?".join(re.escape(ch) for ch in variant) + r"(?!\w)(?![.,]\d)"
        if re.search(pattern, page_norm):
            return True
    return False


def number_variants(t):
    """'%26,2' → ['%26,2', '26.2%', '26.2 %', '26.2 percent', '26,2', ...]; '100.000' → ['100.000', '100,000', '100000']."""
    out = [t]
    core, pct = (t[1:], True) if t.startswith("%") else (t, False)
    cores = [core]
    if re.fullmatch(r"\d+,\d{1,2}", core):                      # Türkçe ondalık: 26,2 → 26.2
        cores.append(core.replace(",", "."))
    elif re.fullmatch(r"\d+\.\d{1,2}", core):                    # İngilizce ondalık: 26.2 → 26,2
        cores.append(core.replace(".", ","))
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", core):             # binlik: 100.000 ↔ 100,000 ↔ 100000
        digits = re.sub(r"[.,]", "", core)
        cores += [digits, "{:,}".format(int(digits)), "{:,}".format(int(digits)).replace(",", ".")]
    for c in cores:
        out.append(c)
        if pct:
            out += [c + "%", c + " %", c + " percent", c + " per cent"]
    seen, res = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            res.append(v)
    return res


def judge(ev, page_norm):
    """(karar, bulunan, toplam, eksikler). Eksik kanıt varken 'Doğrulandı' verilmez."""
    items = [("alinti", q) for q in ev["alinti"]] + [("kod", c) for c in ev["kod"]] + [("sayi", n) for n in ev["sayi"]]
    if not items:
        return "Kanıt yok", 0, 0, []
    found, missing = 0, []
    for kind, text in items:
        if has_token(page_norm, text, kind):
            found += 1
        else:
            missing.append(text)
    total = len(items)
    # Koruma: doğrudan alıntıların HİÇBİRİ sayfada yoksa rakamlar maddeyi kurtarmaz (rakam başka bağlamda tesadüfen geçebilir;
    # eskiden oran >=0.5 olunca "Kısmen" çıkardı). Kasıtlı kısaltmalı alıntılar has_token'da parçalanarak ayrıca ele alınır.
    if ev["alinti"] and not any(has_token(page_norm, q, "alinti") for q in ev["alinti"]):
        return "Bulunamadı", found, total, missing
    if found == total:
        verdict = "Doğrulandı" if (ev["alinti"] or total >= 2) else "Kısmen"  # tek rakam/kod tek başına zayıf kanıt
    elif found / total >= 0.5 or ev["alinti"]:
        # Alıntı (en az biri) sayfada VAR: eksik kalanlar çoğunlukla çalışanın özet cümlesindeki yeniden yazılmış sayılardır
        # ("1.000 istek / 12 USD" ↔ sayfada "1k requests / $12"). Bu maddeyi "Bulunamadı" diye atmak yanlış-negatiftir → en az "Kısmen".
        verdict = "Kısmen"
    else:
        verdict = "Bulunamadı"
    return verdict, found, total, missing


def collect(notes_dir, files=None):
    paths = sorted(p for p in Path(notes_dir).glob("*.md") if p.is_file() and (not files or p.name in set(files)))
    return [denetle.analyze(p) for p in paths]


def run(notes_dir, limit=0, jobs=4, cache_dir=None, files=None, hints=None):
    results = collect(notes_dir, files)
    candidates = []
    for r in results:
        for f in r["findings"]:
            if not f["urls"]:
                continue
            ev = evidence(f["metin"])
            strength = len(ev["alinti"]) * 3 + len(ev["kod"]) + len(ev["sayi"])
            candidates.append((strength, r["dosya"], f, ev))
    total_findings = sum(r["bulgu"] for r in results)
    with_url = len(candidates)
    candidates.sort(key=lambda c: -c[0])
    no_evidence = [c for c in candidates if c[0] == 0]
    testable = [c for c in candidates if c[0] > 0]
    chosen, skipped = (testable, []) if not limit else (testable[:limit], testable[limit:])   # limit 0/None = TÜMÜ (0 jeton; 20 sınırı 150 bulguyu denetimsiz bıraktı)
    urls = sorted({u for c in chosen for u in c[2]["urls"][:2]})
    pages = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for url, page in zip(urls, pool.map(lambda u: oku.load(u, cache_dir=cache_dir), urls)):
            pages[url] = page
    rows = []
    for strength, name, f, ev in chosen:
        best = None
        for url in f["urls"][:2]:  # alıntıyı yazan URL ilk olmayabilir: çok kaynaklı maddede hepsine bak
            page = pages[url]
            if not page["ok"]:
                row = {"karar": "Erişilemedi", "bulunan": 0, "toplam": 0, "eksik": [], "neden": page["hata"], "url": url}
            else:
                verdict, found, total, missing = judge(ev, page_text_norm(page["markdown"]))
                row = {"karar": verdict, "bulunan": found, "toplam": total, "eksik": missing, "neden": "", "url": url,
                       "enjeksiyon_izi": bool(oku.INJECTION.search(page["markdown"]))}
            if best is None or (RANK[row["karar"]], row["bulunan"]) > (RANK[best["karar"]], best["bulunan"]):
                best = row
        trust = guven.score(best["url"], guven.hints_for(hints, Path(name).stem))
        rows.append({"not": name, "iddia": f["metin"], **best, "guven": trust["puan"], "guven_sinif": trust["sinif"]})
    for strength, name, f, ev in no_evidence:
        trust = guven.score(f["urls"][0], guven.hints_for(hints, Path(name).stem))
        rows.append({"not": name, "iddia": f["metin"], "url": f["urls"][0], "karar": "Kanıt yok", "bulunan": 0, "toplam": 0, "eksik": [],
                     "neden": "otomatik aranabilir alıntı/rakam yok", "guven": trust["puan"], "guven_sinif": trust["sinif"]})
    coverage = {"toplam_bulgu": total_findings, "url_li": with_url, "denenen": len(chosen), "kanitsiz": len(no_evidence),
                "limit_disi": len(skipped), "urlsiz": total_findings - with_url}
    return rows, coverage


def render(rows, coverage):
    counts = {}
    for r in rows:
        counts[r["karar"]] = counts.get(r["karar"], 0) + 1
    L = ["# Otomatik iddia–kaynak doğrulaması", "",
         "Özet: " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -RANK[kv[0]])) + f" (toplam {len(rows)})",
         f"Kapsam: {coverage['toplam_bulgu']} bulgudan {coverage['denenen']} tanesi kaynakta arandı; "
         f"{coverage['kanitsiz']} kanıtsız (alıntı/rakam yok), {coverage['limit_disi']} `--en-cok` sınırı dışında, {coverage['urlsiz']} URL'siz.", "",
         "| Karar | Kanıt | Not | İddia | Kaynak | Güven |", "|---|---:|---|---|---|---:|"]
    for r in rows:
        claim = re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]\([^)]*\)", "", r["iddia"]))[:90]
        L.append(f"| {r['karar']} | {r['bulunan']}/{r['toplam']} | {r['not']} | {claim} | {urlparse(r['url']).netloc} | {r.get('guven', '—')} |")
    if coverage["limit_disi"]:
        L += ["", f"⚠ {coverage['limit_disi']} madde sınır nedeniyle denenmedi; tümü için `--en-cok {coverage['denenen'] + coverage['limit_disi']}` ver."]
    todo = [r for r in rows if r["karar"] in ("Kısmen", "Bulunamadı", "Erişilemedi", "Kanıt yok")]
    if todo:
        L += ["", "## Claude'un elle bakacakları", ""]
        for r in todo:
            L.append(f"- **{r['karar']}** `{r['not']}` — {r['iddia'][:140]}\n  kaynak: {r['url']}" +
                     (f"\n  sayfada bulunamayan: {', '.join(map(str, r['eksik'][:4]))}" if r["eksik"] else "") +
                     (f"\n  neden: {r['neden']}" if r.get("neden") else ""))
    notfound = [r for r in rows if r["karar"] == "Bulunamadı"]
    if notfound:
        L += ["", f"## RAPORA GİRMEZ: {len(notfound)} bulgunun alıntısı kaynak sayfada YOK (uydurma/çeviri/kaynak karışması şüphesi)", "",
              "Bunları sentez girdisinden çıkar (`--temiz-yaz` bunu yapar) ya da kaynağı elle açıp düzelt; düzeltmeden rapora alma.", ""]
        L += [f"- `{r['not']}` — {re.sub(chr(10), ' ', r['iddia'])[:130]}\n  kaynak: {r['url']}" for r in notfound]
    weak = [r for r in rows if r["karar"] == "Doğrulandı" and r.get("guven", 100) < 50]
    if weak:
        L += ["", "## Alıntı sayfada var ama kaynak zayıf (güven <50): sayfanın doğruluğunu ikinci kaynakla teyit et", ""]
        L += [f"- `{r['not']}` — {r['iddia'][:110]}\n  kaynak: {r['url']} ({r.get('guven_sinif')}, {r['guven']})" for r in weak]
    inj = [r for r in rows if r.get("enjeksiyon_izi")]
    if inj:
        L += ["", "⚠ Prompt-injection izi olan kaynaklar (içerik talimat sayılmaz): " + ", ".join(sorted({urlparse(r['url']).netloc for r in inj}))]
    return "\n".join(L) + "\n"


def clean_copies(notes_dir, rows, out_dir, files=None):
    """'Bulunamadı' bulguların maddelerini çıkarıp temiz not kopyaları yazar (sentez girdisi). Orijinal notlara dokunmaz.
    Döner: {dosya: çıkarılan madde sayısı}. Çıkarılanlar out_dir/DISLANAN.md'ye yazılır."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    drop = {}
    for r in rows:
        if r["karar"] == "Bulunamadı":
            drop.setdefault(r["not"], set()).add(re.sub(r"\s+", " ", r["iddia"]).strip())
    dropped, report = {}, ["# Sentezden çıkarılan bulgular (alıntı kaynakta bulunamadı)", ""]
    for p in sorted(Path(notes_dir).glob("*.md")):
        if files and p.name not in set(files):
            continue
        kept, n = [], 0
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = denetle.BULLET_RE.match(line.strip())
            body = re.sub(r"\s+", " ", line.strip()[m.end():]).strip() if m else None
            if body and body in drop.get(p.name, ()):
                n += 1
                report.append(f"- `{p.name}` — {body[:160]}")
                continue
            kept.append(line)
        (out / p.name).write_text("\n".join(kept) + "\n", encoding="utf-8")
        dropped[p.name] = n
    (out / "DISLANAN.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return dropped


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("notlar")
    ap.add_argument("--cikti")
    ap.add_argument("--en-cok", type=int, default=0, help="en çok kaç madde (0 = tümü; varsayılan)")
    ap.add_argument("--is", dest="jobs", type=int, default=4)
    ap.add_argument("--onbellek", help="sayfa deposu dizini (varsayılan: notlar/../kaynaklar)")
    ap.add_argument("--dosyalar", nargs="+", help="yalnız bu not dosyaları")
    ap.add_argument("--plan", help="PLAN.json: `kaynaklar` ipuçları güvenilirlik puanına +10 verir")
    ap.add_argument("--temiz-yaz", dest="temiz", help="'Bulunamadı' maddeleri çıkarılmış not kopyalarını bu dizine yaz (sentez girdisi)")
    a = ap.parse_args()
    if not [p for p in Path(a.notlar).glob("*.md") if not a.dosyalar or p.name in set(a.dosyalar)]:
        print(f"dogrula: {a.notlar} içinde (seçilen) .md yok", file=sys.stderr)
        return 2
    hints = guven.hints_by_slug(a.plan) if a.plan else {}
    rows, coverage = run(a.notlar, a.en_cok, a.jobs, a.onbellek or str(Path(a.notlar).parent / "kaynaklar"), a.dosyalar, hints)
    report = render(rows, coverage)
    out = Path(a.cikti) if a.cikti else Path(a.notlar).parent / "dogrulama.md"
    out.write_text(report, encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps({"kapsam": coverage, "satirlar": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report)
    print(f"(doğrulama yazıldı: {out})")
    if a.temiz:
        dropped = clean_copies(a.notlar, rows, a.temiz, a.dosyalar)
        print(f"(temiz kopyalar: {a.temiz} — çıkarılan madde: {sum(dropped.values())}; sentezi bu dizinden yap)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
