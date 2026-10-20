#!/usr/bin/env python3
"""İSTEĞE BAĞLI anlam (NLI) denetimi: alıntı sayfada VAR ama iddiayı DESTEKLEMİYOR olabilir mi? (varsayılan hat bunu çalıştırmaz)

`dogrula.py` (0 jeton) alıntının sayfada geçtiğini söyler; alıntı doğru olsa da iddia onu yanlış öznenin üstüne yapıştırmış olabilir
(ör. sayının başka bir konuya ait olması). Bu iş anlam gerektirir: çok dilli bir NLI modeli, (öncül = sayfadaki pencerenin metni,
hipotez = bulgunun iddia metni) çiftine entailment/neutral/contradiction olasılıkları verir; entailment düşükse bulgu işaretlenir.

Bu dosya saf Python'dur; ağır bağımlılıklar (torch + transformers) AYRI bir sanal ortamdadır. `anlam.py` çiftleri kurar, yanındaki
`anlam_calistir.py`'yi o ortamın Python'uyla alt süreç olarak çalıştırır (stdin JSONL → stdout JSONL) ve sonucu yazar.
Kurulum: `anlam_kur.sh` (bkz. SKILL.md "Anlam denetimi"). Yapılandırma: `nli_backend` (bkz. ayar.py şeması).

ÖLÇÜLMÜŞ DAVRANIŞ (198 gerçek doğrulanmış bulgu; öncül = sayfada alıntının ±300 karakter çevresi, hipotez = iddia):
  entailment < 0,05 → gerçek çiftlerde %11 yanlış alarm, karıştırılmış çiftlerin %36'sı yakalanır
  entailment < 0,10 → %13 / %46
  entailment < 0,30 → %22 / %68
  Öncül yalnızca alıntı olunca yanlış alarm %26'ya çıkar (tarih/sürüm ayrıntısı alıntı dışında kalır).
Yani GÜRÜLTÜLÜ bir "önce şuna bak" sinyalidir, hüküm DEĞİLDİR: karar "Doğrulandı" DEĞİŞMEZ; yalnız işaretlenir ve sıralanır.

Kullanım: anlam.py KOŞU_DIZINI [--onbellek D] [--notlar D] [--esik X] [--pencere N] [--isaretle] [--kuru] [--cikti anlam.md]
  KOŞU_DIZINI: KOŞU_DIZINI/dogrulama.json, KOŞU_DIZINI/kaynaklar, KOŞU_DIZINI/notlar-temiz varsayılanları.
Çıkış kodları: 0 tamam · 2 yapılandırma/dosya yok (kurulum yönlendirmesi) · 3 alt süreç hatası/zaman aşımı/eksik çıktı.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ayar  # noqa: E402
import denetle  # noqa: E402
import dogrula  # noqa: E402
import oku  # noqa: E402

CALISTIRICI = "anlam_calistir.py"   # bu dosyanın yanındaki NLI çalışanı (ayrı venv)
DEFAULT_ESIK = 0.10
DEFAULT_PENCERE = 300
DEFAULT_TIMEOUT = 900               # saniye: alt süreç (torch yükleme + tüm çiftler)
MIN_IDDIA = 12                      # bundan kısa iddia metni anlam denetimine değmez
GUCLU_CELISKI = 0.5                 # entailment düşük VE contradiction bu eşiğin üstündeyse "güçlü"
AZAMI_TOKEN = 512                   # anlam_calistir.py'ye geçen öncül+hipotez jeton sınırı (ölçülen pencere için yeterli)

# Kısmen / Anlam zayıf ön ekleri (madde işaretinden sonra, yan yana olabilir): tek ön eki tanır (ekleme noktası için).
ONEK_TEK_RE = re.compile(r"^\s*⚠ \[(?:Kısmen|Anlam zayıf):[^\]]*\]\s*")
KENAR_RE = re.compile(r'^[\s\u00a0—–\-,.;:·|*]+|[\s\u00a0—–\-,.;:·|*]+$')


class AnlamHatasi(Exception):
    """Anlam denetimi hatası. `kod`: 2 (yapılandırma/yol yok) ya da 3 (alt süreç/çıktı hatası)."""

    def __init__(self, mesaj, kod=3):
        super().__init__(mesaj)
        self.kod = kod


def iddia_metni(iddia):
    """Bulgu satırından anlam denetimine girecek iddia metni: madde işareti, Kısmen/Anlam ön eki, tırnak içi alıntılar,
    bağlantı (metin ve adres), künye parantezi ve çevre tire/noktalama atılır (dogrula.claim_prose + kenar temizliği)."""
    t = (iddia or "").strip()
    m = denetle.BULLET_RE.match(t)
    if m:
        t = t[m.end():]
    t = denetle.KISMEN_ONEK_RE.sub("", t)
    t = dogrula.claim_prose(t)
    t = re.sub(r"\s+", " ", t).strip()
    return KENAR_RE.sub("", t).strip()


def _oncul(url, alintilar, cache_dir, pencere):
    """Öncül: oku önbelleğindeki sayfada (oku.load) dogrula.norm/_quote_span ile bulunan İLK alıntının ±pencere karakter çevresi.
    Sayfa/alıntı bulunamazsa öncül alıntının kendisidir. Dönüş: (metin, "pencere"|"alinti")."""
    soz = alintilar[0] if alintilar else ""
    if url and cache_dir:
        page = oku.load(url, cache_dir=str(cache_dir))
        if page.get("ok"):
            base = dogrula.page_text_norm(page.get("markdown", ""))
            span = next((sp for sp in (dogrula._quote_span(base, q) for q in alintilar) if sp), None)
            if span:
                lo, hi = max(0, span[0] - pencere), span[1] + pencere
                return base[lo:hi], "pencere"
    return soz, "alinti"


def kur(rows, cache_dir=None, pencere=DEFAULT_PENCERE, oncul_hesapla=True):
    """dogrulama.json satırlarından (yalnız karar == "Doğrulandı") anlam çiftlerini kurar.

    Her çift: id, iddia (temizlenmiş hipotez), premise (öncül), not, kaynak, oncul_turu. Alıntısız bulgu ve 12 karakterden
    kısa iddia atlanır. `oncul_hesapla=False` (kuru çalıştırma): sayfa okunmaz, öncül alıntının kendisidir (ağ YOK)."""
    ciftler, atlanan = [], {"karar": 0, "alintisiz": 0, "kisa": 0}
    for r in rows:
        if r.get("karar") != "Doğrulandı":
            atlanan["karar"] += 1
            continue
        ev = dogrula.evidence(r.get("iddia") or "")
        if not ev["alinti"]:
            atlanan["alintisiz"] += 1
            continue
        metin = iddia_metni(r.get("iddia") or "")
        if len(metin) < MIN_IDDIA:
            atlanan["kisa"] += 1
            continue
        if oncul_hesapla:
            premise, tur = _oncul(r.get("url"), ev["alinti"], cache_dir, pencere)
        else:
            premise, tur = ev["alinti"][0], "alinti"
        ciftler.append({"id": len(ciftler), "iddia": metin, "premise": premise,
                        "not": r.get("not", ""), "kaynak": r.get("url", ""), "oncul_turu": tur})
    return ciftler, atlanan


def _dogrulama_yolu(kaynak):
    p = Path(kaynak)
    return p / "dogrulama.json" if p.is_dir() else p


def _rows_oku(yol):
    if not Path(yol).is_file():
        raise AnlamHatasi(f"doğrulama dosyası yok: {yol} (önce dogrula.py çalıştırın)", kod=2)
    try:
        data = json.loads(Path(yol).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise AnlamHatasi(f"doğrulama dosyası okunamadı: {yol} ({e})", kod=2)
    return data.get("satirlar", []) if isinstance(data, dict) else []


def _calistir(jsonl, backend, timeout):
    """NLI çalışanını ayrı venv Python'uyla alt süreç olarak koşturur (stdin JSONL). Ortam daraltılır; çevrimdışı sabitlenir."""
    import arastir
    cmd = [backend["python"], str(Path(__file__).resolve().with_name(CALISTIRICI)),
           "--model", backend["model_dir"], "--cihaz", backend.get("cihaz", "auto"), "--azami-token", str(AZAMI_TOKEN)]
    env = arastir.clean_env({"HF_HUB_OFFLINE": "1"})   # torch/transformers yalnız yerelden okur: ağ YOK
    return arastir.run_cmd(cmd, env=env, timeout=timeout, stdin_text=jsonl)


