#!/usr/bin/env python3
"""Doğrulama ve rapor denetimindeki "yanlış güven" kusurları için gerileme testleri (çevrimdışı; ağ ve model kullanmaz).

Kapsam: K2 sayı–alıntı yakınlık kapısı · K3 "Kısmen" temiz kopya ön eki · K5 rapor_kontrol havuz sınırı ·
O7 VERİ uyarısı başlığı ve gh depo açıklaması temizliği · O1 kanıt kesme sınırı görünürlüğü.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import denetle  # noqa: E402
import destek  # noqa: E402
import dogrula  # noqa: E402
import rapor_kontrol  # noqa: E402


def _sayfalar(mapping):
    def load(url, cache_dir=None):
        if url in mapping:
            return {"ok": True, "markdown": mapping[url], "hata": ""}
        return {"ok": False, "markdown": "", "hata": "erişilemedi"}
    return load


class SayiAlintiYakinligi(unittest.TestCase):
    """K2: iddianın sayısı doğrulanan alıntıdan ±SAYI_ALINTI_PENCERE karakter dışındaysa 'Kısmen'."""
    FILL = "Lorem ipsum dolor sit amet consectetur adipiscing elit. " * 70          # ~4000 karakter
    QUOTE = "the model achieves 290 tokens per second on this benchmark"

    def _page(self, uzak):
        bas = f"Abstract. {self.QUOTE}. The tuning details follow. "
        kuyruk = "A later table reports 290 ms for the same run. " if uzak else ""
        return dogrula.page_text_norm(bas + self.FILL + kuyruk)

    def _kayit(self):
        return f'Gecikme 290 ms ölçüldü — "{self.QUOTE}" — [U](https://a.example/p)'

    def test_sayi_alintidan_uzaksa_kismen_ve_neden_yazilir(self):
        ev = dogrula.evidence(self._kayit())
        verdict, found, total, missing, neden = dogrula.judge_detayli(ev, self._page(uzak=True))
        self.assertEqual(verdict, "Kısmen")
        self.assertIn("sayı alıntıdan ~", neden)
        self.assertEqual([u["sayi"] for u in dogrula.sayi_alintidan_uzak(ev, self._page(uzak=True))], ["290ms"])
        self.assertEqual(dogrula.judge(ev, self._page(uzak=True))[0], "Kısmen")   # judge da aynı kararı verir

    def test_sayi_alintinin_penceresinde_dogrulandi_kalir(self):
        ev = dogrula.evidence(self._kayit())
        yakin = dogrula.page_text_norm(f"{self.QUOTE}. Gecikme 290 ms civarında. " + self.FILL)
        self.assertEqual(dogrula.judge(ev, yakin)[0], "Doğrulandı")
        self.assertEqual(dogrula.judge_detayli(ev, yakin)[4], "")

    def test_alinti_bulunamazsa_davranis_degismez(self):
        ev = dogrula.evidence('Gecikme 290 ms — "this exact sentence is definitely absent from the page text" — [U](https://a.example/p)')
        self.assertEqual(dogrula.judge(ev, self._page(uzak=True))[0], "Bulunamadı")
        self.assertEqual(dogrula.sayi_alintidan_uzak(ev, self._page(uzak=True)), [])

    def test_pencere_sabiti_buyutulunce_uzak_sayi_dogrulanir(self):
        ev = dogrula.evidence(self._kayit())
        with mock.patch.object(dogrula, "SAYI_ALINTI_PENCERE", 10_000):
            self.assertEqual(dogrula.judge(ev, self._page(uzak=True))[0], "Doğrulandı")


class KismenOneki(unittest.TestCase):
    """K3: temiz kopyada 'Kısmen' satırı ön ek alır; 'Bulunamadı' satırı yine düşer; ayrıştırıcılar ön eki atlar."""
    QUOTE = "the model achieves 290 tokens per second on this benchmark"

    def _note(self):
        return ("# k\n## S\n### Alıntılı bulgular\n"
                f'- Gecikme 290 ms — "{self.QUOTE}" — [U](https://a.example/p)\n'
                '- Uydurma — "this sentence is not on the page at all" — [U2](https://b.example/2)\n'
                "### Çıkarımlar\n- x\n### Boşluklar\n- y\n")

    def _sayfalar(self):
        uzak = dogrula.page_text_norm(f"Abstract. {self.QUOTE}. Detaylar. " + "Lorem ipsum dolor sit amet. " * 60 +
                                      "A later table reports 290 ms for the same run.")
        return {"https://a.example/p": uzak, "https://b.example/2": "Completely unrelated page text."}

    def _rows_kur(self, d):
        nd = Path(d) / "notlar"
        nd.mkdir()
        (nd / "n.md").write_text(self._note(), encoding="utf-8")
        with mock.patch.object(dogrula.oku, "load", side_effect=_sayfalar(self._sayfalar())):
            return str(nd), dogrula.run(str(nd), limit=0, jobs=1)[0]

    def test_kismen_satiri_onek_alir_bulunamadi_duser(self):
        with tempfile.TemporaryDirectory() as d:
            nd, rows = self._rows_kur(d)
            self.assertEqual({r["karar"] for r in rows}, {"Kısmen", "Bulunamadı"})
            dropped = dogrula.clean_copies(nd, rows, str(Path(d) / "temiz"))
            clean = (Path(d) / "temiz" / "n.md").read_text(encoding="utf-8")
        self.assertEqual(dropped, {"n.md": 1})
        self.assertIn("⚠ [Kısmen: sayı alıntıdan ~", clean)
        self.assertNotIn("Uydurma", clean)                                   # Bulunamadı yine çıkarıldı

    def test_onek_idempotent_ikinci_kosum_eklemez(self):
        with tempfile.TemporaryDirectory() as d:
            nd, rows = self._rows_kur(d)
            temiz = Path(d) / "temiz"
            dogrula.clean_copies(nd, rows, str(temiz))
            ikinci = Path(d) / "temiz2"
            dogrula.clean_copies(str(temiz), rows, str(ikinci))             # zaten işaretli kopya üzerinde yeniden çalış
            clean = (ikinci / "n.md").read_text(encoding="utf-8")
        self.assertEqual(clean.count("⚠ [Kısmen:"), 1)

    def test_denetle_analyze_onekini_atlar(self):
        note = ("# k\n## S\n### Alıntılı bulgular\n"
                "- ⚠ [Kısmen: sayı alıntıdan ~900 kr uzak] Bulgu metni burada — [U](https://a.example/p)\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "n.md"
            p.write_text(note, encoding="utf-8")
            r = denetle.analyze(p)
        self.assertEqual(r["bulgu"], 1)
        self.assertEqual(r["findings"][0]["metin"], "Bulgu metni burada — [U](https://a.example/p)")
        self.assertEqual(r["urls"], ["https://a.example/p"])

    def test_evidence_oneki_kanit_saymaz(self):
        ev = dogrula.evidence("⚠ [Kısmen: sayı alıntıdan ~900 kr uzak] Bulgu — [U](https://a.example/p)")
        self.assertEqual(ev["sayi"], [])                                    # ön ekin "900" rakamı kanıt sayılmaz

    def test_rapor_kontrol_madde_onekini_ayristirmayi_bozmaz(self):
        items = rapor_kontrol.parse_items("- ⚠ [Kısmen: kısmi kanıt] Bulgu metni [U](https://a.example/p)\n")
        self.assertEqual(items[0]["tur"], "madde")
        self.assertIn("https://a.example/p", items[0]["metin"])

    def test_destek_ayristiricisi_onekle_cokmez(self):
        txt = destek._line_search_text("- ⚠ [Kısmen: kısmi kanıt] Bulgu metni — [U](https://a.example/p)")
        self.assertIsInstance(txt, str)
        self.assertIn("bulgu metni", txt)
        self.assertEqual(destek.concrete_items("⚠ [Kısmen: kısmi kanıt] cümle", set()), [])   # ön ek tek başına öğe üretmez

    def test_neden_yoksa_varsayilan_kisaltma_yazilir(self):
        with tempfile.TemporaryDirectory() as d:
            nd = Path(d) / "notlar"
            nd.mkdir()
            (nd / "n.md").write_text("# k\n## S\n### Alıntılı bulgular\n- Bulgu metni burada — [U](https://a.example/p)\n",
                                     encoding="utf-8")
            rows = [{"not": "n.md", "karar": "Kısmen", "iddia": "Bulgu metni burada — [U](https://a.example/p)", "neden": ""}]
            dogrula.clean_copies(str(nd), rows, str(Path(d) / "temiz"))
            clean = (Path(d) / "temiz" / "n.md").read_text(encoding="utf-8")
        self.assertIn("- ⚠ [Kısmen: kısmi kanıt] Bulgu metni burada", clean)


class HavuzSiniri(unittest.TestCase):
    """K5: MAX_POOL'u aşan URL'ler sessizce atlanmaz; kaynak-okunamadı (havuz sınırı) uyarısı üretir, --siki düşer."""
    RAPOR = "".join(f"- kayıt {i} [U{i}](https://h{i}.example/p)\n" for i in range(61))
    PAGE = {"ok": True, "markdown": "içerik metni " * 40, "hata": ""}

    def test_61_url_havuz_sinirinda_uyari_uretir(self):
        self.assertGreaterEqual(rapor_kontrol.MAX_POOL, 60)
        res = rapor_kontrol.run(self.RAPOR, loader=lambda u: self.PAGE, max_pool=60)
        self.assertEqual((res["url_sayisi"], res["havuz_disi_sayisi"]), (61, 1))
        sinir = [f for f in res["ekstra"] if f["tur"] == "kaynak-okunamadı (havuz sınırı)"]
        self.assertEqual(len(sinir), 1)
        self.assertIn("https://h60.example/p", sinir[0]["mesaj"])
        self.assertGreaterEqual(rapor_kontrol.summarize(res)["uyarı"], 1)
        self.assertIn("havuz sınırı dışında", rapor_kontrol.render(res, "r.md"))

    def test_varsayilan_havuz_61_urlyi_kapsar(self):
        res = rapor_kontrol.run(self.RAPOR, loader=lambda u: self.PAGE)     # varsayılan 120
        self.assertEqual((res["url_sayisi"], res["havuz_disi_sayisi"]), (61, 0))

    def test_cli_havuz_secenegi_ve_siki_cikis_kodu(self):
        with tempfile.TemporaryDirectory() as d:
            rp = Path(d) / "rapor.md"
            rp.write_text(self.RAPOR, encoding="utf-8")
            with mock.patch.object(rapor_kontrol.oku, "load", return_value=self.PAGE), \
                 mock.patch.object(sys, "argv", ["rapor_kontrol.py", str(rp), "--havuz", "60", "--siki"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rapor_kontrol.main(), 1)
            self.assertIn("kaynak-okunamadı (havuz sınırı)", (Path(d) / "rapor-kontrol.md").read_text(encoding="utf-8"))
            with mock.patch.object(rapor_kontrol.oku, "load", return_value=self.PAGE), \
                 mock.patch.object(sys, "argv", ["rapor_kontrol.py", str(rp), "--havuz", "120", "--siki"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rapor_kontrol.main(), 0)


class VeriUyarisi(unittest.TestCase):
    """O7: dogrulama.md / destek.md / denetim.md başına tek satırlık VERİ etiketi; gh depo açıklaması tek satır."""
    def test_uc_render_veri_uyarisiyla_baslar(self):
        cov = {"toplam_bulgu": 0, "denenen": 0, "kanitsiz": 0, "limit_disi": 0, "urlsiz": 0, "sinir_disi_kanit": 0}
        self.assertTrue(dogrula.render([], cov).startswith(denetle.VERI_UYARISI))
        self.assertTrue(destek.render({}).startswith(denetle.VERI_UYARISI))
        self.assertTrue(denetle.render([], {}, [], False).startswith(denetle.VERI_UYARISI))

    def test_gh_depo_aciklamasi_satir_sonu_ve_backtick_temizlenir(self):
        payload = [5, False, "2026-10-01T00:00:00Z", False, "first line\nsecond `code` line"]
        with mock.patch.object(denetle.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")):
            r = denetle.check_repo("a/b")
        self.assertNotIn("\n", r["not"])
        self.assertNotIn("`", r["not"])
        self.assertEqual(r["not"], "first line second code line")


class KanitKesmeSiniri(unittest.TestCase):
    """O1: alıntı 3 / kod 4 / sayı 5 / URL 2 üst sınırı nedeniyle denetlenmeyen öğeler görünür kılınır (davranış değişmez)."""
    def test_evidence_atlanan_sayilari(self):
        text = " ".join(f'"a fairly long quotation number {i}"' for i in range(4))   # 4 alıntı → 1 atlanır
        text += " " + " ".join(f"{i}00x" for i in range(1, 8))                        # 7 sayı → 2 atlanır
        text += " " + " ".join(f"`kod{i}`" for i in range(6))                         # 6 kod → 2 atlanır
        ev = dogrula.evidence(text)
        self.assertEqual((len(ev["alinti"]), ev["atlanan"]["alinti"]), (3, 1))
        self.assertEqual((len(ev["sayi"]), ev["atlanan"]["sayi"]), (5, 2))
        self.assertEqual((len(ev["kod"]), ev["atlanan"]["kod"]), (4, 2))

    def test_kapsam_satirinda_sinir_bildirimi(self):
        cov = {"toplam_bulgu": 1, "denenen": 1, "kanitsiz": 0, "limit_disi": 0, "urlsiz": 0, "sinir_disi_kanit": 4}
        self.assertIn("4 öğe sınır nedeniyle denetlenmedi", dogrula.render([], cov))
        cov0 = {**cov, "sinir_disi_kanit": 0}
        self.assertNotIn("sınır nedeniyle denetlenmedi", dogrula.render([], cov0))

    def test_run_sinir_disi_sayisini_kapsama_yazar(self):
        note = ("# k\n## S\n### Alıntılı bulgular\n"
                '- Bulgu "a fairly long quotation here" ' + " ".join(f"{i}00x" for i in range(1, 8)) +
                " — [U1](https://a.example/1) [U2](https://b.example/2) [U3](https://c.example/3)\n")
        with tempfile.TemporaryDirectory() as d:
            nd = Path(d) / "notlar"
            nd.mkdir()
            (nd / "n.md").write_text(note, encoding="utf-8")
            with mock.patch.object(dogrula.oku, "load", side_effect=_sayfalar({})):
                rows, cov = dogrula.run(str(nd), limit=0, jobs=1)
        self.assertEqual(cov["sinir_disi_kanit"], 3)   # 2 sayı (7→5) + 1 URL (3→2)


if __name__ == "__main__":
    unittest.main()

class KismenOnEkiTuketicileri(unittest.TestCase):
    """Temiz kopyadaki "⚠ [Kısmen: …]" ön eki destek.py ve uzlas.py'de iddia/aranan metne girmez."""

    def test_destek_arama_metni_on_eki_atar(self):
        import destek
        a = destek._line_search_text("- ⚠ [Kısmen: sayı alıntıdan ~900 kr uzak] RTX 5090 hızı 290 t/s — [K](https://x.example/a)")
        self.assertNotIn("kismen", a.replace("ı", "i").lower())
        self.assertIn("rtx 5090", a.lower())

    def test_uzlas_iddia_sozcukleri_on_eki_icermez(self):
        import tempfile, uzlas
        from pathlib import Path
        not_ = ("# k\n\n## S\n### Özet\nx\n### Alıntılı bulgular\n"
                "- ⚠ [Kısmen: kısmi kanıt] Bellek bant genişliği büyür [K](https://x.example/a)\n"
                "### Çıkarımlar\n- c\n### Boşluklar\n- b\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "n.md"
            p.write_text(not_, encoding="utf-8")
            f = uzlas.findings(p)
        self.assertEqual(len(f), 1)
        self.assertFalse({"kısmen", "kismen", "kısmi", "kanıt"} & f[0]["q"])
        self.assertIn("bant", " ".join(f[0]["q"]))
