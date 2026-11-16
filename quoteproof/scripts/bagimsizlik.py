#!/usr/bin/env python3
"""Kaynak bağımsızlığı raporu: notların atıf yaptığı sayfaları içerik benzerliğine göre kümeler ve her kümeyi TEK kaynak sayar (0 LLM jetonu, yalnız standart kütüphane).

Neden: `denetle.py`'nin "Farklı alan adı" sütunu HAM alan adı sayısıdır. Aynı yazı (syndication) üç ayrı alan adında
yayımlandığında üç bağımsız kaynak gibi görünür — oysa "yayın kopyası uzlaşı sayılmaz". Bu araç alan adı sayısını bağımsız
kaynak sayısından AYIRIR: içerikçe aynı olan sayfalar tek küme, her küme tek oy.

Yöntem: her notun URL'leri `denetle.bullet_urls` ile toplanır (dogrula.py'nin kullandığı ayrıştırıcı; kopyalanmaz); okuma
önbelleğindeki (`cache_dir`) sayfa metinlerinden GEÇİCİ bir kasa kurulur (`:memory:` yerine geçici dosya — kalıcı kasa
kirlenmez) ve kasa.py'nin shingle(8)+Jaccard≥0.85 kuralıyla kopya grupları bulunur. Bağımsız kaynak = kopya grubundaki tüm
alan adları TEK, ya da grupsuz tek sayfa → kendi alan adı.

SINIRLAMA (kanıt değil, öncelik sinyali): yalnız sayfa METNİ benzerliğine bakar; ortak sahiplik, aynı ajans zinciri, aynı
muhabir ya da dairesel atıf TESPİT EDİLMEZ. Farklı metinle yayımlanan kopyalar ve ortak kaynaktan beslenen özgün görünümlü
yazılar yakalanmaz. Okunamayan (önbellekte olmayan) sayfalar bağımsız kaynak sayımına girmez.

Kullanım: bagimsizlik.py NOT_DIZINI [--onbellek DIR] [--cikti bagimsizlik.md] [--json]
Çıkış: 0 tamam · 2 kullanım hatası
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import denetle  # noqa: E402
import kasa  # noqa: E402

VARSAYILAN_ONBELLEK = "kaynaklar"
VARSAYILAN_CIKTI = "bagimsizlik.md"


def _not_dosyalari(notes_dir, files=None):
    secili = set(files) if files is not None else None
    return sorted(p for p in Path(notes_dir).glob("*.md")
                  if p.is_file() and p.name != "DISLANAN.md" and (secili is None or p.name in secili))


def _not_urlleri(path):
    """Notun tüm bölümlerindeki URL'ler → sıralı, kanonik, benzersiz liste (denetle.bullet_urls yeniden kullanılır)."""
    _, questions = denetle.parse_note(path)
    out = []
    for q in questions:
        for lines in q["bolumler"].values():
            for satir in lines:
                for u in denetle.bullet_urls(satir):
                    c = kasa.url_kanonik(u.rstrip(".,;)"))
                    if c and c not in out:
                        out.append(c)
    return out


def _onbellek_sayfalari(cache_dir):
    """{kanonik url: sayfa sözlüğü} — aynı kanonik URL birden çoksa en yeni fetched_at kazanır. Yalnız ok=true ve dolu markdown."""
    sayfalar = {}
    if not cache_dir:
        return sayfalar
    for s in kasa.sayfalari_yukle(cache_dir):
        c = kasa.url_kanonik(s["url"])
        if not c:
            continue
        eski = sayfalar.get(c)
        if eski is None or s["alindi"] > eski["alindi"]:
            sayfalar[c] = s
    return sayfalar


def _gecici_kasa(sayfalar):
    """Geçici dizine oku.py önbellek biçiminde JSON yazıp geçici bir kasa kurar. (db_yolu, dizin) döner; çağıran siler."""
    dizin = tempfile.mkdtemp(prefix="bagimsizlik-")
    db = os.path.join(dizin, "kasa.db")
    for i, (u, s) in enumerate(sorted(sayfalar.items())):
        Path(dizin, f"{i:06d}.json").write_text(json.dumps(
            {"istenen_url": u, "ok": True, "markdown": s["metin"], "fetched_at": s["alindi"] or 1.0,
             "baslik": s.get("baslik", "")}, ensure_ascii=False), encoding="utf-8")
    kasa.ekle(db, [dizin])
    return db, dizin


def run(notes_dir, cache_dir, files=None):
    """Not başına bağımsızlık özeti. Döner: {slug: {dosya, url_sayisi, okunabilir_sayisi, alan_adi_sayisi,
    bagimsiz_kaynak_sayisi, kopya_gruplari:[{"urller":[...], "alan_adlari":[...]}]}}."""
    onbellek = _onbellek_sayfalari(cache_dir)
    notlar = _not_dosyalari(notes_dir, files)
    urller_per_not = {p.stem: _not_urlleri(p) for p in notlar}
    ilgili = sorted({u for urller in urller_per_not.values() for u in urller if u in onbellek})
    db = dizin = None
    try:
        db, dizin = _gecici_kasa({u: onbellek[u] for u in ilgili})
        gruplar = sorted((sorted(u) for u in kasa.kopya_gruplari(db).values() if len(u) > 1))
        res = {}
        for p in notlar:
            urller = urller_per_not[p.stem]
            okunabilir = [u for u in urller if u in onbellek]
            kopyalar = [{"urller": uyeler, "alan_adlari": sorted({kasa._host(u) for u in uyeler})}
                        for uyeler in gruplar if any(u in okunabilir for u in uyeler)]
            res[p.stem] = {
                "dosya": p.name,
                "url_sayisi": len(urller),
                "okunabilir_sayisi": len(okunabilir),
                "alan_adi_sayisi": len({kasa._host(u) for u in urller}),
                "okunabilir_alan_adi_sayisi": len({kasa._host(u) for u in okunabilir}),   # bağımsız kaynakla AYNI taban: fark yalnız kopyalardan gelir
                "bagimsiz_kaynak_sayisi": kasa.bagimsiz_alan_adi_sayisi(okunabilir, db) if okunabilir else 0,
                "kopya_gruplari": kopyalar,
            }
        return res
    finally:
        if dizin:
            shutil.rmtree(dizin, ignore_errors=True)


