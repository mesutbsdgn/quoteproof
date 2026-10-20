#!/usr/bin/env python3
"""anlam.py çevrimdışı testleri (ağ yok, model yok; alt süreç ve oku.load mock'lu): python3 -m unittest test_anlam

Kapsam: iddia temizliği, öncül penceresi ve geri dönüş, ayrıştırma + eşik/güçlü mantığı, hata kodları (2/3),
isaretle idempotentliği ve "Kısmen" ön ekiyle birlikte, ayar doğrulaması, anlam.md bölümleri ve "Sınırlama" sayıları,
--kuru model çağırmaması, arastir.py --anlam akışı. ANLAM_GERCEK testi YOKTUR (model gerektirir).
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import anlam  # noqa: E402
import arastir  # noqa: E402
import ayar  # noqa: E402
import denetle  # noqa: E402
import destek  # noqa: E402

ALINTI = "the card runs fast in benchmarks and stays cool"
KUNYE = "(2026-10, birincil)"
DOGRU_CFG = {"models": {"x": {"cli": "m"}}}


def _cfg(yol, obj):
    Path(yol).write_text(json.dumps(obj), encoding="utf-8")
    return str(yol)


class IddiaTemizligi(unittest.TestCase):
    """İddia metni: madde işareti, ön ek, tırnak alıntı, bağlantı (metin+adres), künye ve çevre noktalama atılır."""

    def test_alinti_link_kunye_onek_atilir(self):
        iddia = f'- ⚠ [Kısmen: kısmi kanıt] GPU hızı 290 t/s — "{ALINTI}" — [K](https://x.example/a) {KUNYE}'
        m = anlam.iddia_metni(iddia)
        self.assertEqual(m, "GPU hızı 290 t/s")
        for yok in (ALINTI, "https://", "x.example", "birincil", "Kısmen", "⚠", "[K]"):
            self.assertNotIn(yok, m)

    def test_kisa_ve_alintisiz_bulgu_atlanir_karar_disi_sayilir(self):
        rows = [
            {"karar": "Doğrulandı", "not": "n.md", "url": "https://x.example/a", "iddia": f'Kısa — "{ALINTI}"'},
            {"karar": "Doğrulandı", "not": "n.md", "url": "https://x.example/a", "iddia": "Bu bir iddiadır ama tırnak içi alıntı yok."},
            {"karar": "Kısmen", "not": "n.md", "url": "https://x.example/a", "iddia": f'Doğru bulgu metni burada — "{ALINTI}"'},
        ]
        ciftler, atlanan = anlam.kur(rows, None, oncul_hesapla=False)
        self.assertEqual(ciftler, [])
        self.assertEqual(atlanan, {"karar": 1, "alintisiz": 1, "kisa": 1})

    def test_dogrulanmis_tek_cift_kurulur(self):
        rows = [{"karar": "Doğrulandı", "not": "n.md", "url": "https://x.example/a",
                 "iddia": f'GPU hızı ölçüldü — "{ALINTI}" — [K](https://x.example/a) {KUNYE}'}]
        ciftler, _ = anlam.kur(rows, None, oncul_hesapla=False)
        self.assertEqual(len(ciftler), 1)
        self.assertEqual(ciftler[0]["iddia"], "GPU hızı ölçüldü")
        self.assertEqual(ciftler[0]["oncul_turu"], "alinti")


class Oncul(unittest.TestCase):
    """Öncül: bulunan İLK alıntının ±pencere çevresi; sayfa/alıntı yoksa alıntının kendisi."""

    def _rows(self, url):
        return [{"karar": "Doğrulandı", "not": "n.md", "url": url,
                 "iddia": f'GPU hızı ölçüldü ve iyi çıktı — "{ALINTI}" — [K]({url}) {KUNYE}'}]

    def test_pencere_alintidan_cevrelenir(self):
        sayfa = "Haberler burada durur ve uzun bir giriş yazar. " * 6 + ALINTI + " devamı da vardır burada. " * 6
        with mock.patch.object(anlam.oku, "load", return_value={"ok": True, "markdown": sayfa}):
            ciftler, _ = anlam.kur(self._rows("https://x.example/a"), "/tmp/onb", pencere=50)
        c = ciftler[0]
        self.assertEqual(c["oncul_turu"], "pencere")
        self.assertIn(ALINTI, c["premise"])
        self.assertGreater(len(c["premise"]), len(ALINTI))
        self.assertLessEqual(len(c["premise"]), len(ALINTI) + 2 * 50)

    def test_sayfa_okunamazsa_alinti_oncul(self):
        with mock.patch.object(anlam.oku, "load", return_value={"ok": False, "markdown": "", "hata": "ulaşılamadı"}):
            ciftler, _ = anlam.kur(self._rows("https://x.example/a"), "/tmp/onb")
        self.assertEqual(ciftler[0]["oncul_turu"], "alinti")
        self.assertEqual(ciftler[0]["premise"], ALINTI)

    def test_alinti_sayfada_bulunamazsa_alinti_oncul(self):
        with mock.patch.object(anlam.oku, "load", return_value={"ok": True, "markdown": "ilgisiz bir sayfa metni burada bulunuyor"}):
            ciftler, _ = anlam.kur(self._rows("https://x.example/a"), "/tmp/onb")
        self.assertEqual(ciftler[0]["oncul_turu"], "alinti")
        self.assertEqual(ciftler[0]["premise"], ALINTI)


def _satirlar(adet):
    return [{"karar": "Doğrulandı", "not": "n.md", "url": f"https://x.example/{i}",
             "iddia": f'Bulgu {i} iddiası burada yeterince uzun — "{ALINTI}" — [K](https://x.example/{i}) {KUNYE}'}
            for i in range(adet)]


def _cikti(skorlar):
    return "".join(json.dumps({"id": i, "entailment": e, "neutral": n, "contradiction": c}) + "\n"
                   for i, (e, n, c) in enumerate(skorlar))


class EsikVeGuclu(unittest.TestCase):
    """Ayristirma + eşik/güçlü mantığı: isaret = ent < esik; guclu = isaret ve con >= 0,5."""

    def _run(self, skorlar, esik=0.10, calistirici=None, adet=None):
        adet = adet if adet is not None else len(skorlar)
        ck = _cikti(skorlar)
        fake = calistirici or (lambda jsonl, be, timeout: (0, ck, "", False))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "dogrulama.json").write_text(json.dumps({"satirlar": _satirlar(adet)}), encoding="utf-8")
            with mock.patch.object(anlam.oku, "load", return_value={"ok": False, "markdown": ""}):
                return anlam.run(d, None, None, esik=esik,
                                 backend={"python": sys.executable, "model_dir": d, "cihaz": "cpu"}, calistirici=fake)

    def test_esik_ve_guclu(self):
        s = self._run([(0.05, 0.90, 0.05), (0.01, 0.09, 0.90), (0.80, 0.10, 0.10)])
        self.assertEqual((s["cift"], s["isaretli"], s["guclu"]), (3, 2, 1))
        self.assertTrue(s["sonuclar"][0]["isaret"] and not s["sonuclar"][0]["guclu"])
        self.assertTrue(s["sonuclar"][1]["isaret"] and s["sonuclar"][1]["guclu"])
        self.assertFalse(s["sonuclar"][2]["isaret"])

    def test_esik_degistirilince_isaret_degisir(self):
        s = self._run([(0.20, 0.70, 0.10)], esik=0.30)
        self.assertEqual(s["isaretli"], 1)

    def test_bos_satirlar_atlanir(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "dogrulama.json").write_text(json.dumps({"satirlar": _satirlar(1)}), encoding="utf-8")
            fake = lambda jsonl, be, timeout: (0, "\n\n" + _cikti([(0.01, 0.09, 0.9)]), "", False)
            with mock.patch.object(anlam.oku, "load", return_value={"ok": False, "markdown": ""}):
                s = anlam.run(d, None, None, backend={"python": sys.executable, "model_dir": d}, calistirici=fake)
        self.assertEqual(s["isaretli"], 1)


class HataKodlari(unittest.TestCase):
    """2: yapılandırma/yol yok. 3: alt süreç hatası/zaman aşımı/eksik satır."""

    def _dir(self):
        d = tempfile.mkdtemp()
        (Path(d) / "dogrulama.json").write_text(json.dumps({"satirlar": _satirlar(2)}), encoding="utf-8")
        return d

    def test_yapilandirma_yok_kod2(self):
        d = self._dir()
        cfg = _cfg(Path(d) / "c.json", DOGRU_CFG)   # nli_backend YOK
        with mock.patch.dict(os.environ, {"QUOTEPROOF_CONFIG": cfg}):
            ayar.load(refresh=True)
            with self.assertRaises(anlam.AnlamHatasi) as cm:
                anlam.run(d)
            self.assertEqual(cm.exception.kod, 2)
        ayar._cache.clear()

    def test_yol_yok_kod2(self):
        d = self._dir()
        with self.assertRaises(anlam.AnlamHatasi) as cm:
            anlam.run(d, backend={"python": str(Path(d) / "yok-python"), "model_dir": d})
        self.assertEqual(cm.exception.kod, 2)

    def test_model_dizini_yok_kod2(self):
        d = self._dir()
        with self.assertRaises(anlam.AnlamHatasi) as cm:
            anlam.run(d, backend={"python": sys.executable, "model_dir": str(Path(d) / "yok-model")})
        self.assertEqual(cm.exception.kod, 2)

    def test_alt_surec_hatasi_kod3(self):
        d = self._dir()
        fake = lambda jsonl, be, timeout: (1, "", "torch patladı", False)
        with self.assertRaises(anlam.AnlamHatasi) as cm:
            anlam.run(d, backend={"python": sys.executable, "model_dir": d}, calistirici=fake)
        self.assertEqual(cm.exception.kod, 3)

    def test_zaman_asimi_kod3(self):
        d = self._dir()
        fake = lambda jsonl, be, timeout: (124, "", "", True)
        with self.assertRaises(anlam.AnlamHatasi) as cm:
            anlam.run(d, backend={"python": sys.executable, "model_dir": d}, calistirici=fake)
        self.assertEqual(cm.exception.kod, 3)

    def test_eksik_satir_kod3(self):
        d = self._dir()
        fake = lambda jsonl, be, timeout: (0, _cikti([(0.01, 0.09, 0.9)]), "", False)   # 2 çift, 1 satır
        with self.assertRaises(anlam.AnlamHatasi) as cm:
            anlam.run(d, backend={"python": sys.executable, "model_dir": d}, calistirici=fake)
        self.assertEqual(cm.exception.kod, 3)

    def test_dogrulama_dosyasi_yok_kod2(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(anlam.AnlamHatasi) as cm:
                anlam.run(d, backend={"python": sys.executable, "model_dir": d})
        self.assertEqual(cm.exception.kod, 2)


class Isaretle(unittest.TestCase):
    """İşaretleme: madde işaretinden sonra, Kısmen ön eki varsa ARDINA; idempotent."""

    def _not(self, prefix=""):
        return (f'# T\n## S\n### Alıntılı bulgular\n- {prefix}Bulgu metni burada yeterince uzun — '
                f'[K](https://x.example/a) {KUNYE}\n### Çıkarımlar\n- yorum\n### Boşluklar\n- —\n')

    def _sonuc(self, guclu=False):
        return {"sonuclar": [{"not": "n.md", "iddia": f'Bulgu metni burada yeterince uzun — [K](https://x.example/a) {KUNYE}',
                              "kaynak": "https://x.example/a", "oncul_turu": "pencere",
                              "ent": 0.03, "neu": 0.5, "con": 0.88 if guclu else 0.10, "isaret": True, "guclu": guclu}]}

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "n.md"
            p.write_text(self._not(), encoding="utf-8")
            n1 = anlam.isaretle(d, self._sonuc())
            n2 = anlam.isaretle(d, self._sonuc())
            text = p.read_text(encoding="utf-8")
        self.assertEqual((n1, n2), (1, 0))
        self.assertEqual(text.count("⚠ [Anlam zayıf:"), 1)
        self.assertIn("ent=0.03", text)

    def test_kismen_onekinden_sonra_eklenir(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "n.md"
            p.write_text(self._not("⚠ [Kısmen: kısmi kanıt] "), encoding="utf-8")
            n = anlam.isaretle(d, self._sonuc(guclu=True))
            satir = next(l for l in p.read_text(encoding="utf-8").splitlines() if "Bulgu metni" in l)
        self.assertEqual(n, 1)
        self.assertIn("- ⚠ [Kısmen: kısmi kanıt] ⚠ [Anlam zayıf: ent=0.03 çelişki=0.88] Bulgu metni", satir)

    def test_isaretsiz_sonuc_dokunmaz(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "n.md"
            p.write_text(self._not(), encoding="utf-8")
            s = self._sonuc()
            s["sonuclar"][0]["isaret"] = False
            self.assertEqual(anlam.isaretle(d, s), 0)
            self.assertNotIn("Anlam zayıf", p.read_text(encoding="utf-8"))


class Ayarlama(unittest.TestCase):
    """ayar.nli_backend şeması: yoksa None, aralık/tip doğrulaması, dosya varlığı YÜKLEMEDE denetlenmez, describe satırı."""

    def _yukle(self, obj):
        d = tempfile.mkdtemp()
        cfg = _cfg(Path(d) / "c.json", obj)
        return mock.patch.dict(os.environ, {"QUOTEPROOF_CONFIG": cfg})

    def test_yoksa_none_ve_describe_yok(self):
        with self._yukle(DOGRU_CFG):
            ayar.load(refresh=True)
            self.assertIsNone(ayar.nli_backend())
            self.assertIn("anlam: yok", ayar.describe())
        ayar._cache.clear()

    def test_gecerli_varsayilanlar_ve_tilde_acilir(self):
        obj = {"models": {"x": {"cli": "m"}},
               "nli_backend": {"python": "~/venv/bin/python", "model_dir": "~/nli-model", "cihaz": "cpu"}}
        with self._yukle(obj):
            ayar.load(refresh=True)
            b = ayar.nli_backend()
            self.assertEqual((b["esik"], b["pencere"], b["cihaz"]), (0.10, 300, "cpu"))
            self.assertTrue(b["python"].startswith(str(Path.home())))
            self.assertNotIn("~", b["model_dir"])
            self.assertIn("anlam: var", ayar.describe())
        ayar._cache.clear()

    def test_dosya_varligi_yuklemede_denetlenmez(self):
        obj = {"models": {"x": {"cli": "m"}}, "nli_backend": {"python": "/yok/bir/py", "model_dir": "/yok/bir/model"}}
        with self._yukle(obj):
            ayar.load(refresh=True)   # hata VERMEMELİ (varlık kullanımda denetlenir)
            self.assertEqual(ayar.nli_backend()["python"], "/yok/bir/py")
        ayar._cache.clear()

    def test_gecersiz_degerler(self):
        for kotu in ({"esik": 1.5}, {"esik": -0.1}, {"esik": "yüksek"}, {"pencere": 10}, {"pencere": 5000},
                     {"pencere": 300.5}, {"cihaz": "cuda"}, {"python": ""}, {"model_dir": 5}):
            obj = {"models": {"x": {"cli": "m"}}, "nli_backend": {"python": "/a", "model_dir": "/b", **kotu}}
            with self._yukle(obj), self.assertRaises(ayar.ConfigError):
                ayar.load(refresh=True)
            ayar._cache.clear()

    def test_nli_backend_nesne_degilse_hata(self):
        with self._yukle({"models": {"x": {"cli": "m"}}, "nli_backend": "yol"}):
            with self.assertRaises(ayar.ConfigError):
                ayar.load(refresh=True)
        ayar._cache.clear()


class Render(unittest.TestCase):
    """anlam.md: veri uyarısı, özet sayıları, işaretli tablo ve Sınırlama'daki ölçülmüş oranlar."""

    def _sonuc(self):
        return {"cift": 3, "isaretli": 1, "guclu": 0, "esik": 0.10, "pencere": 300, "atlanan": {},
                "sonuclar": [
                    {"not": "n.md", "iddia": "x" * 60, "kaynak": "https://x.example/a", "oncul_turu": "pencere",
                     "ent": 0.03, "neu": 0.5, "con": 0.1, "isaret": True, "guclu": False},
                    {"not": "n.md", "iddia": "y" * 60, "kaynak": "https://x.example/b", "oncul_turu": "alinti",
                     "ent": 0.90, "neu": 0.05, "con": 0.05, "isaret": False, "guclu": False}]}

    def test_bolumler_ve_sinirlama_sayilari(self):
        t = anlam.render(self._sonuc())
        self.assertIn(denetle.VERI_UYARISI, t)
        self.assertIn("3 çift hesaplandı", t)
        self.assertIn("1 işaretli", t)
        self.assertIn("## Sınırlama", t)
        self.assertIn("KANIT DEĞİLDİR", t)
        self.assertIn("önce şuna bak", t)
        self.assertIn("Doğrulandı", t)
        for oran in ("%11", "%36", "%13", "%46", "%22", "%68", "%26"):
            self.assertIn(oran, t)

    def test_isaretli_yoksa_tablo_bos(self):
        s = self._sonuc()
        s["isaretli"] = 0
        for r in s["sonuclar"]:
            r["isaret"] = False
        self.assertIn("İşaretli çift yok", anlam.render(s))

    def test_yaz_md_ve_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = anlam.yaz(Path(d) / "anlam.md", self._sonuc())
            self.assertTrue(p.exists())
            j = Path(d) / "anlam.json"
            self.assertTrue(j.exists())
            self.assertIn("Sınırlama", p.read_text(encoding="utf-8"))
            self.assertIn("sonuclar", json.loads(j.read_text(encoding="utf-8")))


