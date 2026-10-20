#!/usr/bin/env python3
"""Kaynak kasası: okunan sayfaları kalıcı, aranabilir bir SQLite FTS5 deposunda tutar (0 LLM jetonu, yalnız standart kütüphane).

Neden: oku.py'nin sayfa önbelleği (`kaynaklar/`) her koşuda baştan okunur ve aramada tam metin taraması yoktur. Kasa, okunan
sayfaları BM25 sıralı tam metin aramasıyla kalıcı kılar; ayrıca aynı makalenin farklı alan adlarında yayımlanmış kopyalarını
("syndication") tek kaynak sayar. Böylece "bu iddiayı kaç BAĞIMSIZ alan adı doğruluyor?" sorusu ve "hangi kaynak yeniden
doğrulanmalı?" sorusu ucuza cevaplanır.

Veritabanı: `--db`, yoksa QUOTEPROOF_KASA ortam değişkeni, yoksa ~/.local/share/quoteproof/kasa.db (üst dizin gerekirse oluşturulur).

Girdi: oku.py önbellek dosyaları (her biri <24hex>.json; alanlar: istenen_url, ok, markdown, fetched_at, isteğe bağlı baslik/yontem).
Yalnız `ok=true` ve `markdown` boş olmayan dosyalar alınır; bozuk JSON ve ok=false atlanır. Sayfalar kanonik URL anahtarıyla
kaydedilir (şema/host küçük harf, http→https, www atılır, fragment ve izleme parametreleri atılır): aynı sayfanın iki URL biçimi tek kayıt olur.

Kullanım:
  python3 kasa.py ekle KAYNAKLAR_DIZINI [DIZIN ...]
  python3 kasa.py ara "sorgu" [--en-cok 10] [--eski-gun 30] [--json]
  python3 kasa.py kopyalar
  python3 kasa.py istatistik
  python3 kasa.py guncelle-plan PLAN.json ESKI_DIZIN [--cikti YOL] [--eski-gun 30]
Çıkış: 0 tamam · 1 hata · 2 kullanım hatası
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.dont_write_bytecode = True

PASAJ_HEDEF = 800          # pasaj başına ~karakter (paragraf sınırında biriktirilir)
SHINGLE_N = 8              # kopya tespitinde kayan pencere sözcük sayısı
SHINGLE_SINIR = 6000       # sayfanın yalnız ilk bu kadar karakteri karşılaştırılır
JACCARD_ESIK = 0.85        # bu ve üstü kopya kabul edilir
GRUP_KIMLIK_UZUNLUK = 12   # sha1 hex ilk kaç karakter grup kimliği olur
VARSAYILAN_ESKI_GUN = 30
OZET_UZUNLUK = 150
URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
IZLEME_ONEK_RE = re.compile(r"utm_|^aff", re.I)     # izleme parametreleri: utm_*, aff*
IZLEME_AD_RE = frozenset({"fbclid", "gclid", "ref"})
VARSAYILAN_PORT = {"http": "80", "https": "443"}

SEMA_SAYFA = """CREATE TABLE IF NOT EXISTS sayfa(
    url TEXT PRIMARY KEY, host TEXT, baslik TEXT, alindi REAL,
    uzunluk INTEGER, icerik_hash TEXT, kopya_grubu TEXT)"""
SEMA_PASAJ = """CREATE VIRTUAL TABLE IF NOT EXISTS pasaj USING fts5(
    url UNINDEXED, sira UNINDEXED, metin, tokenize='unicode61 remove_diacritics 2')"""


class KasaHatasi(Exception):
    """Kasayla ilgili anlamlı kullanım/veri hatası."""


def veritabani_yolu(db=None):
    """--db > QUOTEPROOF_KASA > ~/.local/share/quoteproof/kasa.db sırasıyla çözülür."""
    if db:
        return Path(db).expanduser()
    env = os.environ.get("QUOTEPROOF_KASA")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".local" / "share" / "quoteproof" / "kasa.db"


def baglan(db=None, olustur=False):
    """Veritabanını aç, şemayı kur. olustur=True ise üst dizin yaratılır ve yeni dosya oluşturulabilir;
    aksi hâlde veritabanı yoksa KasaHatasi. sqlite3.Connection döner."""
    p = veritabani_yolu(db)
    yeni = str(p) == ":memory:" or not p.exists()
    if yeni and not olustur:
        raise KasaHatasi(f"kasa veritabanı yok: {p} (önce `ekle` çalıştır)")
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.execute(SEMA_SAYFA)
    con.execute(SEMA_PASAJ)
    return con


def _host(url):
    """URL'den alan adı (küçük harf, baştaki www atılır, port atılır)."""
    try:
        net = urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    net = net.split("@")[-1].split(":")[0]
    return net[4:] if net.startswith("www.") else net


