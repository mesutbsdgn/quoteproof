# quoteproof (eski ad: arastir-ogren)

**Ne işe yarar:** Çok kaynaklı, kanıtlı araştırma ve öğrenme raporu üretir. Konuyu alt konulara böler, ucuz modeller paralel web taraması yapar, **0 token'lık Python betikleri** her alıntının kaynak sayfada gerçekten geçtiğini (sayı, sürüm, tarih dahil) doğrular; Claude kritik iddiaları kendisi açıp kontrol eder ve Türkçe rapor yazar.

**Ne zaman kullanılır:** "araştır", "karşılaştır", "trend/pazar incele", "X'i öğrenmek istiyorum". **Kullanma:** tek olgu/sürüm/fiyat sorusu (doğrudan arama yeter), yerel kod incelemesi.

**Hangi dosyayı oku:** `SKILL.md` (derinlik seçimi, adımlar, kurallar). Şablonlar `references/` içinde (`arastirmaci-istemi.md`, `rapor-sablonu.md`, `ortak-brief-sablonu.md`).

## Yapılandırma
`quoteproof.example.json` dosyasını `~/.config/quoteproof/config.json` olarak kopyalayıp doldur (ya da `QUOTEPROOF_CONFIG=yol`). Anahtarın kendisi dosyaya yazılmaz, yalnız ortam değişkeninin ADI yazılır. Durum: `python3 scripts/ayar.py`. Codex ve yalnız-Claude örnekleri de var (`quoteproof.codex.example.json`, `quoteproof.claude-only.example.json`).

## Betikler (`scripts/`)
`arastir.py` (çalıştırıcı: plan → paralel çalışanlar → notlar → denetim) · `oku.py` (nazik sayfa okuma, robots.txt'e uyar) · `dogrula.py` (iddia–kaynak doğrulama) · `denetle.py` (not denetimi) · `guven.py` (kaynak güvenilirlik puanı) · `kapsama.py` (planlanan olgular bulgularda var mı) · `uzlas.py` (bağımsız koşuların uzlaşısı) · `hakem.py` (isteğe bağlı model hakemi: alıntı doğru konuya mı ait) · `rapor_kontrol.py`, `rapor_olc.py` (rapor denetimi/ölçümü) · `ayar.py` (yapılandırma durumu). Hakem dışındakiler 0 LLM jetonu harcar.

## Doğrulama
```bash
cd ~/.agents/skills/quoteproof/scripts && python3 -I -m pytest -q    # 298 test
```

## Hangi ajanda kayıtlı
Bu makinede, skill dizini okuyan ajanların hepsine `~/.agents/skills/quoteproof` symlink olarak bağlıdır (makineye özel ayrıntı: `yonlendir` skill README'si).

## Genel (açık kaynak) proje
Aynı kodun yayın deposu `~/Documents/03_PROJELER/quoteproof` (GitHub: mesutbsdgn/quoteproof). Orada skill klasörü hâlâ `arastir-ogren/` adını taşıyor; bu makinedeki kopya `quoteproof/`. İkisi arasında senkron elle yapılır.

_Son gözden geçirme: 18 Eki 2026. Yeniden adlandırma: arastir-ogren → quoteproof (17 Eki 2026)._
