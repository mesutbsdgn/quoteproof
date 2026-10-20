#!/usr/bin/env python3
"""guven.py çevrimdışı birim testleri (ağ yok): python3 -m unittest test_guven"""
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # skill dizininde __pycache__/.pyc üretme (taranamayan ikili dosya)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guven  # noqa: E402


class TeknikBasinDonanim(unittest.TestCase):
    """8 Eki 2026: phoronix.com, hardware-corner.net gibi donanım yayınları 'belirsiz 50' alıp SEO yoluyla 42'ye düşüyordu."""

    YENI = ["phoronix.com", "anandtech.com", "tomshardware.com", "servethehome.com", "notebookcheck.net",
            "techpowerup.com", "hardware-corner.net", "semianalysis.com", "chipsandcheese.com"]

    def test_yeni_donanim_yayinlari_teknik_basin_62(self):
        for host in self.YENI:
            r = guven.score(f"https://{host}/x")
            self.assertEqual(r["sinif"], "teknik basın", host)
            self.assertEqual(r["puan"], 62, host)

    def test_phoronix_haber_yolu_en_az_55(self):
        for url in ("https://phoronix.com/news/x", "https://www.phoronix.com/scan.php?page=news_item"):
            self.assertGreaterEqual(guven.score(url)["puan"], 55, url)

    def test_hardware_corner_artik_belirsiz_degil(self):
        r = guven.score("https://hardware-corner.net/best-nas-2026")
        self.assertEqual(r["sinif"], "teknik basın")
        self.assertEqual(r["puan"], 54)   # 62 − 8 (SEO kalıbı); eskiden 42 idi
        self.assertNotEqual(r["sinif"], "belirsiz")


class VsKarsilastirmaCezasi(unittest.TestCase):
    def test_vs_tek_basina_uc_ceza(self):
        base = guven.score("https://some-blog.example/post")["puan"]
        r = guven.score("https://some-blog.example/mlx-vs-llama-cpp-on-apple-silicon")
        self.assertEqual(r["puan"], base - 3)
        self.assertIn("teknik karşılaştırma", " ".join(r["gerekce"]))

    def test_vs_donanım_yayininda_uc_ceza(self):
        self.assertEqual(guven.score("https://phoronix.com/mlx-vs-llama-cpp")["puan"], 62 - 3)

    def test_derleme_terimleri_hala_sekiz_ceza(self):
        base = guven.score("https://some-blog.example/post")["puan"]
        for yol in ("best-gpus-2026", "top-10-laptops", "review-nvidia", "coupon-deals", "cheap-ssd", "alternatives-to-x"):
            self.assertEqual(guven.score(f"https://some-blog.example/{yol}")["puan"], base - 8, yol)

    def test_vs_ile_derleme_terimi_birlikte_sekiz_ceza(self):
        base = guven.score("https://some-blog.example/post")["puan"]
        self.assertEqual(guven.score("https://some-blog.example/best-vs")["puan"], base - 8)
        self.assertEqual(guven.score("https://some-blog.example/deals-vs")["puan"], base - 8)

    def test_vs_ile_baslayan_kelime_ceza_almaz(self):
        base = guven.score("https://some-blog.example/post")["puan"]
        self.assertEqual(guven.score("https://some-blog.example/vscode")["puan"], base)
        self.assertEqual(guven.score("https://some-blog.example/posts/vs")["puan"], base - 3)


class MevcutDavranisKorunur(unittest.TestCase):
    def test_bilinmeyen_alan_adi_hala_50(self):
        self.assertEqual(guven.score("https://some-blog.example/post")["puan"], 50)
        self.assertEqual(guven.classify("evil-gov.example"), ("belirsiz", 50))

    def test_mevcut_sinif_puanlari_degismedi(self):
        expect = {"https://arstechnica.com/x": ("teknik basın", 65),
                  "https://www.theregister.com/x": ("teknik basın", 65),
                  "https://lwn.net/x": ("teknik basın", 65),
                  "https://theverge.com/x": ("teknik basın", 65),
                  "https://github.com/o/r": ("kod deposu", 65),
                  "https://medium.com/x": ("topluluk", 40),
                  "https://en.wikipedia.org/x": ("ansiklopedi", 60),
                  "https://owasp.org/x": ("güvenlik standardı/rehberi", 88),
                  "https://nist.gov/x": ("resmî/standart", 90)}
        for url, (cls, pts) in expect.items():
            r = guven.score(url)
            self.assertEqual((r["sinif"], r["puan"]), (cls, pts), url)

    def test_en_uzun_sonek_kurali_bozulmadi(self):
        self.assertEqual(guven.score("https://gist.github.com/x")["puan"], 45)   # github.com (65) değil
        self.assertEqual(guven.score("https://cheatsheetseries.owasp.org/x")["puan"], 88)

    def test_cok_kiracili_alt_alan_kurali_bozulmadi(self):
        hints = guven.hints_from_text("medium.com")
        self.assertNotIn("planda beklenen", " ".join(guven.score("https://evil.medium.com/x", hints)["gerekce"]))
        self.assertIn("planda beklenen", " ".join(guven.score("https://medium.com/x", hints)["gerekce"]))
        self.assertEqual(guven.score("https://docs.evil.com/a")["sinif"], "doküman benzeri alt alan (doğrulanmadı)")

    def test_taklit_alan_adlari_hala_belirsiz(self):
        for url in ("https://phoronix.com.evil.example/x", "https://notanandtech.com/x",
                    "https://tomshardware.com.evil.io/x", "https://lwn.net.cn.example/x"):
            self.assertEqual(guven.score(url)["sinif"], "belirsiz", url)


class CokKiraciliAlanAdlari(unittest.TestCase):
    """O6 (20 Eki 2026): github.io/gitlab.io/readthedocs.io herkesin sitesi; .edu/~ kişisel sayfa. Hepsi eskiden yüksek puan alıyordu."""

    def test_github_io_ve_gitlab_io_topluluk_50(self):
        for host in ("x.github.io", "x.gitlab.io", "gist.github.io"):
            r = guven.score(f"https://{host}/yazı")
            self.assertEqual(r["sinif"], "topluluk", host)
            self.assertEqual(r["puan"], 50, host)

    def test_readthedocs_io_dokuman_benzeri_55(self):
        r = guven.score("https://proje.readthedocs.io/en/latest/")
        self.assertEqual(r["sinif"], "doküman benzeri alt alan (doğrulanmadı)")
        self.assertEqual(r["puan"], 55)

    def test_edu_taban_90_kisisel_sayfa_60(self):
        self.assertEqual(guven.score("https://cs.example.edu/x")["puan"], 90)
        self.assertEqual(guven.score("https://cs.example.edu/~user/x")["puan"], 60)

    def test_github_com_hala_kod_deposu_65(self):
        self.assertEqual(guven.score("https://github.com/o/r")["puan"], 65)
        self.assertEqual(guven.score("https://gitlab.com/o/r")["puan"], 65)

    def test_cok_kiracili_plan_ipucu_kok_alan_ile_arti_10(self):
        hints = guven.hints_from_text("proje.readthedocs.io")
        r = guven.score("https://proje.readthedocs.io/en/latest/", hints)
        self.assertEqual(r["puan"], 55 + 10)
        self.assertIn("planda beklenen", " ".join(r["gerekce"]))

    def test_plan_ipucu_alt_alana_yayilmaz(self):
        hints = guven.hints_from_text("proje.readthedocs.io")
        self.assertNotIn("planda beklenen", " ".join(guven.score("https://evil.readthedocs.io/x", hints)["gerekce"]))


if __name__ == "__main__":
    unittest.main()