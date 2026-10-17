#!/usr/bin/env python3
"""Araştırma raporu ölçer (0 LLM jetonu, yalnız standart kütüphane + guven.py).

Bir ya da birkaç raporu AYNI ölçütlerle sayar, yan yana tablo basar. Amaç: iki ajanın (ör. iki farklı model) raporlarını
izlenimle değil sayıyla karşılaştırmak. Sayılar kaliteyi KANITLAMAZ; "nereye bakmalı" sinyalidir (kritik iddiayı yine kaynağında aç).

Kullanım: rapor_olc.py RAPOR.md [RAPOR2.md ...] [--basliklar "Yönetici özeti|Kaynakça"] [--ulkeler "ABD,Çin,Türkiye"]
Ölçülenler: sözcük · istenen başlıkların bulunma oranı · tablo satırı · benzersiz URL ve kaynak sınıfı dağılımı (guven.py) ·
"boşluk/veri yok" ifadesi (dürüstlük sinyali) · KESİK çıktı işareti · her ülke için geçen satır sayısı.
"""
import argparse
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import guven  # noqa: E402

URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
GAP_RE = re.compile(r"bulunamadı|bulamadım|veri sınırlı|doğrulanamadı|teyit edilemedi|notlarda yok|bulgu yok", re.I)
TRUNC_RE = re.compile(r"Reply truncated at the model|output token limit|ÇIKTI MODEL ÇIKTI-TOKEN SINIRINDA KESİLDİ")
TABLE_SEP = re.compile(r"^\|[\s:|-]+\|?\s*$")


def measure(path, headings, countries):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    found = [h for h in headings if re.search(r"(?m)^#{1,4}\s*(?:\d+\.\s*)?" + re.escape(h), text, re.I)]
    urls = sorted({u.rstrip(".,;") for u in URL_RE.findall(text)})
    classes = {}
    for u in urls:
        c = guven.score(u, None)["sinif"]
        classes[c] = classes.get(c, 0) + 1
    rows = [l for l in lines if l.startswith("|") and not TABLE_SEP.match(l)]
    gaps = len(GAP_RE.findall(text))
    cover = {}
    for c in countries:
        hit = [l for l in lines if c in l]
        cover[c] = (len(hit), sum(1 for l in hit if GAP_RE.search(l)))
    return {"ad": Path(path).name, "sozcuk": len(text.split()), "basliklar": (len(found), len(headings)),
            "tablo_satiri": len(rows), "url": len(urls), "siniflar": classes, "bosluk": gaps,
            "kesik": bool(TRUNC_RE.search(text)), "ulke": cover}


def render(results, countries):
    names = [r["ad"] for r in results]
    L = ["| Ölçüt | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
    def row(label, fn):
        L.append(f"| {label} | " + " | ".join(str(fn(r)) for r in results) + " |")
    row("Sözcük", lambda r: r["sozcuk"])
    row("İstenen başlık bulundu", lambda r: f"{r['basliklar'][0]}/{r['basliklar'][1]}")
    row("Tablo satırı", lambda r: r["tablo_satiri"])
    row("Benzersiz URL", lambda r: r["url"])
    row("Kaynak sınıfları", lambda r: ", ".join(f"{k} {v}" for k, v in sorted(r["siniflar"].items(), key=lambda kv: -kv[1])) or "—")
    row("'Bulunamadı/veri sınırlı' ifadesi", lambda r: r["bosluk"])
    row("⚠ KESİK çıktı", lambda r: "EVET" if r["kesik"] else "hayır")
    for c in countries:
        row(f"{c} (satır / boşluklu)", lambda r, c=c: f"{r['ulke'][c][0]} / {r['ulke'][c][1]}")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raporlar", nargs="+")
    ap.add_argument("--basliklar", default="Yönetici özeti|Son 12 ay|Teknoloji eksenleri|Ülke vizyon|Karşılaştırma matrisi|Belirsizlik|Sonuç|Kaynakça",
                    help="'|' ile ayrılmış beklenen başlık parçaları")
    ap.add_argument("--ulkeler", default="", help="virgülle ayrılmış ülke/konu adları")
    a = ap.parse_args(argv)
    headings = [h for h in a.basliklar.split("|") if h]
    countries = [c.strip() for c in a.ulkeler.split(",") if c.strip()]
    missing = [p for p in a.raporlar if not Path(p).is_file()]
    if missing:
        print("rapor_olc: dosya yok: " + ", ".join(missing), file=sys.stderr)
        return 2
    print(render([measure(p, headings, countries) for p in a.raporlar], countries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