class Kuru(unittest.TestCase):
    def test_kuru_model_cagirmaz(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "dogrulama.json").write_text(json.dumps({"satirlar": _satirlar(2)}), encoding="utf-8")
            with mock.patch.object(anlam, "_calistir", side_effect=AssertionError("çağrılmamalı")), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                rc = anlam.main([d, "--kuru"])
        self.assertEqual(rc, 0)
        self.assertIn("2 çift hesaplanacak", out.getvalue())


class ArastirAnlam(unittest.TestCase):
    """arastir.py --anlam: kapalıyken çağrılmaz, açıkken çağrılır, hata ana akışı düşürmez."""

    NOTE = ("# Konu\n\n## Soru 1\n### Özet\nEk yük ölçüldü.\n### Alıntılı bulgular\n"
            "- A — \"The overhead is about 8% on x86-64 Linux.\" — [A](https://example.org/a) (2025-10, birincil)\n"
            "- B — \"A second quote long enough for the checker.\" — [B](https://example.org/b) (2025-10, birincil)\n"
            "- C — \"A third quote long enough for the checker.\" — [C](https://example.org/c) (2025-10, birincil)\n"
            "### Çıkarımlar\n- (yok)\n### Boşluklar\n- (belirtilmedi)\n")
    PLAN = [{"slug": "konu", "konu": "k", "sorular": ["s?"], "min_url": 3}]

    def _run(self, extra=(), anlam_hata=False):
        calls = []

        def fake_anlam_run(*a, **k):
            calls.append("run")
            if anlam_hata:
                raise anlam.AnlamHatasi("nli_backend yok", kod=2)
            return {"cift": 2, "isaretli": 1, "guclu": 0, "esik": 0.10, "pencere": 300, "sonuclar": [], "atlanan": {}}

        def fake_yaz(cikti, sonuc):
            calls.append("yaz")
            Path(cikti).write_text("md", encoding="utf-8")

        def fake_worker(item, base, args, delay=0.0, sequence=None):
            (base / "notlar" / f"{item['slug']}.md").write_text(self.NOTE, encoding="utf-8")
            return {"slug": item["slug"], "ok": True, "deneme": 1, "arka": "cli", "rc": 0, "hata": "",
                    "bayt": len(self.NOTE), "sure_sn": 1, "denemeler": [], "jeton": [1, 1], "araclar": {}}

        def fake_run(cmd, check=False, **k):
            calls.append("cmd")
            return mock.Mock(returncode=0)

        with tempfile.TemporaryDirectory() as d:
            Path(d, "PLAN.json").write_text(json.dumps(self.PLAN), encoding="utf-8")
            argv = ["arastir.py", str(Path(d) / "PLAN.json"), "-d", d, "--arka", "cli", *extra]
            page = {"ok": True, "markdown": "Lorem ipsum dolor sit amet. " * 30, "hata": ""}
            with mock.patch.object(sys, "argv", argv), mock.patch.object(arastir, "available_backends", return_value={"cli"}), \
                 mock.patch.object(arastir, "run_worker", side_effect=fake_worker), \
                 mock.patch.object(destek.oku, "load", return_value=page), \
                 mock.patch.object(arastir.subprocess, "run", side_effect=fake_run), \
                 mock.patch.object(anlam, "run", side_effect=fake_anlam_run), \
                 mock.patch.object(anlam, "yaz", side_effect=fake_yaz), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = arastir.main()
        return calls, rc

    def test_kapaliyken_cagrilmaz(self):
        calls, _ = self._run()
        self.assertNotIn("run", calls)
        self.assertNotIn("yaz", calls)

    def test_acikken_cagrilir(self):
        calls, _ = self._run(["--anlam"])
        self.assertIn("run", calls)
        self.assertIn("yaz", calls)

    def test_hata_ana_akisi_dusurmez(self):
        calls, rc = self._run(["--anlam"], anlam_hata=True)
        self.assertIn("run", calls)
        self.assertNotIn("yaz", calls)
        self.assertNotEqual(rc, 2)


class Bagimsiz(unittest.TestCase):
    """Çekirdek hat bağımlılıksızdır: anlam.py yalnız standart kütüphane + yerel modüller ister (torch import edilmez)."""

    def test_anlam_torch_istemez(self):
        import ast
        kaynak = Path(anlam.__file__).read_text(encoding="utf-8")
        moduller = {n.names[0].name.split(".")[0] for n in ast.walk(ast.parse(kaynak)) if isinstance(n, ast.Import)}
        moduller |= {n.module.split(".")[0] for n in ast.walk(ast.parse(kaynak))
                     if isinstance(n, ast.ImportFrom) and n.module}
        self.assertNotIn("torch", moduller)
        self.assertNotIn("transformers", moduller)


if __name__ == "__main__":
    unittest.main()