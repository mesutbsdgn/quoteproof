#!/usr/bin/env python3
"""kapsama.py ve uzlas.py çevrimdışı birim testleri (ağ yok): python3 -m unittest test_kapsama_uzlas

K4: olgu eşleşmesi yalnız iddia metni + alıntı üzerinde yapılır (URL/bağlantı adresi/künye sayılmaz).
O3: aynı sayfadan farklı sayı taşıyan bulgular aynı iddia sayılmaz; çelişki birleşik notta işaretlenir.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import denetle  # noqa: E402
import kapsama  # noqa: E402
import uzlas  # noqa: E402


class _NotTemel(unittest.TestCase):
    """Test notu + dogrulama.json yazan ortak yardımcılar."""

    def _not(self, bulgular):
        """bulgular = [(iddia, alıntı, url)]"""
        s = "# konu\n## S\n### Özet\nözet\n### Alıntılı bulgular\n"
        s += "".join(f'- {c} — "{q}" — [K]({u}) (2026-10, birincil)\n' for c, q, u in bulgular)
        return s + "### Çıkarımlar\n- yorum\n### Boşluklar\n- yok\n"

    def _dirs(self, d, notes, verdict="Doğrulandı"):
        out = []
        for name, text in notes:
            p = Path(d) / name / "notlar-temiz"
            p.mkdir(parents=True)
            note = p / "konu.md"
            note.write_text(text, encoding="utf-8")
            rows = [{"not": note.name, "iddia": f["metin"], "karar": verdict}
                    for f in denetle.analyze(note)["findings"]]
            (p.parent / "dogrulama.json").write_text(json.dumps({"satirlar": rows}, ensure_ascii=False), encoding="utf-8")
            out.append(str(p))
        return out


class OlguMetniDaraltma(unittest.TestCase):
    """K4: bulgu satırının TAMAMINDA arama, "/rtx-5090-review/" URL'sini "CUDA|RTX" olgusuna eşletiriyordu."""

    def test_olgu_metni_baglanti_adresi_url_kunye_disar_metin_icerde(self):
        line = '- [RTX incelemesi](https://k.example/rtx-5090-review/) bitti (2026-10, birincil)'
        m = kapsama.olgu_metni(line)
        self.assertNotIn("rtx-5090-review", m)      # bağlantı adresi/URL çıkarıldı
        self.assertNotIn("https://", m)
        self.assertNotIn("birincil", m)             # künye parantezi çıkarıldı
        self.assertIn("RTX incelemesi", m)          # bağlantı METNİ kaldı


class OlguKapsamaUrlSaymaz(_NotTemel):
    """K4 uçtan uca: kapsama yalnız iddia metni + alıntıya bakmalı."""

    ITEM = {"slug": "konu", "konu": "k", "sorular": ["s?"], "kaynaklar": "x", "kisitlar": "y",
            "olgular": [{"ad": "CUDA/RTX olgusu", "ara": "CUDA|RTX"}]}

    def test_yalniz_url_de_gecen_terim_kapsamaz(self):
        text = self._not([("GPU hızı", "the card runs fast in benchmarks", "https://k.example/rtx-5090-review/")])
        with tempfile.TemporaryDirectory() as d:
            res = kapsama.run([self.ITEM], self._dirs(d, [("r1", text)]))
        self.assertEqual((res["konu"]["kapsanan"], res["konu"]["toplam"]), (0, 1))

    def test_alintida_gecen_terim_kapsar(self):
        text = self._not([("GPU hızı", "the RTX 5090 runs fast in benchmarks", "https://k.example/other/")])
        with tempfile.TemporaryDirectory() as d:
            res = kapsama.run([self.ITEM], self._dirs(d, [("r1", text)]))
        self.assertEqual((res["konu"]["kapsanan"], res["konu"]["toplam"]), (1, 1))

    def test_iddia_metninde_gecen_iliskisel_olgu_kapsar(self):
        item = {"slug": "konu", "konu": "k", "sorular": ["s?"], "kaynaklar": "x", "kisitlar": "y",
                "olgular": [{"ad": "M5, M4'ten ≥4x", "ara": r"M5.{0,40}4x|4x.{0,40}M4"}]}
        text = self._not([("M5 hızı", "the chip is much quicker in practice", "https://k.example/bench/")])
        # iddia metninde "M5 ... 4x M4" ilişkisi var (alıntıda değil):
        text = text.replace("- M5 hızı —", "- M5, M4'e göre 4x hızlı —")
        with tempfile.TemporaryDirectory() as d:
            res = kapsama.run([item], self._dirs(d, [("r1", text)]))
        self.assertEqual((res["konu"]["kapsanan"], res["konu"]["toplam"]), (1, 1))

    def test_yorumlanmayan_karar_kapsama_disarida_kalir(self):
        text = self._not([("GPU hızı", "the RTX 5090 runs fast in benchmarks", "https://k.example/other/")])
        with tempfile.TemporaryDirectory() as d:
            res = kapsama.run([self.ITEM], self._dirs(d, [("r1", text)], verdict="Kısmen"))
        self.assertEqual((res["konu"]["kapsanan"], res["konu"]["toplam"]), (0, 1))


