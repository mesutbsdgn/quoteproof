#!/usr/bin/env python3
"""Uzlaşı: aynı plan konusunun BAĞIMSIZ koşularından (farklı çalışan, model ya da tekrar) gelen doğrulanmış notları birleştirir (0 LLM jetonu, yalnız standart kütüphane).

Neden: tek bir çalışan çalıştırması konunun anahtar olgularının yaklaşık %80'ini kapsıyor ve çalıştırmadan çalıştırmaya çok değişiyor (ölçüm: aynı konuda en kötü çalıştırma 8/12, en iyi 12/12;
iki çalıştırmanın birleşimi ≈ %92, üçünün ≈ %96). Hafif kip bir çalıştırmayı düz isteme yakın maliyete indirdi; birkaç hafif çalıştırma birleştirilince kapsama ve tutarlılık artar,
ve "kaç çalıştırma aynı iddiayı doğruladı" ucuz bir güven sinyali olur.

Girdi: her biri bir çalıştırmanın `notlar-temiz/` (ya da `notlar/`) dizini. Aynı dosya adı (slug) aynı konudur.
Kullanım:
  python3 uzlas.py KOSU1/notlar-temiz KOSU2/notlar-temiz [KOSU3/...] [--cikti uzlasi.md] [--yaz BIRLESIK_DIZIN] [--etiket a,b,c]
Çıktı:
  uzlasi.md      konu başına: iddia kümeleri, kaç çalıştırmada doğrulandı, yalnız tek çalıştırmada çıkanlar, çalıştırma başına katkı
  BIRLESIK_DIZIN/<slug>.md   her kümenin temsilci bulgusu `**[k/N çalıştırma]**` önekiyle; dogrula.py/denetle.py'den yeniden geçirilebilir
Bu bir sezgiseldir: iki bulgu "aynı iddia" sayılırsa alıntı sözcük örtüşmesi ≥0,6 ya da aynı sayfada ≥0,35 örtüşme/ortak sayıdır. Çelişkiyi (aynı konuda farklı sayı) bulmaz;
onu koordinatör notlardan okur.
"""
import argparse
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import denetle  # noqa: E402
import dogrula  # noqa: E402

OVERLAP_SAME = 0.6          # alıntı sözcük örtüşmesi (küçük kümeye göre): bu ve üstü → aynı iddia
OVERLAP_SAME_PAGE = 0.35    # aynı sayfada: bu örtüşme ya da ortak sayı yeter
MIN_RUNS = 2


def _toks(text):
    return set(re.findall(r"\w{3,}", dogrula.norm(text)))


def _url_key(u):
    return u.split("#")[0].rstrip("/").replace("://www.", "://")


def findings(path):
    """Notun "Alıntılı bulgular" maddeleri: [{satir, metin, q, urls, nums}]. Maddesi URL'siz ya da alıntısız olanlar da alınır (q: iddia metni)."""
    _, questions = denetle.parse_note(Path(path))
    out = []
    for q in questions:
        for line in q["bolumler"].get("Alıntılı bulgular", []):
            m = denetle.BULLET_RE.match(line.strip())
            if not m or "](" not in line:
                continue
            body = line.strip()[m.end():]
            ev = dogrula.evidence(body)
            quote = " ".join(ev["alinti"])
            claim = re.sub(r"\[[^\]]*\]\([^)]*\)", "", body)
            out.append({"satir": line.strip(), "metin": body, "q": _toks(quote) if quote else _toks(claim),
                        "urls": {_url_key(u) for u in denetle.bullet_urls(body)}, "nums": set(ev["sayi"]), "alinti": bool(quote)})
    return out


def same_claim(a, b):
    small = max(1, min(len(a["q"]), len(b["q"])))
    ov = len(a["q"] & b["q"]) / small
    if ov >= OVERLAP_SAME:
        return True
    return bool(a["urls"] & b["urls"]) and (ov >= OVERLAP_SAME_PAGE or bool(a["nums"] & b["nums"]))


def cluster(per_run):
    """per_run: {etiket: [bulgu]} → [{etiket: [bulgu, ...]}]. Aynı çalıştırmanın iki bulgusu aynı kümeye girmez (çalıştırma başına en çok bir üye sayılır)."""
    clusters = []
    for label, fs in per_run.items():
        for f in fs:
            for c in clusters:
                if label not in c and any(same_claim(f, g) for gs in c.values() for g in gs):
                    c[label] = [f]
                    break
            else:
                clusters.append({label: [f]})
    return clusters


def representative(c):
    """Küme temsilcisi: alıntılı olanlardan en uzun alıntıyı taşıyan (bilgi en çok), yoksa ilk üye."""
    members = [f for fs in c.values() for f in fs]
    quoted = [f for f in members if f["alinti"]]
    return max(quoted, key=lambda f: len(f["q"])) if quoted else members[0]


def merge_note(slug, runs, clusters, gaps):
    n = len(runs)
    L = [f"# {slug} (birleşik, {n} çalıştırma)", "", "## Birleşik bulgular", "### Özet",
         f"{n} bağımsız çalıştırmanın doğrulanmış bulgularının birleşimi. Her bulgunun önündeki `[k/{n} çalıştırma]`, aynı iddianın kaç çalıştırmada bağımsız olarak bulunduğunu gösterir.",
         "", "### Alıntılı bulgular"]
    for c in sorted(clusters, key=lambda c: -len(c)):
        rep = representative(c)
        body = rep["metin"]
        L.append(f"- **[{len(c)}/{n} çalıştırma]** {body}")
    L += ["", "### Çıkarımlar", "- (Çalışan çıkarımları birleştirilmedi: doğrulanmamış yorumdur; koordinatör kendi çıkarımını bulgulardan yapsın.)",
          "", "### Boşluklar"]
    L += [f"- ({lab}) {g}" for lab, g in gaps] or ["- (belirtilmedi)"]
    return "\n".join(L) + "\n"


