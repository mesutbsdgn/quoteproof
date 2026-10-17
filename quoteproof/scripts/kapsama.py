#!/usr/bin/env python3
"""Anahtar olgu kapsaması: planda beklenen olgular, doğrulanmış bulgularda var mı? (0 LLM jetonu, yalnız standart kütüphane)

Neden: kapsama yalnızca BEKLENEN olgulara karşı ölçülebilir. Ölçüm (9 Ekim 2026, iki konu): tek çalıştırma anahtar olguların ≈ %62–85'ini buluyor ve
tekrarlar farklı olguları kaçırıyor; bir olgu listesi olmadan "tamam mı?" sorusunun cevabı yok. Bu araç, koordinatörün plana yazdığı olgu listesine göre
"kapsama 9/12, eksik: …" der ve eksikler için yalnız o olguları arayan bir ek plan (hedefli ek çalıştırma) üretir.

Plan alanı `olgular` (çalışana VERİLMEZ; yalnız ölçüm içindir): liste; her öğe
  {"ad": "İnsan okur açıklama", "ara": "regex"}            ara: büyük/küçük harf duyarsız; liste de olabilir (herhangi biri yeter)
  ya da "açıklama :: regex"
Bir olgu, `dogrulama.json` içinde aynı dosya ve bulgu için karar "Doğrulandı" ise ve o bulgu
"Alıntılı bulgular" maddelerinde eşleşirse kapsanmıştır. Kısmen/Erişilemedi/Kanıt yok/Bulunamadı
ve doğrulama kaydı olmayan maddeler sayılmaz. Özet/Boşluklar hiçbir zaman eşleşmez.
Olgu listesini kaynağı görmeden yazdıysan yanlış olabilir: hiçbir koşunun bulmadığı olgu "bulunamadı" ya da "beklenti yanlış" olabilir; elle bak.

Kullanım:
  python3 kapsama.py PLAN.json NOT_DIZINI [NOT_DIZINI ...] [--etiket a,b] [--cikti kapsama.md] [--eksik-plan EK_PLAN.json] [--esik 0.6]
  Birden çok dizin = birden çok bağımsız çalıştırma: olgu başına "kaç çalıştırmada bulundu" ve birleşim kapsaması gösterilir.
  --eksik-plan: kapsanmayan olgular için aynı slug'lı ek plan (arastir.py -d BASKA_DIZIN ile çalıştırıp uzlas.py ile birleştir).
Çıkış: 0 tamam · 1 kapsama --esik altında · 2 kullanım hatası
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import denetle  # noqa: E402
import dogrula  # noqa: E402

MAX_OLGU = 40
VARSAYILAN_ESIK = 0.6
EK_SORU_SINIRI = 3      # ek planda en çok bu kadar soru (fazlası son soruda birleşir): soru sayısı arama bütçesini belirler, maliyet buradan gelir


class OlguHatasi(ValueError):
    pass


def olgulari_oku(item):
    """item["olgular"] → [{"ad", "ara", "rx"}]. Biçim ya da regex hatasında OlguHatasi."""
    ham = item.get("olgular")
    if ham is None:
        return []
    if not isinstance(ham, list):
        raise OlguHatasi("'olgular' bir liste olmalı")
    if len(ham) > MAX_OLGU:
        raise OlguHatasi(f"'olgular' en çok {MAX_OLGU} öğe olabilir ({len(ham)} verildi)")
    out = []
    for i, o in enumerate(ham, 1):
        if isinstance(o, str):
            if "::" not in o:
                raise OlguHatasi(f"olgular[{i}]: \"ad :: regex\" biçiminde olmalı")
            ad, ara = (x.strip() for x in o.split("::", 1))
        elif isinstance(o, dict):
            ad, ara = o.get("ad"), o.get("ara")
        else:
            raise OlguHatasi(f"olgular[{i}]: metin ya da {{\"ad\", \"ara\"}} nesnesi olmalı")
        if isinstance(ara, list):
            if not ara or not all(isinstance(a, str) and a.strip() for a in ara):
                raise OlguHatasi(f"olgular[{i}]: 'ara' listesi boş olmayan metinlerden oluşmalı")
            ara = "|".join(f"(?:{a})" for a in ara)
        if not isinstance(ad, str) or not ad.strip() or not isinstance(ara, str) or not ara.strip():
            raise OlguHatasi(f"olgular[{i}]: 'ad' ve 'ara' boş olmayan metin olmalı")
        try:
            rx = re.compile(ara, re.IGNORECASE)
        except re.error as e:
            raise OlguHatasi(f"olgular[{i}] ({ad[:30]}): regex geçersiz ({e})")
        out.append({"ad": ad.strip(), "ara": ara.strip(), "rx": rx})
    return out


def bulgu_satirlari(path):
    """Notun denetle.py ile aynı ayrıştırılmış "Alıntılı bulgular" maddeleri."""
    return denetle.analyze(Path(path))["findings"]


def _claim_key(text):
    return re.sub(r"\s+", " ", text or "").strip()


def dogrulama_kararlari(path):
    """dogrulama.json satırlarını (dosya, iddia) anahtarıyla sırayı koruyarak grupla.

    Aynı metinli yinelenmiş maddeler için sıralı liste tutulur; dogrula.py aynı güçteki
    eşit iddiaları kaynak sırasıyla işler.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("satirlar"), list):
        return {}
    out = {}
    for row in data["satirlar"]:
        if not isinstance(row, dict):
            continue
        name, claim, verdict = row.get("not"), row.get("iddia"), row.get("karar")
        if isinstance(name, str) and isinstance(claim, str) and isinstance(verdict, str):
            out.setdefault((name, _claim_key(claim)), []).append(verdict)
    return out