def _skorlari_ayristir(out):
    skorlar = {}
    for satir in (out or "").splitlines():
        satir = satir.strip()
        if not satir:
            continue
        try:
            d = json.loads(satir)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and "id" in d:
            skorlar[d["id"]] = d
    return skorlar


def run(dogrulama, notes_dir=None, cache_dir=None, esik=None, pencere=None, backend=None,
        timeout=DEFAULT_TIMEOUT, calistirici=None):
    """Anlam denetimini çalıştırır ve ham sonucu döner (notlar dosyalanmaz; işaretleme `isaretle` ile ayrı yapılır).

    `dogrulama`: koşu dizini ya da dogrulama.json yolu · `notes_dir`, `cache_dir`: bilgi/önbellek dizinleri.
    Hata: AnlamHatasi(kod=2) yapılandırma/yol yoksa; AnlamHatasi(kod=3) alt süreç hata/zaman aşımı/eksik çıktı verirse."""
    backend = backend if backend is not None else ayar.nli_backend()
    if not backend:
        raise AnlamHatasi("nli_backend yapılandırılmamış; kurulum için anlam_kur.sh ve SKILL.md 'Anlam denetimi' bölümüne bakın", kod=2)
    python = str(Path(backend["python"]).expanduser()) if backend.get("python") else ""
    if not python or not Path(python).is_file():
        raise AnlamHatasi(f"NLI Python bulunamadı: {backend.get('python')!r}; önce anlam_kur.sh ile sanal ortamı kurun (SKILL.md)", kod=2)
    model_dir = str(Path(backend["model_dir"]).expanduser()) if backend.get("model_dir") else ""
    if not model_dir or not Path(model_dir).is_dir():
        raise AnlamHatasi(f"NLI model dizini bulunamadı: {backend.get('model_dir')!r}; önce anlam_kur.sh ile modeli indirin (SKILL.md)", kod=2)
    be = {"python": python, "model_dir": model_dir, "cihaz": backend.get("cihaz", "auto")}
    esik = DEFAULT_ESIK if esik is None else float(esik)
    pencere = DEFAULT_PENCERE if pencere is None else int(pencere)

    rows = _rows_oku(_dogrulama_yolu(dogrulama))
    ciftler, atlanan = kur(rows, cache_dir, pencere)
    sonuc = {"cift": len(ciftler), "isaretli": 0, "guclu": 0, "esik": esik, "pencere": pencere,
             "sonuclar": [], "atlanan": atlanan}
    if not ciftler:
        return sonuc

    jsonl = "".join(json.dumps({"id": c["id"], "premise": c["premise"], "hypothesis": c["iddia"]}, ensure_ascii=False) + "\n"
                    for c in ciftler)
    rc, out, err, timed_out = (calistirici or _calistir)(jsonl, be, timeout)
    if timed_out:
        raise AnlamHatasi(f"NLI alt süreci {timeout} sn'de zaman aşımına uğradı (çift sayısı: {len(ciftler)}); "
                          "daha güçlü makinede ya da --esik/--pencere ile deneyin", kod=3)
    if rc != 0:
        raise AnlamHatasi(f"NLI alt süreci hata verdi (rc={rc}): {(err or out or '').strip()[:160]}", kod=3)
    skorlar = _skorlari_ayristir(out)
    for c in ciftler:
        e = skorlar.get(c["id"])
        if not e or "entailment" not in e:
            raise AnlamHatasi(f"NLI çıktısında {c['id']} kimlikli çift için satır yok (eksik/bozuk çıktı)", kod=3)
        ent, neu, con = float(e["entailment"]), float(e.get("neutral", 0.0)), float(e.get("contradiction", 0.0))
        isaret = ent < esik
        guclu = isaret and con >= GUCLU_CELISKI
        sonuc["sonuclar"].append({"not": c["not"], "iddia": c["iddia"], "kaynak": c["kaynak"], "oncul_turu": c["oncul_turu"],
                                  "ent": ent, "neu": neu, "con": con, "isaret": isaret, "guclu": guclu})
        if isaret:
            sonuc["isaretli"] += 1
        if guclu:
            sonuc["guclu"] += 1
    return sonuc