class AyniIddiaSayiKurali(unittest.TestCase):
    """O3: "RTX 5090 … 290" ile "RTX 4090 … 150" yalnız %35 örtüşmeyle birleşip çelişkiyi siliyordu."""

    def _f(self, quote, nums=(), urls=("https://k.example/rtx",)):
        return {"q": set(quote.split()), "nums": set(nums), "urls": set(urls), "alinti": True, "metin": quote}

    def test_ayni_sayfa_farkli_sayilar_ayni_iddia_sayilmaz(self):
        a = self._f("RTX 5090 runs at 290 tokens per second", ["290"])
        b = self._f("RTX 4090 runs at 150 tokens per second", ["150"])
        small = min(len(a["q"]), len(b["q"]))
        self.assertGreaterEqual(len(a["q"] & b["q"]) / small, uzlas.OVERLAP_SAME)   # sözcük örtüşmesi yüksek…
        self.assertFalse(uzlas.same_claim(a, b))                                     # …ama sayı kuralı birleştirmez

    def test_ortak_sayi_varsa_ayni_iddia(self):
        a = self._f("RTX 5090 runs at 290 tokens per second", ["290", "5090"])
        b = self._f("RTX 5090 runs at 290 tokens per second in our test", ["290", "5090"])
        self.assertTrue(uzlas.same_claim(a, b))

    def test_iki_taraf_sayisizsa_ortusme_karar_verir(self):
        a = self._f("best effort maintenance until March", [])
        b = self._f("best effort maintenance until March", [])
        self.assertTrue(uzlas.same_claim(a, b))

    def test_yuvarlanmis_sayilar_ayri_kume_kabul_edilir(self):
        # 290 ↔ ~300: ortak sayı yok → ayrı küme; davranış kabul edilir (koordinatör notta görür).
        a = self._f("cached tokens about 290 per sequence", ["290"])
        b = self._f("cached tokens about 300 per sequence", ["300"])
        self.assertFalse(uzlas.same_claim(a, b))


class CeliskiKumesi(unittest.TestCase):
    """O3: aynı sayfadan farklı sayı taşıyan ayrı kümeler birleşik notta "Çelişen/ayrı sayılar" başlığıyla işaretlenir."""

    def _f(self, quote, nums, urls=("https://k.example/rtx",)):
        return {"q": set(quote.split()), "nums": set(nums), "urls": set(urls), "alinti": True, "metin": quote}

    def test_conflicts_ayni_sayfa_farkli_sayi_bulur(self):
        a = {"r1": [self._f("RTX 5090 measured faster overall", ["5090", "4x"])]}
        b = {"r1": [self._f("RTX 4090 measured faster overall", ["4090", "2x"])]}
        c = {"r2": [self._f("unrelated page claim about something", ["7"], urls=("https://k.example/baska",))]}
        self.assertEqual(len(uzlas.conflicts([a, b, c])), 1)

    def test_conflicts_ortak_sayi_varsa_isaretlemez(self):
        a = {"r1": [self._f("RTX 5090 measured faster", ["5090", "4x"])]}
        b = {"r2": [self._f("RTX 5090 measured faster", ["5090", "3x"])]}
        self.assertEqual(uzlas.conflicts([a, b]), [])


class AyniSayfaFarkliSayiBirlestirme(_NotTemel):
    """Uçtan uca: aynı URL'yi paylaşan farklı sayılı iki bulgu ayrı küme kalır ve birleşik notta işaretlenir."""

    def test_farkli_sayilar_ayri_kume_ve_notta_celiski_bolumu(self):
        text = self._not([
            ("RTX 5090 kartı 4x daha hızlı ölçüldü", "RTX 5090 measured 4x faster than its predecessor in the test", "https://k.example/rtx"),
            ("RTX 4090 kartı 2x daha hızlı ölçüldü", "RTX 4090 measured 2x faster than its predecessor in the test", "https://k.example/rtx"),
        ])
        with tempfile.TemporaryDirectory() as d:
            dirs = self._dirs(d, [("r1", text)])
            res = uzlas.run(dirs)
            r = res["konu"]
            self.assertEqual(len(r["clusters"]), 2)   # birleşmedi
            self.assertEqual(len(uzlas.conflicts(r["clusters"])), 1)
            merged = uzlas.merge_note("konu", r["runs"], r["clusters"], r["gaps"])
        self.assertIn("### Çelişen/ayrı sayılar", merged)


if __name__ == "__main__":
    unittest.main()