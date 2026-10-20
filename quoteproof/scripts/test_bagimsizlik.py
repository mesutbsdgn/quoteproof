#!/usr/bin/env python3
"""bagimsizlik.py çevrimdışı testleri (ağ yok, yalnız geçici dizin): python3 -m unittest test_bagimsizlik"""
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arastir  # noqa: E402
import bagimsizlik  # noqa: E402
import destek  # noqa: E402

UZUN = ("Yapay zeka modelleri bellek bant genişliği ile sınırlıdır ve ölçüm sonuçları "
        "donanım yapılandırmasına göre değişir. Decode hızı token başına saniye ile ifade edilir. " * 6)
FARKLI = ("Muhasebe kayıtları vergi mevzuatına uygun tutulur ve beyanname dönemleri yıllıktır. "
          "Bilanço kalemleri denetimden geçer ve raporlanır. " * 6)


def onbellek_yaz(dizin, url, metin, fetched_at=1000.0):
    """oku.py önbellek dosyası taklidi yazar (ad sha1; içerik kasa.sayfalari_yukle biçiminde)."""
    Path(dizin).mkdir(parents=True, exist_ok=True)
    ad = hashlib.sha1(url.encode()).hexdigest()[:24]
    Path(dizin, f"{ad}.json").write_text(
        json.dumps({"istenen_url": url, "ok": True, "markdown": metin, "fetched_at": fetched_at,
                    "baslik": url}, ensure_ascii=False), encoding="utf-8")


def not_yaz(dizin, ad, urls):
    """Her URL için bir bulgu maddesi olan tek soruluk not yazar."""
    maddeler = "".join(f'- Bulgu {i} — "alıntı" — [K{i}]({u}) (2025-10, birincil)\n' for i, u in enumerate(urls, 1))
    text = (f"# Konu {ad}\n\n## Soru 1\n### Özet\nÖzet cümlesi burada yazıyor ve yeterince uzun.\n"
            f"### Alıntılı bulgular\n{maddeler}### Çıkarımlar\n- (yok)\n### Boşluklar\n- (belirtilmedi)\n")
    p = Path(dizin) / f"{ad}.md"
    p.write_text(text, encoding="utf-8")
    return p