def isaretle(notes_dir, sonuc):
    """İşaretli (isaret) bulguların notlar kopyasındaki satırına, madde işaretinden SONRA (Kısmen ön eki varsa onun ARDINA)
    "⚠ [Anlam zayıf: ent=...]" ön ekini ekler (güçlüyse çelişki de yazılır). Idempotent. Döner: işaretlenen satır sayısı.

    Satır eşlemesi metin aramasıyla yapılır (dogrula.clean_copies yaklaşımı): madde gövdesi normalize edilip sonuçtaki iddiayla karşılaştırılır."""
    hedef = {}
    for r in sonuc.get("sonuclar", []):
        if r.get("isaret"):
            hedef.setdefault(r["not"], {})[re.sub(r"\s+", " ", r["iddia"]).strip()] = r
    isaretlenen = 0
    for name, bulgular in hedef.items():
        path = Path(notes_dir) / name
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        degisti = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            m = denetle.BULLET_RE.match(stripped)
            if not m:
                continue
            body = re.sub(r"\s+", " ", denetle.KISMEN_ONEK_RE.sub("", stripped[m.end():]).strip())
            r = bulgular.get(body)
            if not r:
                continue
            off = len(line) - len(line.lstrip())
            goto, var = off + m.end(), False
            while True:
                p = ONEK_TEK_RE.match(line[goto:])
                if not p:
                    break
                if "Anlam zayıf:" in p.group(0):
                    var = True
                goto += p.end()
            if var:   # idempotent: zaten işaretliyse dokunma
                continue
            onek = f"⚠ [Anlam zayıf: ent={r['ent']:.2f}" + (f" çelişki={r['con']:.2f}" if r.get("guclu") else "") + "] "
            lines[i] = line[:goto] + onek + line[goto:]
            isaretlenen += 1
            degisti = True
        if degisti:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return isaretlenen


