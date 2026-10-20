#!/usr/bin/env python3
"""kasa.py çevrimdışı birim testleri (ağ yok, yalnız geçici dizin): python3 -m unittest test_kasa"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # skill dizininde __pycache__/.pyc üretme

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kasa  # noqa: E402

UZUN = ("Yapay zeka modelleri bellek bant genişliği ile sınırlıdır ve ölçüm sonuçları "
        "donanım yapılandırmasına göre değişir. Decode hızı token başına saniye ile ifade edilir. " * 4)
FARKLI = ("Muhasebe kayıtları vergi mevzuatına uygun tutulur ve beyanname dönemleri yıllıktır. "
          "Bilanço kalemleri denetimden geçer. " * 4)


def yaz(dizin, ad, url, metin, fetched_at, ok=True):
    """oku.py önbellek dosyası taklidi yazar (24hex ad)."""
    p = Path(dizin) / f"{ad}.json"
    p.write_text(json.dumps({"istenen_url": url, "ok": ok, "markdown": metin,
                             "fetched_at": fetched_at, "baslik": ad}, ensure_ascii=False), encoding="utf-8")
    return p


class KasaTemel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kaynak = Path(self.tmp.name) / "kaynaklar"
        self.kaynak.mkdir()
        self.db = str(Path(self.tmp.name) / "kasa.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _ekle(self, *adlar):
        for ad in adlar:
            yaz(self.kaynak, ad[0], ad[1], ad[2], ad[3], ad[4] if len(ad) > 4 else True)
        return kasa.ekle(self.db, [str(self.kaynak)])

    def test_01_ekle_idempotent(self):
        s1 = self._ekle(("a" * 24, "https://x.example/a", "alfa beta gama delta epsilon zeta eta teta iota", 1000.0))
        self.assertEqual((s1["eklendi"], s1["yenilendi"], s1["atlandi"]), (1, 0, 0))
        s2 = self._ekle(("a" * 24, "https://x.example/a", "alfa beta gama delta epsilon zeta eta teta iota", 1000.0))
        self.assertEqual((s2["eklendi"], s2["yenilendi"], s2["atlandi"]), (0, 0, 1))
        self.assertEqual(kasa.istatistik(self.db)["pasaj"], kasa.istatistik(self.db)["pasaj"])
        self.assertEqual(kasa.istatistik(self.db)["sayfa"], 1)

    def test_02_yeniyse_guncellenir_eskisi_degismez(self):
        self._ekle(("b" * 24, "https://x.example/b", "elma armut kiraz üzüm erik şeftali kayısı vişne", 1000.0))
        s = self._ekle(("b" * 24, "https://x.example/b", "kavun karpuz çilek ahududu yaban mersin dut incir", 2000.0))
        self.assertEqual(s["yenilendi"], 1)
        self.assertTrue(kasa.ara(self.db, "karpuz"), "yeni içerik aranabilmeli")
        self.assertFalse(kasa.ara(self.db, "armut"), "eski içerik silinmeli")
        s2 = self._ekle(("b" * 24, "https://x.example/b", "nar mandalina portakal limon greyfurt turunç bergamot", 1500.0))
        self.assertEqual(s2["atlandi"], 1)
        self.assertTrue(kasa.ara(self.db, "karpuz"), "eski fetched_at güncellememeli")

    def test_03_kopya_grubu_ve_bagimsiz_alan_adi(self):
        self._ekle(("c" * 24, "https://bir.example/a", UZUN, 1000.0),
                   ("d" * 24, "https://iki.example/a", UZUN, 1000.0),
                   ("e" * 24, "https://uc.example/b", FARKLI, 1000.0))
        gruplar = kasa.kopya_gruplari(self.db)
        bir = next(g for g, u in gruplar.items() if "https://bir.example/a" in u)
        self.assertEqual(set(gruplar[bir]), {"https://bir.example/a", "https://iki.example/a"})
        uc = next(g for g, u in gruplar.items() if "https://uc.example/b" in u)
        self.assertNotEqual(bir, uc)
        self.assertEqual(kasa.bagimsiz_alan_adi_sayisi(
            ["https://bir.example/a", "https://iki.example/a"], self.db), 1)
        self.assertEqual(kasa.bagimsiz_alan_adi_sayisi(
            ["https://bir.example/a", "https://uc.example/b"], self.db), 2)

    def test_04_ara_bm25_kopya_ozel_karakter_eski(self):
        cok = " ".join(["benchmark"] * 12) + " " + "ölçüm sonucu donanım yapılandırması bellek bandı"
        az = "benchmark bir kez geçiyor " + "gürültü" * 5
        self._ekle(("f" * 24, "https://a.example/x", cok, 1000.0),
                   ("g" * 24, "https://b.example/x", az, 1000.0),
                   ("h" * 24, "https://c.example/x", cok, 1000.0))
        r = kasa.ara(self.db, "benchmark", eski_gun=10, simdi=1000.0 + 40 * 86400)
        self.assertEqual(r[0]["url"], "https://a.example/x")
        self.assertEqual(r[0]["kopya_sayisi"], 2)   # c.example kopyası ayrı sonuç olarak gösterilmez
        self.assertTrue(r[0]["eski"], "40 gün > 10 gün bayrak")
        self.assertEqual(len([x for x in r if x["url"] in ("https://a.example/x", "https://c.example/x")]), 1)
        for sorgu in ('"', "*", "-", "AND", '" AND * -', "benchmark*"):
            kasa.ara(self.db, sorgu)                # çökmemeli

    def test_05_guncelle_plan_originali_degistirmez(self):
        self._ekle(("i" * 24, "https://kaynak.example/rapor", UZUN, 1500.0))
        eski = Path(self.tmp.name) / "kosu"
        (eski / "kaynaklar").mkdir(parents=True)
        (eski / "notlar").mkdir()
        yaz(eski / "kaynaklar", "i" * 24, "https://kaynak.example/rapor", UZUN, 1500.0)
        (eski / "notlar" / "konu.md").write_text(
            "Kaynak: https://kaynak.example/rapor ve https://yok.example/z\n", encoding="utf-8")
        plan_p = Path(self.tmp.name) / "PLAN.json"
        plan_p.write_text(json.dumps([{"slug": "konu", "kisitlar": "eski kisit"}], ensure_ascii=False), encoding="utf-8")
        onceki = plan_p.read_text(encoding="utf-8")
        r = kasa.guncelle_plan(self.db, str(plan_p), str(eski), eski_gun=30)
        self.assertEqual(plan_p.read_text(encoding="utf-8"), onceki, "orijinal değişmemeli")
        self.assertEqual(r["konu"], 1)
        kisit = r["plan"][0]["kisitlar"]
        self.assertIn("eski kisit", kisit)
        self.assertIn("GÜNCELLEME KİPİ", kisit)
        self.assertIn("1 kaynak okundu", kisit)
        self.assertIn("kaynak.example", kisit)
        self.assertTrue(Path(r["cikti"]).is_file())

    def test_06_bozuk_ve_ok_false_atlanir(self):
        (self.kaynak / ("z" * 24 + ".json")).write_text("{bozuk json", encoding="utf-8")
        yaz(self.kaynak, "y" * 24, "https://okfalse.example/a", UZUN, 1000.0, ok=False)
        yaz(self.kaynak, "x" * 24, "https://bos.example/a", "   ", 1000.0)
        s = self._ekle(("w" * 24, "https://gecerli.example/a", UZUN, 1000.0))
        self.assertEqual(s["gecerli"], 1)
        self.assertEqual(s["eklendi"], 1)
        self.assertEqual(kasa.istatistik(self.db)["sayfa"], 1)

    def test_07_turkce_karakter_aranabilir(self):
        self._ekle(("t" * 24, "https://tr.example/a",
                    "güneş ışığı şirket ğ gibi bir metin ağaç ığdır işlem şğüı", 1000.0))
        for sorgu in ("güneş", "ışığı", "şirket", "ağaç"):
            self.assertTrue(kasa.ara(self.db, sorgu), f"{sorgu} bulunmalı")


class YardimciTestleri(unittest.TestCase):
    def test_url_kanonik_tablosu(self):
        ornekler = {
            "HTTPS://WWW.Example.COM/Yol/": "https://example.com/Yol",
            "http://example.com": "https://example.com/",
            "https://example.com:443/a": "https://example.com/a",
            "http://example.com:80/a": "https://example.com/a",
            "https://example.com:8443/a": "https://example.com:8443/a",
            "https://example.com/a#bolum": "https://example.com/a",
            "https://example.com/a?utm_source=x&b=2&a=1": "https://example.com/a?a=1&b=2",
            "https://example.com/a?fbclid=z&ref=twitter&aff_id=9&q=1": "https://example.com/a?q=1",
            "https://example.com/a?b=2&a=1": "https://example.com/a?a=1&b=2",
            "https://www.example.com/": "https://example.com/",
            "mailto:a@b.com": "",
            "": "",
        }
        for girdi, beklenen in ornekler.items():
            self.assertEqual(kasa.url_kanonik(girdi), beklenen, girdi)
        self.assertEqual(kasa.url_kanonik("https://EXAMPLE.com/x?A=1#frag"), kasa.url_kanonik("http://www.example.com/x?A=1"))

    def test_ayni_sayfanin_iki_url_bicimi_tek_kayit(self):
        with tempfile.TemporaryDirectory() as t:
            kaynak = Path(t) / "kaynaklar"
            kaynak.mkdir()
            db = str(Path(t) / "k.db")
            yaz(kaynak, "a" * 24, "https://www.example.com/x?utm_source=n", UZUN, 1000.0)
            yaz(kaynak, "b" * 24, "http://example.com/x", UZUN, 2000.0)
            s = kasa.ekle(db, [str(kaynak)])
            self.assertEqual(kasa.istatistik(db)["sayfa"], 1, "kanonik anahtar: tek kayıt")
            self.assertEqual(s["sayfa"], 1)
            self.assertEqual(s["eklendi"], 1)
            self.assertEqual(s["yenilendi"], 1)   # ikinci biçim daha yeni fetched_at ile güncelledi
            self.assertEqual(kasa.ara(db, "bellek")[0]["url"], "https://example.com/x")

    def test_pasajlara_bol_paragraf_ve_sert_bolme(self):
        p = kasa.pasajlara_bol("a" * 600 + "\n\n" + "b" * 600 + "\n\n" + "c" * 50)
        self.assertTrue(all(len(x) <= kasa.PASAJ_HEDEF for x in p))
        self.assertGreaterEqual(len(p), 2)

    def test_normalle_ve_shingle(self):
        self.assertEqual(kasa.normalle("Merhaba, DÜNYA! (2026) http://x.example"), "merhaba dünya 2026")
        self.assertGreaterEqual(kasa.jaccard(kasa.shingle_kumesi(UZUN), kasa.shingle_kumesi(UZUN)), kasa.JACCARD_ESIK)
        self.assertLess(kasa.jaccard(kasa.shingle_kumesi(UZUN), kasa.shingle_kumesi(FARKLI)), kasa.JACCARD_ESIK)

    def test_bos_sorgu_hata(self):
        with tempfile.TemporaryDirectory() as t:
            db = str(Path(t) / "k.db")
            kasa.ekle(db, [t])
            with self.assertRaises(kasa.KasaHatasi):
                kasa.ara(db, "   ")


if __name__ == "__main__":
    unittest.main()