def url_kanonik(url):
    """URL'yi kopya/kaynak sayımı için kanonikleştirir: şema ve host küçük harf, http→https, `www.` atılır,
    fragment atılır, izleme parametreleri (utm_*, fbclid, gclid, ref, aff*) atılır, kalan sorgu parametreleri
    sıralanır, yolun sonundaki '/' (kök hariç) ve varsayılan port atılır. Kanonikleştirilemeyen girdide "" döner.

    Kanonik anahtar sayesinde aynı sayfanın iki URL biçimi (www'li/www'siz, http/https, izleme parametreli) TEK kayıt olur.
    """
    try:
        p = urlsplit((url or "").strip())
    except (ValueError, AttributeError):
        return ""
    if not p.netloc:
        return ""
    ham_sema = (p.scheme or "").lower()
    sema = "https" if ham_sema in ("", "http") else ham_sema
    netloc = p.netloc.lower()
    if "@" in netloc:
        netloc = netloc.split("@")[-1]
    host, _, port = netloc.partition(":")
    if host.startswith("www."):
        host = host[4:]
    if port and port != VARSAYILAN_PORT.get(ham_sema):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    pairs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not IZLEME_ONEK_RE.search(k) and k.lower() not in IZLEME_AD_RE]
    sorgu = urlencode(sorted(pairs))
    yol = p.path.rstrip("/") or "/"
    return urlunsplit((sema, netloc, yol, sorgu, ""))


def _sha1(metin):
    return hashlib.sha1(metin.encode("utf-8", "ignore")).hexdigest()


def _iso(epoch):
    """Epoch float → YYYY-AA-GG (yerel saat)."""
    return time.strftime("%Y-%m-%d", time.localtime(epoch)) if epoch else ""