def verified_bulgu_satirlari(path, decisions):
    """Yalnız dogrulama.json'da aynı not maddesi için Doğrulandı olan bulgular."""
    pending = {key: list(values) for key, values in decisions.items()}
    out = []
    for finding in bulgu_satirlari(path):
        key = (Path(path).name, _claim_key(finding["metin"]))
        verdicts = pending.get(key, [])
        verdict = verdicts.pop(0) if verdicts else None
        if verdict == "Doğrulandı":
            out.append(finding["metin"])
    return out


def _eslesir(rx, satirlar):
    return any(rx.search(s) or rx.search(dogrula.norm(s)) for s in satirlar)


def run(plan, dirs, labels=None, files=None):
    """plan: öğe listesi; dirs: not dizinleri (çalıştırma başına bir). Döner: {slug: sonuç} (yalnız `olgular`ı olan ve notu bulunan konular)."""
    labels = labels or [Path(d).resolve().parent.name if Path(d).name.startswith("notlar") else Path(d).name for d in dirs]
    if len(set(labels)) != len(labels):
        labels = [f"{l}#{i + 1}" for i, l in enumerate(labels)]
    decisions_by_label = {lab: dogrulama_kararlari(Path(d).resolve().parent / "dogrulama.json")
                          for lab, d in zip(labels, dirs)}
    out = {}
    for item in plan if isinstance(plan, list) else []:
        facts = olgulari_oku(item)
        slug = item.get("slug")
        if not facts or not slug or (files is not None and f"{slug}.md" not in set(files)):
            continue
        lines = {}
        for lab, d in zip(labels, dirs):
            note = Path(d) / f"{slug}.md"
            if note.is_file():
                lines[lab] = verified_bulgu_satirlari(note, decisions_by_label[lab])
        if not lines:
            continue
        rows = [{"ad": f["ad"], "ara": f["ara"], "kapsayan": [lab for lab, sat in lines.items() if _eslesir(f["rx"], sat)]} for f in facts]
        covered = sum(1 for r in rows if r["kapsayan"])
        out[slug] = {"item": item, "etiketler": list(lines), "olgular": rows, "kapsanan": covered, "toplam": len(rows),
                     "eksik": [r for r in rows if not r["kapsayan"]],
                     "etiket_kapsama": {lab: sum(1 for r in rows if lab in r["kapsayan"]) for lab in lines}}
    return out