def render(sonuc):
    """`anlam.md` gövdesi: veri uyarısı, özet, en düşük entailment'tan başlayan işaretli tablo ve Sınırlama paragrafı."""
    L = [denetle.VERI_UYARISI, "", "# Anlam denetimi (isteğe bağlı, NLI)", "",
         f"{sonuc['cift']} çift hesaplandı · **{sonuc['isaretli']} işaretli** (entailment < {sonuc['esik']:.2f}) · "
         f"{sonuc['guclu']} güçlü (düşük entailment + contradiction ≥ {GUCLU_CELISKI:.1f}). Öncül penceresi ±{sonuc['pencere']} karakter.",
         "", "Karar değişmez: işaret, 'alıntı sayfada var ama iddiayı desteklemiyor olabilir' demektir, hüküm değil.", ""]
    isaretliler = sorted((r for r in sonuc.get("sonuclar", []) if r.get("isaret")), key=lambda r: r["ent"])
    L += ["| Not | İddia | ent | con | Kaynak |", "|---|---|---:|---:|---|"]
    if isaretliler:
        for r in isaretliler:
            iddia = re.sub(r"\s+", " ", r["iddia"])[:120]
            L.append(f"| {r['not']} | {iddia} | {r['ent']:.2f} | {r['con']:.2f} | {r['kaynak']} |")
    else:
        L.append("| — | İşaretli çift yok | — | — | — |")
    L += ["", "## Sınırlama", "",
          "Bu bir KANIT DEĞİLDİR; yalnızca 'önce şuna bak' sıralamasıdır. Ölçülen davranış (198 gerçek doğrulanmış bulgu; öncül = sayfada "
          "alıntının ±300 karakter çevresi, hipotez = bulgunun iddia metni): entailment < 0,05 → gerçek çiftlerde %11 yanlış alarm, "
          "karıştırılmış çiftlerin %36'sı yakalanır; < 0,10 → %13 / %46; < 0,30 → %22 / %68. Öncül yalnızca alıntı olunca yanlış alarm %26'ya "
          "çıkar (tarih/sürüm ayrıntısı alıntının dışında kalır). Çeviri ve çok kısa/etiket iddialarda yanlış alarm artar; İngilizce dışı "
          "kaynaklarda model zayıflar. Yalnız 'Doğrulandı' satırları denenir: işaretlenen bulgu RAPORA GİRMEZ diye bir kural yoktur, "
          "yalnız kaynağı elle açıp bak.", ""]
    return "\n".join(L)