class BagimsizlikTemel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name) / "notlar"
        self.d.mkdir()
        self.onbellek = Path(self.tmp.name) / "kaynaklar"
        self.onbellek.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_ayni_metin_iki_host_bagimsiz_kucuk(self):
        onbellek_yaz(self.onbellek, "https://bir.example/a", UZUN)
        onbellek_yaz(self.onbellek, "https://iki.example/a", UZUN)   # aynı yazı, farklı alan adı
        not_yaz(self.d, "konu", ["https://bir.example/a", "https://iki.example/a"])
        r = bagimsizlik.run(self.d, str(self.onbellek))["konu"]
        self.assertEqual(r["url_sayisi"], 2)
        self.assertEqual(r["alan_adi_sayisi"], 2)
        self.assertEqual(r["bagimsiz_kaynak_sayisi"], 1, "kopya grubu tek kaynak sayılmalı")
        self.assertLess(r["bagimsiz_kaynak_sayisi"], r["alan_adi_sayisi"])
        self.assertEqual(len(r["kopya_gruplari"]), 1)
        self.assertEqual(r["kopya_gruplari"][0]["alan_adlari"], ["bir.example", "iki.example"])

    def test_farkli_metin_bagimsiz_esit(self):
        onbellek_yaz(self.onbellek, "https://bir.example/a", UZUN)
        onbellek_yaz(self.onbellek, "https://iki.example/a", FARKLI)
        not_yaz(self.d, "konu", ["https://bir.example/a", "https://iki.example/a"])
        r = bagimsizlik.run(self.d, str(self.onbellek))["konu"]
        self.assertEqual(r["alan_adi_sayisi"], 2)
        self.assertEqual(r["bagimsiz_kaynak_sayisi"], 2)
        self.assertEqual(r["kopya_gruplari"], [])

    def test_okunamayan_sayfa_sayimi_bozmaz(self):
        onbellek_yaz(self.onbellek, "https://bir.example/a", UZUN)
        onbellek_yaz(self.onbellek, "https://iki.example/a", UZUN)
        # üçüncü URL önbellekte YOK (okunamadı): bağımsız kaynağı artırmamalı
        not_yaz(self.d, "konu", ["https://bir.example/a", "https://iki.example/a", "https://uc.example/b"])
        r = bagimsizlik.run(self.d, str(self.onbellek))["konu"]
        self.assertEqual(r["url_sayisi"], 3)
        self.assertEqual(r["okunabilir_sayisi"], 2)
        self.assertEqual(r["bagimsiz_kaynak_sayisi"], 1, "okunamayan sayfa bağımsız kaynak saymaz")
        self.assertEqual(r["kopya_gruplari"][0]["alan_adlari"], ["bir.example", "iki.example"])

    def test_kanonik_url_ayni_sayfa_tek_kaynak(self):
        onbellek_yaz(self.onbellek, "https://www.example.com/x?a=1", UZUN)
        onbellek_yaz(self.onbellek, "http://example.com/x?a=1", UZUN)
        not_yaz(self.d, "konu", ["https://www.example.com/x?a=1", "http://example.com/x?a=1"])
        r = bagimsizlik.run(self.d, str(self.onbellek))["konu"]
        self.assertEqual(r["url_sayisi"], 1, "kanonik: aynı sayfanın iki URL biçimi tek")
        self.assertEqual(r["alan_adi_sayisi"], 1)

    def test_files_secimi_ve_dislanan_atlanir(self):
        onbellek_yaz(self.onbellek, "https://bir.example/a", UZUN)
        not_yaz(self.d, "konu", ["https://bir.example/a"])
        not_yaz(self.d, "obur", ["https://bir.example/a"])
        (self.d / "DISLANAN.md").write_text("# d\n", encoding="utf-8")
        r = bagimsizlik.run(self.d, str(self.onbellek), files=["konu.md"])
        self.assertEqual(list(r), ["konu"])

    def test_render_bolumleri(self):
        onbellek_yaz(self.onbellek, "https://bir.example/a", UZUN)
        onbellek_yaz(self.onbellek, "https://iki.example/a", UZUN)
        not_yaz(self.d, "konu", ["https://bir.example/a", "https://iki.example/a"])
        res = bagimsizlik.run(self.d, str(self.onbellek))
        md = bagimsizlik.render(res)
        self.assertIn("# Kaynak bağımsızlığı", md)
        self.assertIn("| Not | URL | Okunabilir | Alan adı | Okunabilir alan adı | Bağımsız kaynak | Kopya grubu |", md)
        self.assertIn("## konu.md — kopya grupları", md)
        self.assertIn("## Sınırlama", md)
        self.assertIn("Ortak sahiplik", md)
        s = bagimsizlik.summarize(res)
        self.assertEqual((s["alan_adi"], s["bagimsiz"], s["kopya_grubu"]), (2, 1, 1))

    def test_cli_json_ve_md(self):
        onbellek_yaz(self.onbellek, "https://bir.example/a", UZUN)
        onbellek_yaz(self.onbellek, "https://iki.example/a", UZUN)
        not_yaz(self.d, "konu", ["https://bir.example/a", "https://iki.example/a"])
        out = Path(self.tmp.name) / "bagimsizlik.md"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bagimsizlik.main([str(self.d), "--onbellek", str(self.onbellek), "--cikti", str(out)]), 0)
        self.assertTrue(out.is_file())
        self.assertIn("# Kaynak bağımsızlığı", out.read_text(encoding="utf-8"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(bagimsizlik.main([str(self.d), "--onbellek", str(self.onbellek), "--json"]), 0)
        self.assertIn("bagimsiz_kaynak_sayisi", buf.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bagimsizlik.main(["/yok/dizin"]), 2)


class ArastirHatti(unittest.TestCase):
    """arastir.py, dogrula'dan sonra bagimsizlik.py'yi çalıştırır, bagimsizlik.md yazar, kopya grubunu uyarır, çıkış kodunu DEĞİŞTİRMEZ."""
    NOTE = ("# Konu\n\n## Soru 1\n### Özet\nEk yük yaklaşık %8 ölçüldü.\n### Alıntılı bulgular\n"
            '- A — "x" — [A](https://bir.example/a) (2025-10, birincil)\n'
            '- B — "x" — [B](https://iki.example/a) (2025-10, birincil)\n'
            '- C — "y" — [C](https://uc.example/b) (2025-10, birincil)\n'
            "### Çıkarımlar\n- (yok)\n### Boşluklar\n- (belirtilmedi)\n")

    def _main(self, d, extra=()):
        Path(d, "PLAN.json").write_text(json.dumps(
            [{"slug": "konu", "konu": "k", "sorular": ["s?"], "min_url": arastir.MIN_URLS}]), encoding="utf-8")

        def fake(item, base, args, delay=0.0, sequence=None):
            (base / "notlar" / f"{item['slug']}.md").write_text(self.NOTE)
            return {"slug": item["slug"], "ok": True, "deneme": 1, "arka": "cli", "rc": 0, "hata": "", "bayt": len(self.NOTE),
                    "sure_sn": 1, "denemeler": [], "jeton": [1, 1], "araclar": {}}

        onbellek = Path(d) / "kaynaklar"
        onbellek_yaz(onbellek, "https://bir.example/a", UZUN)
        onbellek_yaz(onbellek, "https://iki.example/a", UZUN)
        onbellek_yaz(onbellek, "https://uc.example/b", FARKLI)
        argv = ["arastir.py", str(Path(d) / "PLAN.json"), "-d", d, "--arka", "cli", *extra]
        page = {"ok": True, "markdown": "Lorem ipsum dolor sit amet. " * 30, "hata": ""}
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(arastir, "available_backends", return_value={"cli"}), \
             mock.patch.object(arastir, "run_worker", side_effect=fake), mock.patch.object(destek.oku, "load", return_value=page), \
             mock.patch.object(arastir.subprocess, "run", return_value=mock.Mock(returncode=0)), contextlib.redirect_stdout(out):
            rc = arastir.main()
        return rc, out.getvalue()

    def test_bagimsizlik_md_yazilir_ve_kopya_grubu_uyarilir(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = self._main(d)
            self.assertEqual(rc, 0)
            self.assertIn("kaynak bağımsızlığı", out)
            self.assertIn("⚠", out)
            md = (Path(d) / "bagimsizlik.md").read_text(encoding="utf-8")
            self.assertIn("# Kaynak bağımsızlığı", md)
            self.assertIn("iki.example", md)

    def test_dogrula_yok_ile_bagimsizlik_calismaz(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = self._main(d, ["--dogrula-yok"])
            self.assertNotIn("kaynak bağımsızlığı", out)
            self.assertFalse((Path(d) / "bagimsizlik.md").exists())


if __name__ == "__main__":
    unittest.main()