def normalle(metin):
    """Kopya karşılaştırması için: küçük harf; URL'ler ve rakam-olmayan işaretler atılır; boşluk daraltılır."""
    t = (metin or "").lower()
    t = re.sub(r"https?://\S+|www\.\S+", " ", t)
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def shingle_kumesi(metin, n=SHINGLE_N, sinir=SHINGLE_SINIR):
    """Metnin ilk `sinir` karakterinden n sözcüklük kayan pencere kümesi."""
    ws = normalle(metin)[:sinir].split()
    if not ws:
        return set()
    if len(ws) < n:
        return {tuple(ws)}
    return {tuple(ws[i:i + n]) for i in range(len(ws) - n + 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def pasajlara_bol(metin, hedef=PASAJ_HEDEF):
    """Paragraf-birikimli pasajlar: paragraflar ~hedef karaktere kadar birleşir; tek paragraf hedeften uzunsa sert bölünür."""
    out, buf = [], ""
    for parca in re.split(r"\n\s*\n", metin or ""):
        parca = parca.strip()
        if not parca:
            continue
        if len(parca) > hedef:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(parca[i:i + hedef] for i in range(0, len(parca), hedef))
            continue
        if buf and len(buf) + 1 + len(parca) > hedef:
            out.append(buf)
            buf = parca
        else:
            buf = parca if not buf else f"{buf}\n{parca}"
    if buf:
        out.append(buf)
    return out


def _fts_ifade(sorgu, operator=" "):
    """FTS5 sözdizimi hatası çıkarmayan sorgu: her sözcük çift tırnağa alınır (içteki tırnak katlanır), `operator` ile birleşir.
    Yalnız harf/rakam içeren sözcükler alınır (salt işaretler FTS5'te boş ifade üretip hata verir)."""
    kelimeler = [w for w in re.findall(r"\S+", sorgu or "") if re.search(r"\w", w, re.UNICODE)]
    ifade = operator.join(f'"{w.replace(chr(34), chr(34) * 2)}"' for w in kelimeler)
    return ifade, kelimeler


def sayfalari_yukle(dizin):
    """Bir önbellek dizinindeki geçerli sayfaları oku → [{"url","host","baslik","alindi","metin"}]. Bozuk JSON / ok=false / boş markdown atlanır."""
    out = []
    for dosya in sorted(Path(dizin).glob("*.json")):
        try:
            data = json.loads(dosya.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not data.get("ok"):
            continue
        metin = data.get("markdown") or ""
        if not isinstance(metin, str) or not metin.strip():
            continue
        url = data.get("istenen_url") or data.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        try:
            alindi = float(data.get("fetched_at") or 0.0)
        except (TypeError, ValueError):
            alindi = 0.0
        baslik = data.get("baslik") or ""
        out.append({"url": url.strip(), "host": _host(url), "baslik": baslik if isinstance(baslik, str) else "",
                    "alindi": alindi, "metin": metin})
    return out


def _grup_hesapla(con):
    """Tüm sayfaların shingle kümelerinden kopya gruplarını yeniden atar (union-find). Yeni grupları döner."""
    satirlar = con.execute("SELECT url, alindi FROM sayfa").fetchall()
    kumeler, bilgi = {}, {}
    for r in satirlar:
        metin = "\n".join(x[0] for x in con.execute(
            "SELECT metin FROM pasaj WHERE url=? ORDER BY sira", (r["url"],)).fetchall())
        kumeler[r["url"]] = shingle_kumesi(metin)
        bilgi[r["url"]] = r["alindi"] or 0.0
    urller = list(kumeler)
    ebeveyn = {u: u for u in urller}

    def kok(u):
        while ebeveyn[u] != u:
            ebeveyn[u] = ebeveyn[ebeveyn[u]]
            u = ebeveyn[u]
        return u

    for i in range(len(urller)):
        for j in range(i + 1, len(urller)):
            a, b = kumeler[urller[i]], kumeler[urller[j]]
            lo, hi = (len(a), len(b)) if len(a) <= len(b) else (len(b), len(a))
            if not hi or lo / hi < JACCARD_ESIK:   # Jaccard ≤ lo/hi, eşiğe ulaşamaz
                continue
            if jaccard(a, b) >= JACCARD_ESIK:
                ebeveyn[kok(urller[i])] = kok(urller[j])

    gruplar = {}
    for u in urller:
        gruplar.setdefault(kok(u), []).append(u)
    sonuc = {}
    for uyeler in gruplar.values():
        en_eski = min(uyeler, key=lambda u: (bilgi[u], u))
        gid = _sha1(en_eski)[:GRUP_KIMLIK_UZUNLUK]
        sonuc[gid] = sorted(uyeler)
    con.execute("UPDATE sayfa SET kopya_grubu=NULL")
    for gid, uyeler in sonuc.items():
        con.executemany("UPDATE sayfa SET kopya_grubu=? WHERE url=?", [(gid, u) for u in uyeler])
    return sonuc


def ekle(db, dizinler):
    """Önbellek dizinlerini kasaya ekler/günceller. Sayfalar KANONİK URL anahtarıyla kaydedilir (aynı sayfanın iki URL
    biçimi tek kayıt). Aynı URL yalnız fetched_at daha yeniyse yenilenir (idempotent).

    Döner: {"eklendi","yenilendi","atlandi","gecerli","kopya_grubu","sayfa"}.
    """
    con = baglan(db, olustur=True)
    eklendi = yenilendi = atlandi = gecerli = 0
    try:
        for dizin in dizinler:
            sayfalar = sayfalari_yukle(dizin)
            for s in sayfalar:
                gecerli += 1
                url = url_kanonik(s["url"]) or s["url"]
                var = con.execute("SELECT alindi FROM sayfa WHERE url=?", (url,)).fetchone()
                if var is not None:
                    if s["alindi"] <= (var["alindi"] or 0.0):
                        atlandi += 1
                        continue
                    con.execute("DELETE FROM pasaj WHERE url=?", (url,))
                    yenilendi += 1
                else:
                    eklendi += 1
                pasajlar = pasajlara_bol(s["metin"])
                con.executemany("INSERT INTO pasaj(url, sira, metin) VALUES (?,?,?)",
                                [(url, i, p) for i, p in enumerate(pasajlar)])
                con.execute("INSERT INTO sayfa(url, host, baslik, alindi, uzunluk, icerik_hash, kopya_grubu) "
                            "VALUES (?,?,?,?,?,?,NULL) "
                            "ON CONFLICT(url) DO UPDATE SET host=excluded.host, baslik=excluded.baslik, "
                            "alindi=excluded.alindi, uzunluk=excluded.uzunluk, icerik_hash=excluded.icerik_hash",
                            (url, s["host"], s["baslik"], s["alindi"], len(s["metin"]), _sha1(s["metin"])))
        gruplar = _grup_hesapla(con)
        con.commit()
    finally:
        con.close()
    kopya = sum(1 for u in gruplar.values() if len(u) > 1)
    return {"eklendi": eklendi, "yenilendi": yenilendi, "atlandi": atlandi, "gecerli": gecerli,
            "kopya_grubu": kopya, "sayfa": sum(len(u) for u in gruplar.values())}


def _pasaj_ozeti(metin, kelimeler, n=OZET_UZUNLUK):
    """Eşleşen sözcüğün çevresinden n karakterlik özet; bulunamazsa metnin başı."""
    low = (metin or "").lower()
    pos = -1
    for k in kelimeler:
        p = low.find(k.lower())
        if p >= 0 and (pos < 0 or p < pos):
            pos = p
    if pos < 0:
        return (metin or "")[:n]
    bas = max(0, pos - n // 3)
    return (metin or "")[bas:bas + n]


def ara(db, sorgu, en_cok=10, eski_gun=VARSAYILAN_ESKI_GUN, simdi=None):
    """BM25 sıralı (bm25() küçük = iyi) arama. Aynı kopya_grubundan yalnız en iyi sonuç; yaş > eski_gun ise yeniden doğrulama bayrağı."""
    kelimeler = re.findall(r"\S+", sorgu or "")
    if not kelimeler:
        raise KasaHatasi("boş sorgu")
    con = baglan(db)
    try:
        satirlar = []
        ifade_var = False
        for operator in (" ", " OR "):
            ifade, kelimeler = _fts_ifade(sorgu, operator)
            if not kelimeler:            # yalnız işaretsel sorgu: eşleşme yok
                break
            ifade_var = True
            try:
                satirlar = con.execute("SELECT url, metin, bm25(pasaj) AS skor FROM pasaj "
                                       "WHERE pasaj MATCH ? ORDER BY skor", (ifade,)).fetchall()
            except sqlite3.OperationalError as e:
                raise KasaHatasi(f"FTS sorgusu geçersiz: {e}")
            if satirlar:
                break
        if not ifade_var:
            kelimeler = []
        simdi = time.time() if simdi is None else simdi
        out, gorulen = [], set()
        for r in satirlar:
            syf = con.execute("SELECT host, baslik, alindi, kopya_grubu FROM sayfa WHERE url=?", (r["url"],)).fetchone()
            if syf is None:
                continue
            gid = syf["kopya_grubu"]
            anahtar = gid or r["url"]
            if anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            kopya = con.execute("SELECT COUNT(*) FROM sayfa WHERE kopya_grubu=?", (gid,)).fetchone()[0] if gid else 1
            yas = max(0, int((simdi - (syf["alindi"] or simdi)) // 86400))
            out.append({"url": r["url"], "host": syf["host"], "baslik": syf["baslik"],
                        "tarih": _iso(syf["alindi"]), "yas_gun": yas, "pasaj": _pasaj_ozeti(r["metin"], kelimeler),
                        "kopya_sayisi": kopya, "kopya_grubu": gid, "eski": yas > eski_gun, "skor": r["skor"]})
            if len(out) >= en_cok:
                break
        return out
    finally:
        con.close()


def kopya_gruplari(db):
    """{grup_kimliği: [url, ...]} — tüm gruplar (tek üyeli gruplar dahil)."""
    con = baglan(db)
    try:
        out = {}
        for r in con.execute("SELECT url, kopya_grubu FROM sayfa ORDER BY url"):
            out.setdefault(r["kopya_grubu"] or r["url"], []).append(r["url"])
        return out
    finally:
        con.close()


def bagimsiz_alan_adi_sayisi(urls, db):
    """Verilen URL'lerin temsil ettiği BAĞIMSIZ kaynak sayısı: kopya grubu (aynı metnin alan adları) TEK sayılır."""
    con = baglan(db)
    try:
        birim = set()
        for u in urls:
            c = url_kanonik(u) or u
            r = con.execute("SELECT host, kopya_grubu FROM sayfa WHERE url=?", (c,)).fetchone()
            gid = r["kopya_grubu"] if r else None
            if gid:
                n = con.execute("SELECT COUNT(*) FROM sayfa WHERE kopya_grubu=?", (gid,)).fetchone()[0]
                if n > 1:
                    birim.add(("grup", gid))
                    continue
            birim.add(("host", r["host"] if r else _host(c)))
        return len(birim)
    finally:
        con.close()


def istatistik(db):
    """Sayfa/pasaj/kopya grubu sayıları, en eski-en yeni alınma tarihi, host sayısı."""
    con = baglan(db)
    try:
        sayfa = con.execute("SELECT COUNT(*) FROM sayfa").fetchone()[0]
        pasaj = con.execute("SELECT COUNT(*) FROM pasaj").fetchone()[0]
        host = con.execute("SELECT COUNT(DISTINCT host) FROM sayfa").fetchone()[0]
        grup = con.execute("SELECT COUNT(*) FROM (SELECT kopya_grubu FROM sayfa WHERE kopya_grubu IS NOT NULL "
                           "GROUP BY kopya_grubu HAVING COUNT(*)>1)").fetchone()[0]
        aralik = con.execute("SELECT MIN(alindi), MAX(alindi) FROM sayfa").fetchone()
        return {"sayfa": sayfa, "pasaj": pasaj, "kopya_grubu": grup, "host": host,
                "en_eski": _iso(aralik[0] or 0), "en_yeni": _iso(aralik[1] or 0)}
    finally:
        con.close()


def _not_urls(metin):
    return [u.rstrip(".,;:") for u in URL_RE.findall(metin or "")]


def guncelle_plan(db, plan_yolu, eski_dizin, cikti=None, eski_gun=VARSAYILAN_ESKI_GUN):
    """PLAN.json'daki her konunun `kisitlar` metnine güncelleme kipi cümlesi ekler; orijinali değiştirmez.

    Kaynaklar KASADAN, yalnız ESKI_DIZIN/kaynaklar'dan gelen URL'lerden seçilir ve konu, ESKI_DIZIN/notlar/<slug>.md
    içindeki URL'lerle eşlenir. Döner: {"plan": yeni_plan, "konu": güncellenen_konu, "cikti": çıktı_yolu}.
    """
    plan_p = Path(plan_yolu)
    try:
        plan = json.loads(plan_p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise KasaHatasi(f"plan okunamadı/geçersiz: {e}")
    if not isinstance(plan, list):
        raise KasaHatasi("plan bir liste olmalı")
    eski = Path(eski_dizin)
    kaynak_diz = eski / "kaynaklar"
    if not kaynak_diz.is_dir():
        raise KasaHatasi(f"kaynaklar dizini yok: {kaynak_diz}")
    con = baglan(db)
    try:
        kasa_urlleri = {url_kanonik(r["url"]) for r in con.execute("SELECT url FROM sayfa")}
        gecerli = set()
        for dosya in sorted(kaynak_diz.glob("*.json")):
            try:
                d = json.loads(dosya.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(d, dict):
                u = d.get("istenen_url") or d.get("url")
                if isinstance(u, str) and url_kanonik(u) in kasa_urlleri:
                    gecerli.add(url_kanonik(u))
        notlar = eski / "notlar"
        yeni, konu = [], 0
        for item in plan:
            if not isinstance(item, dict):
                yeni.append(item)
                continue
            slug = item.get("slug")
            eslesen = []
            note = notlar / f"{slug}.md" if slug else None
            if note is not None and note.is_file():
                for u in _not_urls(note.read_text(encoding="utf-8", errors="ignore")):
                    c = url_kanonik(u)
                    if c in gecerli:
                        r = con.execute("SELECT alindi FROM sayfa WHERE url=?", (c,)).fetchone()
                        if r is not None:
                            eslesen.append((c, r["alindi"] or 0.0))
            if not eslesen:
                yeni.append(item)
                continue
            n = len(eslesen)
            en_yeni = _iso(max(a for _, a in eslesen))
            hostlar = []
            for u, _ in eslesen:
                h = _host(u)
                if h and h not in hostlar:
                    hostlar.append(h)
            cumle = (f"GÜNCELLEME KİPİ: bu konuda daha önce {n} kaynak okundu (en yeni {en_yeni}); yeni gelişmelere ve "
                     f"{eski_gun} günden eski kaynakların değişip değişmediğine odaklan, aynı kaynakları baştan tarama. "
                     f"Önceki kaynaklar: {', '.join(hostlar[:8])}")
            kopya = dict(item)
            kopya["kisitlar"] = (item.get("kisitlar") + " " + cumle) if item.get("kisitlar") else cumle
            yeni.append(kopya)
            konu += 1
    finally:
        con.close()
    cikti_p = Path(cikti) if cikti else plan_p.with_name("PLAN.guncelleme.json")
    cikti_p.write_text(json.dumps(yeni, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"plan": yeni, "konu": konu, "cikti": str(cikti_p)}


def _cmd_ekle(args):
    for d in args.dizinler:
        if not Path(d).is_dir():
            print(f"kasa: dizin yok: {d}", file=sys.stderr)
            return 2
    try:
        s = ekle(args.db, args.dizinler)
    except (KasaHatasi, sqlite3.DatabaseError) as e:
        print(f"kasa: {e}", file=sys.stderr)
        return 1
    if s["gecerli"] == 0:
        print("kasa: dizinlerde ok=true ve dolu markdown içeren sayfa yok", file=sys.stderr)
        return 1
    print(f"kasa: {s['eklendi']} eklendi, {s['yenilendi']} güncellendi, {s['atlandi']} atlandı; "
          f"{s['sayfa']} sayfa, {s['kopya_grubu']} kopya grubu")
    return 0


def _cmd_ara(args):
    try:
        sonuc = ara(args.db, args.sorgu, en_cok=args.en_cok, eski_gun=args.eski_gun)
    except KasaHatasi as e:
        print(f"kasa: {e}", file=sys.stderr)
        return 2 if str(e) == "boş sorgu" else 1
    except sqlite3.DatabaseError as e:
        print(f"kasa: veritabanı hatası: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(sonuc, ensure_ascii=False, indent=2))
        return 0
    if not sonuc:
        print("kasa: sonuç yok")
        return 0
    for r in sonuc:
        ek = f" (+{r['kopya_sayisi'] - 1} kopya)" if r["kopya_sayisi"] > 1 else ""
        bayrak = " ⟳ yeniden doğrula" if r["eski"] else ""
        print(f"- {r['url']}  [{r['host']} · {r['tarih']} · {r['yas_gun']} gün]{ek}{bayrak}")
        print(f"  {r['pasaj']}")
    return 0


def _cmd_kopyalar(args):
    try:
        gruplar = kopya_gruplari(args.db)
    except (KasaHatasi, sqlite3.DatabaseError) as e:
        print(f"kasa: {e}", file=sys.stderr)
        return 1
    coklular = {g: u for g, u in gruplar.items() if len(u) > 1}
    if not coklular:
        print("kasa: kopya grubu yok")
        return 0
    for g, urller in sorted(coklular.items(), key=lambda x: -len(x[1])):
        print(f"{g} ({len(urller)} sayfa):")
        for u in urller:
            print(f"  - {u}")
    return 0


def _cmd_istatistik(args):
    try:
        s = istatistik(args.db)
    except (KasaHatasi, sqlite3.DatabaseError) as e:
        print(f"kasa: {e}", file=sys.stderr)
        return 1
    print(f"kasa: {s['sayfa']} sayfa, {s['pasaj']} pasaj, {s['kopya_grubu']} kopya grubu, {s['host']} host; "
          f"en eski {s['en_eski'] or '—'}, en yeni {s['en_yeni'] or '—'}")
    return 0


def _cmd_guncelle_plan(args):
    try:
        r = guncelle_plan(args.db, args.plan, args.dizin, cikti=args.cikti, eski_gun=args.eski_gun)
    except KasaHatasi as e:
        print(f"kasa: {e}", file=sys.stderr)
        return 2
    except sqlite3.DatabaseError as e:
        print(f"kasa: veritabanı hatası: {e}", file=sys.stderr)
        return 1
    print(f"kasa: {r['konu']} konu güncellendi → {r['cikti']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="kasa veritabanı yolu (yoksa QUOTEPROOF_KASA, yoksa ~/.local/share/quoteproof/kasa.db)")
    alt = ap.add_subparsers(dest="komut", required=True)

    e = alt.add_parser("ekle", help="önbellek dizinlerini kasaya ekle/güncelle")
    e.add_argument("dizinler", nargs="+")
    e.set_defaults(func=_cmd_ekle)

    a = alt.add_parser("ara", help="BM25 sıralı tam metin araması")
    a.add_argument("sorgu")
    a.add_argument("--en-cok", type=int, default=10)
    a.add_argument("--eski-gun", type=int, default=VARSAYILAN_ESKI_GUN)
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=_cmd_ara)

    k = alt.add_parser("kopyalar", help="kopya gruplarını yazdır")
    k.set_defaults(func=_cmd_kopyalar)

    i = alt.add_parser("istatistik", help="kasa özeti")
    i.set_defaults(func=_cmd_istatistik)

    g = alt.add_parser("guncelle-plan", help="plan konularına güncelleme kipi cümlesi ekle")
    g.add_argument("plan")
    g.add_argument("dizin", help="eski çalıştırma dizini (kaynaklar/ ve notlar/ içerir)")
    g.add_argument("--cikti", help="çıktı dosyası (varsayılan: PLAN.guncelleme.json, planın yanında)")
    g.add_argument("--eski-gun", type=int, default=VARSAYILAN_ESKI_GUN)
    g.set_defaults(func=_cmd_guncelle_plan)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())