def yaz(cikti, sonuc):
    """`anlam.md` (rapor) ve kardeşi `anlam.json` (ham skorlar) yazar. Döner: yazılan md yolu."""
    p = Path(cikti)
    p.write_text(render(sonuc), encoding="utf-8")
    p.with_suffix(".json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dizin", help="koşu dizini (dizin/dogrulama.json, dizin/kaynaklar, dizin/notlar-temiz)")
    ap.add_argument("--onbellek", help="sayfa deposu dizini (varsayılan: dizin/kaynaklar)")
    ap.add_argument("--notlar", help="notlar dizini (varsayılan: dizin/notlar-temiz)")
    ap.add_argument("--esik", type=float, help=f"entailment işaretleme eşiği (0..1; varsayılan {DEFAULT_ESIK})")
    ap.add_argument("--pencere", type=int, help=f"öncül penceresi, alıntının ±karakteri (50..2000; varsayılan {DEFAULT_PENCERE})")
    ap.add_argument("--isaretle", action="store_true", help="işaretli bulguları notlar dizininde '⚠ [Anlam zayıf: …]' ile işaretle")
    ap.add_argument("--kuru", action="store_true", help="model çağırma; yalnız kaç çiftin hesaplanacağını yaz")
    ap.add_argument("--cikti", help="rapor yolu (varsayılan: dizin/anlam.md; yanına dizin/anlam.json yazılır)")
    a = ap.parse_args(argv)
    base = Path(a.dizin)
    notlar = a.notlar or str(base / "notlar-temiz")
    cikti = a.cikti or str(base / "anlam.md")

    if a.kuru:
        try:
            rows = _rows_oku(_dogrulama_yolu(base))
        except AnlamHatasi as e:
            print(f"anlam: {e}", file=sys.stderr)
            return e.kod
        ciftler, _ = kur(rows, None, oncul_hesapla=False)
        print(f"anlam: {len(ciftler)} çift hesaplanacak (kuru); model çağrılmadı")
        return 0

    try:
        sonuc = run(base, notlar, a.onbellek or str(base / "kaynaklar"), esik=a.esik, pencere=a.pencere)
    except ayar.ConfigError as e:
        print(f"anlam: {e}", file=sys.stderr)
        return 78
    except AnlamHatasi as e:
        print(f"anlam: {e}", file=sys.stderr)
        return e.kod
    yaz(cikti, sonuc)
    print(render(sonuc))
    print(f"(anlam denetimi yazıldı: {cikti})")
    if a.isaretle:
        n = isaretle(notlar, sonuc)
        print(f"anlam: {n} satır işaretlendi ({notlar})")
    return 0


if __name__ == "__main__":
    sys.exit(main())