def render(res):
    L = ["# Anahtar olgu kapsaması", ""]
    if not res:
        return "\n".join(L + ["Planda `olgular` olan ve notu bulunan konu yok.", ""])
    for slug, r in res.items():
        n = len(r["etiketler"])
        pct = 100 * r["kapsanan"] // max(1, r["toplam"])
        L += [f"## {slug}: {r['kapsanan']}/{r['toplam']} olgu kapsandı (%{pct})", ""]
        if n > 1:
            L.append(f"{n} çalıştırma; birleşim kapsaması yukarıdaki sayıdır. Çalıştırma başına: " + " · ".join(f"{k} {v}" for k, v in r["etiket_kapsama"].items()) + "\n")
        L += ["| | Olgu |" + (" Bulunduğu çalıştırmalar |" if n > 1 else ""), "|---|---|" + ("---|" if n > 1 else "")]
        for row in r["olgular"]:
            mark = "✓" if row["kapsayan"] else "✗"
            cell = (f" {len(row['kapsayan'])}/{n} ({', '.join(row['kapsayan'])}) |" if row["kapsayan"] else " — |") if n > 1 else ""
            L.append(f"| {mark} | {row['ad']} |{cell}")
        if r["eksik"]:
            L += ["", "Eksik olgular (ya bulunamadı ya da beklenti/regex yanlış; elle bak): " + "; ".join(e["ad"] for e in r["eksik"]),
                  "Hedefli ek çalıştırma için: `--eksik-plan` ile ek plan üret."]
        L.append("")
    L.append("Not: yalnız dogrulama.json içinde aynı dosya ve bulgu için \"Doğrulandı\" kararı olan \"Alıntılı bulgular\" sayılır. Kısmen, Erişilemedi, Kanıt yok, Bulunamadı ve doğrulama kaydı olmayan maddeler dışarıda kalır. Kapsama yine regex eşleşmesidir; olgunun doğru anlaşıldığını kanıtlamaz.")
    return "\n".join(L) + "\n"


def eksik_plan(res):
    """Kapsanmayan olgular için aynı slug'lı ek plan: yalnız eksikleri arayan sorular. Ayrı bir -d dizinine koşturulup uzlas.py ile birleştirilir."""
    plan = []
    for slug, r in res.items():
        if not r["eksik"]:
            continue
        item = {k: v for k, v in r["item"].items() if k not in ("olgular", "sorular", "amac", "min_url")}
        ek = r["eksik"]
        tek = lambda e: f"{e['ad']} — bunu birincil kaynakta ara ve kaynağıyla kanıtla."
        if len(ek) <= EK_SORU_SINIRI:
            sorular = [tek(e) for e in ek]
        else:
            sorular = [tek(e) for e in ek[:EK_SORU_SINIRI - 1]]
            sorular.append("Şunları da ara ve kaynağıyla kanıtla: " + "; ".join(e["ad"] for e in ek[EK_SORU_SINIRI - 1:]))
        item["sorular"] = sorular
        item["amac"] = "YALNIZ şu eksik olguları bul (diğerleri başka çalıştırmada bulundu): " + "; ".join(e["ad"] for e in ek[:8])
        item["olgular"] = [{"ad": e["ad"], "ara": e["ara"]} for e in ek]
        # Açık min_url'u koru; dar plandaki min_url_required=2 varsa zayıflık eşiği
        # çalıştırıcıda zaten ondan türetilir. min_url=2 yazmak şema dışı olur.
        if "min_url" in r["item"]:
            item["min_url"] = r["item"]["min_url"]
        elif "min_url_required" not in r["item"]:
            item["min_url"] = 3
        plan.append(item)
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("dizinler", nargs="+")
    ap.add_argument("--etiket")
    ap.add_argument("--cikti")
    ap.add_argument("--eksik-plan", dest="eksik_plan")
    ap.add_argument("--esik", type=float, default=VARSAYILAN_ESIK)
    args = ap.parse_args(argv)
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"kapsama: plan okunamadı: {e}", file=sys.stderr)
        return 2
    for d in args.dizinler:
        if not Path(d).is_dir():
            print(f"kapsama: dizin yok: {d}", file=sys.stderr)
            return 2
    labels = args.etiket.split(",") if args.etiket else None
    if labels and len(labels) != len(args.dizinler):
        print("kapsama: --etiket sayısı dizin sayısına eşit olmalı", file=sys.stderr)
        return 2
    try:
        res = run(plan, args.dizinler, labels)
    except OlguHatasi as e:
        print(f"kapsama: {e}", file=sys.stderr)
        return 2
    text = render(res)
    if args.cikti:
        Path(args.cikti).write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.eksik_plan:
        ep = eksik_plan(res)
        Path(args.eksik_plan).write_text(json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"kapsama: {len(ep)} konu için ek plan → {args.eksik_plan}", file=sys.stderr)
    return 1 if any(r["kapsanan"] / max(1, r["toplam"]) < args.esik for r in res.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