def summarize(res):
    """Rapor başlığı için toplamlar. Kopya grubu notlar arasında TEK sayılır (aynı üye kümesi bir kez)."""
    gruplar = {tuple(g["urller"]) for r in res.values() for g in r["kopya_gruplari"]}
    return {"not": len(res),
            "alan_adi": sum(r["alan_adi_sayisi"] for r in res.values()),
            "okunabilir_alan_adi": sum(r["okunabilir_alan_adi_sayisi"] for r in res.values()),
            "okunamayan": sum(r["url_sayisi"] - r["okunabilir_sayisi"] for r in res.values()),
            "bagimsiz": sum(r["bagimsiz_kaynak_sayisi"] for r in res.values()),
            "kopya_grubu": len(gruplar)}


def render(res):
    s = summarize(res)
    L = [denetle.VERI_UYARISI, "", "# Kaynak bağımsızlığı", "",
         f"Özet: {s['not']} not; **{s['okunabilir_alan_adi']} okunabilir alan adı → {s['bagimsiz']} bağımsız kaynak** "
         f"({s['kopya_grubu']} kopya grubu; {s['okunamayan']} sayfa okunamadığı için karşılaştırılamadı). Aynı yazının farklı alan adlarındaki kopyaları TEK kaynak sayılır; "
         "`alan adı` sütunu ham sayıdır (denetle.py'nin \"Farklı alan adı\" sütunuyla aynı), `okunabilir alan adı` ve `bağımsız kaynak` AYNI tabandadır (önbellekte okunan sayfalar): aralarındaki fark yalnız yayın kopyalarından gelir.", "",
         "| Not | URL | Okunabilir | Alan adı | Okunabilir alan adı | Bağımsız kaynak | Kopya grubu |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    for slug in sorted(res):
        r = res[slug]
        L.append(f"| {r['dosya']} | {r['url_sayisi']} | {r['okunabilir_sayisi']} | {r['alan_adi_sayisi']} | "
                 f"{r['okunabilir_alan_adi_sayisi']} | {r['bagimsiz_kaynak_sayisi']} | {len(r['kopya_gruplari'])} |")
    L.append("")
    for slug in sorted(res):
        r = res[slug]
        if not r["kopya_gruplari"]:
            continue
        L += [f"## {r['dosya']} — kopya grupları", ""]
        for i, g in enumerate(r["kopya_gruplari"], 1):
            L.append(f"{i}. alan adları: {', '.join(g['alan_adlari'])}")
            L += [f"   - {u}" for u in g["urller"]]
        L.append("")
    L += ["## Sınırlama", "",
          "Bu rapor yalnız sayfa METNİ benzerliğine bakar (kasa.py: shingle 8 sözcük + Jaccard ≥ 0.85). Ortak sahiplik, "
          "aynı ajans zinciri, aynı muhabir ya da dairesel atıf TESPİT EDİLMEZ; farklı metinle yayımlanan kopyalar ve "
          "ortak kaynaktan beslenen özgün görünümlü yazılar yakalanmaz. Okunamayan (önbellekte olmayan) sayfalar bağımsız "
          "kaynak sayımına girmez; `Okunabilir` sütunu kaç sayfanın gerçekten karşılaştırıldığını gösterir.", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("notlar", help="notların bulunduğu dizin (*.md)")
    ap.add_argument("--onbellek", default=None, help=f"okuma önbelleği (varsayılan: NOT_DIZINI/../{VARSAYILAN_ONBELLEK})")
    ap.add_argument("--cikti", default=None, help=f"çıktı dosyası (varsayılan: NOT_DIZINI/../{VARSAYILAN_CIKTI})")
    ap.add_argument("--json", action="store_true", help="Markdown yerine JSON yazdır")
    a = ap.parse_args(argv)

    d = Path(a.notlar)
    if not d.is_dir():
        print(f"bagimsizlik: not dizini yok: {d}", file=sys.stderr)
        return 2
    onbellek = a.onbellek or str(d.parent / VARSAYILAN_ONBELLEK)
    res = run(d, onbellek)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    md = render(res)
    out = Path(a.cikti) if a.cikti else d.parent / VARSAYILAN_CIKTI
    out.write_text(md + "\n", encoding="utf-8")
    s = summarize(res)
    print(f"bagimsizlik: {s['okunabilir_alan_adi']} okunabilir alan adı → {s['bagimsiz']} bağımsız kaynak ({s['kopya_grubu']} kopya grubu; {s['okunamayan']} sayfa okunamadı)")
    print(f"bagimsizlik: rapor → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())