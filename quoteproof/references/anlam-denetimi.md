# Anlam denetimi (isteğe bağlı, NLI)

Betik hata iletileri buraya yönlendirir. Yalnız kullanıcı isterse ya da `--anlam` kullanılacaksa oku.

`dogrula.py` alıntının sayfada GEÇTİĞİNİ söyler; alıntı doğru olsa da iddia onu yanlış öznenin üstüne yapıştırmış olabilir. `anlam.py` bu soruyu çok dilli bir NLI modeline sorar: (öncül = sayfada alıntının ±`pencere` karakter çevresi, hipotez = bulgunun iddia metni) → entailment/neutral/contradiction. entailment eşiğin altındaysa bulgu **işaretlenir** ve sıralanır. **Karar "Doğrulandı" DEĞİŞMEZ**; bu GÜRÜLTÜLÜ bir "önce şuna bak" sinyalidir, KANIT DEĞİLDİR. Hat bağımlılıksız kalır: model AYRI bir sanal ortamda (`torch` + `transformers`) alt süreç olarak çalışır. Varsayılan KAPALI.

Ölçülen davranış (198 gerçek doğrulanmış bulgu; öncül = sayfada alıntının ±300 karakter çevresi, hipotez = iddia): entailment < 0,05 → gerçek çiftlerde %11 yanlış alarm, karıştırılmış çiftlerin %36'sı yakalanır; < 0,10 → %13 / %46; < 0,30 → %22 / %68. Öncül yalnızca alıntı olunca yanlış alarm %26'ya çıkar (tarih/sürüm ayrıntısı alıntı dışında kalır). Yalnız `Doğrulandı` satırları denenir; çeviri/kısa etiket iddialarında ve İngilizce dışı kaynaklarda zayıflar.

**Kurulum (elle, bir kez):** `bash $S/anlam_kur.sh` — `~/.cache/quoteproof/` içine venv (torch + transformers + bağımlılıkları ~0,9 GB) ve modeli (mDeBERTa-v3 çok dilli NLI, ~0,55 GB, MIT) indirir; `~/.config/quoteproof/config.json` dosyasını DEĞİŞTİRMEZ, eklenecek bloğu yazdırır. Sonra yapılandırmaya ekle:

```json
"nli_backend": {"python": "~/.cache/quoteproof/nli-venv/bin/python", "model_dir": "~/.cache/quoteproof/nli-model", "esik": 0.10, "pencere": 300, "cihaz": "auto"}
```

`python3 $S/ayar.py` → `anlam: var`. **Kullanım:** `arastir.py ... --anlam` (destek bloğundan sonra çalışır, `anlam.md`/`anlam.json` yazar ve varsa `notlar-temiz/`i işaretler; `--bosluk-turu` çocuğuna taşınmaz) ya da sonradan `python3 $S/anlam.py ARASTIRMA_DIZINI --isaretle`; `--kuru` önce kaç çiftin hesaplanacağını gösterir (model çağırmaz). `nli_backend` yoksa ya da yol bulunamazsa çıkış kodu **2**, alt süreç hata/zaman aşımı/eksik çıktı verirse **3**; `arastir.py` bu hatayı ana akışı düşürmeden uyarı olarak yazar. İşaret "rapordan çıkar" değil, "kaynağı elle aç ve bak" sırasıdır.