def gap_lines(path):
    _, questions = denetle.parse_note(Path(path))
    out = []
    for q in questions:
        for line in q["bolumler"].get("Boşluklar", []):
            m = denetle.BULLET_RE.match(line.strip())
            if m and line.strip()[m.end():].strip():
                out.append(line.strip()[m.end():].strip())
    return out


def run(dirs, labels=None):
    """dirs: not dizinleri (çalıştırma başına bir). Döner: {slug: {"runs": [...], "clusters": [...], "per_run": {...}, "gaps": [...]}}."""
    labels = labels or [Path(d).resolve().parent.name if Path(d).name.startswith("notlar") else Path(d).name for d in dirs]
    if len(set(labels)) != len(labels):
        labels = [f"{l}#{i + 1}" for i, l in enumerate(labels)]
    slugs = {}
    for lab, d in zip(labels, dirs):
        for p in sorted(Path(d).glob("*.md")):
            if p.name == "DISLANAN.md":
                continue
            slugs.setdefault(p.stem, {})[lab] = p
    out = {}
    for slug, paths in slugs.items():
        per_run = {lab: findings(p) for lab, p in paths.items()}
        gaps = [(lab, g) for lab, p in paths.items() for g in gap_lines(p)]
        out[slug] = {"runs": list(paths), "per_run": per_run, "clusters": cluster(per_run), "gaps": gaps}
    return out


def render(res):
    L = ["# Uzlaşı raporu (çalıştırmalar arası tutarlılık ve birleşik kapsama)", ""]
    for slug, r in res.items():
        n, cl = len(r["runs"]), r["clusters"]
        L += [f"## {slug}", "", f"- Çalıştırma sayısı: {n} ({', '.join(r['runs'])}); çalıştırma başına bulgu: " + ", ".join(f"{k} {len(v)}" for k, v in r["per_run"].items()),
              f"- Ayrı iddia kümesi: **{len(cl)}**"]
        dist = {}
        for c in cl:
            dist[len(c)] = dist.get(len(c), 0) + 1
        L.append("- Kaç çalıştırmada bulundu: " + ", ".join(f"{k} çalıştırma → {v} iddia" for k, v in sorted(dist.items(), reverse=True)))
        for lab in r["runs"]:
            mine = sum(1 for c in cl if lab in c)
            only = sum(1 for c in cl if list(c) == [lab])
            L.append(f"- {lab}: kümelerin %{100 * mine // max(1, len(cl))} kadarını kapsıyor ({mine}/{len(cl)}); yalnız bu çalıştırmada çıkan: {only}")
        if n < MIN_RUNS:
            L.append("- ⚠ Tek çalıştırma var: uzlaşı sinyali yok.")
        singles = [c for c in cl if len(c) == 1]
        if singles and n >= MIN_RUNS:
            L += ["", f"### Yalnız tek çalıştırmada çıkanlar ({len(singles)}): tek başına güvenme, ikinci kaynak/çalıştırma ara", ""]
            for c in singles[:15]:
                lab = next(iter(c))
                L.append(f"- ({lab}) {representative(c)['metin'][:170]}")
        L.append("")
    L.append("Not: iki bulgunun \"aynı iddia\" sayılması sezgiseldir (alıntı sözcük örtüşmesi / aynı sayfa + ortak sayı). Çelişki (aynı konuda farklı sayı) aranmaz; çalıştırma başına özetleri koordinatör okur.")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dizinler", nargs="+", help="çalıştırma başına bir not dizini (notlar-temiz/ önerilir)")
    ap.add_argument("--cikti", help="rapor dosyası (varsayılan: ekrana)")
    ap.add_argument("--yaz", help="birleşik notların yazılacağı dizin")
    ap.add_argument("--etiket", help="çalıştırma etiketleri, virgülle (varsayılan: dizin adlarından)")
    args = ap.parse_args(argv)
    for d in args.dizinler:
        if not Path(d).is_dir():
            print(f"uzlas: dizin yok: {d}", file=sys.stderr)
            return 2
    labels = args.etiket.split(",") if args.etiket else None
    if labels and len(labels) != len(args.dizinler):
        print("uzlas: --etiket sayısı dizin sayısına eşit olmalı", file=sys.stderr)
        return 2
    res = run(args.dizinler, labels)
    if not res:
        print("uzlas: hiçbir not bulunamadı", file=sys.stderr)
        return 2
    report = render(res)
    if args.cikti:
        Path(args.cikti).write_text(report, encoding="utf-8")
    else:
        print(report)
    if args.yaz:
        out = Path(args.yaz)
        out.mkdir(parents=True, exist_ok=True)
        for slug, r in res.items():
            (out / f"{slug}.md").write_text(merge_note(slug, r["runs"], r["clusters"], r["gaps"]), encoding="utf-8")
        print(f"uzlas: {len(res)} birleşik not → {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
