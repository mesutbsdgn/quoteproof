# Quoteproof — DeepSeek V4 Pro 0813 inceleme raporu

- **Model:** deepseek-v4-pro-0813 (Alibaba Token Plan / OpenCode; Dagit üzerinden).
- **İncelenen durum:** commit 41bfbe9 ve yerel README giriş düzeltmeleri.
- **Yöntem:** İnceleme geçici bir kaynak kopyasında yapıldı; asıl depo bu model çağrısında değiştirilmedi. İstemde ağ ve test çalıştırmaması istendi; model de raporunda salt statik inceleme yaptığını belirtiyor. Bu rapor çağrının tüm araç günlüklerini içermediğinden, modelin araç kullanımını bağımsız olarak kanıtlamaz. Codex bu incelemede test çalıştırmadı.

## Codex doğrulama notu

- **R1 — Kapsama metriği: doğrulandı.** Başarılı çalışan notları (good) kapsamaya giriyor; dogrula.py yalnızca Bulunamadı maddeleri temiz kopyadan çıkarıyor. Bu yüzden Kısmen, Erişilemedi ve Kanıt yok kararları kapsama sayımında kalabiliyor.
- **R2 — PDF 60 sayfa sınırı: doğrulandı.** pdftotext -l 60, 61. sayfa ve sonrasını doğrulayıcının görebileceği metinden çıkarıyor. Bu yanlış negatif riski yaratır.
- **R3 — robots.txt sırasında IP pininin değişmesi: kod akışı doğrulandı; istismar edilebilir SSRF doğrulanmadı.** robots.txt isteği aynı thread-local IP alanını yeniden yazabiliyor. İki istek de DNS adresini denetlediği için bunu doğrulanmış SSRF açığı diye sunmuyorum; istek hedefiyle pinlenen IP arasındaki tutarlılık ve test kapsamı iyileştirilmeli.
- **R4 — Gizli değer maskeleme kapsamı: doğrulandı.** redact() hata metinlerinde kullanılıyor; CLI çalışanının başarılı çıktısı doğrudan nota yazılıyor. Bu, içerikte gerçekten sır varsa sızıntı riski doğurur; bu incelemede herhangi bir anahtar değeri aranmadı veya okunmadı.
- **R5 — Test sayısı: statik sayımla doğrulandı.** Test dosyalarında test_ metot tanımı sayıları 235 ve 56; README’de 219/54, sürüm notunda 194/54 yazıyor. Testler çalıştırılmadığı için bu, toplanan veya geçen test sayısı iddiası değildir.
- **R6 — OpenCode izinlerinin çalışma anında uygulanması: doğrulanmamış entegrasyon sınırı.** Depo yapılandırmayı üretir; gerçek OpenCode sürümünün bu izinleri uyguladığını bu statik inceleme teyit etmez. Model çıktısındaki README ölçüm atfı doğru değil; ilgili README satırı tehdide karşı tasarımı anlatıyor, canlı ölçüm iddiası taşımıyor.

Aşağıdaki model raporundaki dosya yolları depo köküne göre düzeltildi. Öneriler henüz uygulanmadı.

---

Aşağıda, geçici kopyadaki tüm proje dosyalarını okuyarak hazırladığım inceleme raporu bulunuyor. Kod, ağ erişimi gerektirmeden salt statik okundu; test çalıştırılmadı, dosya değiştirilmedi.

---


## 1. Genel değerlendirme

Quoteproof, "LLM'in uydurduğu alıntıyı ikinci bir LLM'e değil, kaynağın kendisine kontrol ettirme" fikrini tutarlı ve dürüst biçimde uyguluyor. Çekirdek iddia (sıfır jeton harcayan, deterministik, sınır-duyarlı metin doğrulama) koddan doğrulanıyor: `arastir-ogren/scripts/dogrula.py` alıntı/kod/sayı kanıtlarını çıkarır (`evidence`, arastir-ogren/scripts/dogrula.py:204-223), her birini `arastir-ogren/scripts/oku.py` üzerinden çekilen sayfada arar (`judge`, arastir-ogren/scripts/dogrula.py:294-318) ve hata durumlarında "Doğrulandı" vermez. README'nin en değerli yanı ise alışılmadık ölçüde dürüst olması: doğrulamanın *metinsel* olduğunu, güven puanının *buluşsal* olduğunu, canlı hattın güvenilirliğinin *kanıtlanmadığını* açıkça yazıyor (README.md:330-346). Bu, "kanıtların kapsamı" konusunda koda sadık.

Kod kalitesi derli toplu; modüler (`oku`, `denetle`, `dogrula`, `destek`, `kapsama`, `rapor_kontrol`, `uzlas`, `hakem`, `guven`, `ayar`, `mcp_oku`), sağlayıcı/model ayrıntıları koda gömülü değil (`arastir-ogren/scripts/ayar.py`), ve kritik güvenlik yolları (SSRF, DNS sabitleme, robots.txt) hem özenli yazılmış hem de kapsamlı çevrimdışı testlerle sabitlenmiş. Aşağıdaki risklerin çoğu "hata" değil; kapsam/doğrulama *hassasiyetine* ilişkin boşluklar.

## 2. Güçlü yanlar

- **Gerçek sıfır jeton harcayan, tekrarlanabilir doğrulayıcı.** `number_positions` sınır duyarlıdır (`1.2` `11.20` içinde sayılmaz, arastir-ogren/scripts/dogrula.py:259-267); sayı yazım varyantları uzlaştırılır (`%26,2`↔`26.2%`, `100.000`↔`100,000`, arastir-ogren/scripts/dogrula.py:270-291); alıntı yokken rakamın tek başına maddeyi kurtarmaması korunmuş (arastir-ogren/scripts/dogrula.py:308-309).
- **Sertleştirilmiş okuyucu.** Yalnız `http(s)` ve `ipaddress.is_global` ile kamuya açık adresler (arastir-ogren/scripts/oku.py:95-124); `_PinnedHTTPConnection` ile doğrulanan IP'ye bağlantı (arastir-ogren/scripts/oku.py:127-135); her yönlendirme adımı yeniden doğrulanır (arastir-ogren/scripts/oku.py:184-203); regex'siz, sınırlı robots.txt eşleyici (ReDoS'suz, arastir-ogren/scripts/oku.py:229-311); host başına hız sınırı + `Crawl-delay` (arastir-ogren/scripts/oku.py:157-164, 351-372).
- **Kapalı kalan çalışan sözleşmesi.** Bayt alt sınırı, zorunlu "Alıntılı bulgular" başlığı, plan/onay metni reddi, benzersiz URL alt sınırı ve OpenCode için "hiç arama/okuma aracı çağrılmadı" reddi (arastir-ogren/scripts/arastir.py:327-346, 551-553).
- **Alt süreç ortamı izin listesi.** Yalnız `ENV_ALLOWLIST` + yapılandırılmış anahtar çocuğa verilir (arastir-ogren/scripts/arastir.py:91-92, 101-105); anahtar ana süreçte yazdırılmaz.
- **Süreç anahtar-üretimi ve dürüst sınır bölümü.** README.md:330-346, doğrulamanın anlamsal olmadığını ve canlı güvenilirliğin kanıtlanmadığını koda uygun biçimde yazar; dört bağımsız denemenin başarısızlıklarını gizlemez.
- **Kapsamlı çevrimdışı testler.** `arastir-ogren/scripts/test_arastir.py` 235, `arastir-ogren/scripts/test_oku.py` 56 `def test_` içeriyor; SSRF/redirect/robots/PDF/önbellek/enjeksiyon yollarının çoğu testli.

## 3. Riskler ve eksikler (önem sırasıyla)

### R1 — Kapsama metriği, "doğrulanmış" olmayan bulguları da "kapsandı" sayıyor
- **Kanıt:** `arastir-ogren/scripts/kapsama.py:74-82` (`bulgu_satirlari`) bir notun *tüm* "Alıntılı bulgular" satırını okur; `_eslesir` (arastir-ogren/scripts/kapsama.py:85-86) yalnız regex eşleşmesi yapar. `clean_copies` yalnız **"Bulunamadı"** kararlı maddeleri atar (arastir-ogren/scripts/dogrula.py:555-583); **"Kısmen", "Erişilemedi", "Kanıt yok"** maddeler `notlar-temiz/` içinde kalır. `arastir-ogren/scripts/arastir.py:771-773` kapsamayı tam da bu `notlar-temiz` üzerinde çalıştırır.
- **Etki:** README'nin "A fact counts as covered when it matches a line of the *verified* 'Alıntılı bulgular'" (README.md:260) iddiası koda tam uymuyor. Bir olgu, doğrulanamamış ("Erişilemedi") ya da kısmen doğrulanmış bir maddenin metninde geçiyorsa "kapsama 9/12" sayılabilir. Bu, tamlık sinyalini şişirip yanlış güven üretir.
- **Öneri:** Kapsamayı `dogrulama.json` kararlarıyla eşleştir ve yalnız "Doğrulandı" (en azından "Kısmen"i ayrı sayarak) kararlı maddelere bak; "Erişilemedi/Kanıt yok" maddeleri olgu kapsamasına girmesin.

### R2 — PDF okuyucu 60 sayfada kesilir; sonraki sayfalardaki alıntılar sessizce "Bulunamadı"
- **Kanıt:** `arastir-ogren/scripts/oku.py:735` — `pdftotext -l 60` çağrısı. Sayfa sayısını 60 ile sınırlayan tek öğe bu; README/SKILL bunu hiç belirtmiyor, test de yok (`arastir-ogren/scripts/test_oku.py` yalnız "pdftotext yoksa hata" ve "`-layout` kullanılmaz"ı kapsar, satır 220-224, 445-456).
- **Etki:** 60'tan uzun bir PDF'de 61. sayfa ve sonrasındaki gerçek bir alıntı "Bulunamadı" görünür ve `--temiz-yaz` ile sentezden **silinir** — yanlış negatif, doğru bulgu kaybı.
- **Öneri:** `-l` sınırını kaldır ya da sayfa sayısını parametreye/uyarıya çevir; kısıtı dokümante et ve >60 sayfalık bir PDF için bir test ekle.

### R3 — IP sabitleme, robots.txt alt isteğiyle aynı iş parçacığında ezilebilir (doğrulanmadı: istismar edilebilirlik gösterilmedi)
- **Kanıt:** `arastir-ogren/scripts/oku.py:188` `_local.ip = check_url(current)[0]` ile pin atanır; hemen ardından `arastir-ogren/scripts/oku.py:190` `robots_allowed(current)` çağrılır. Önbellek boşsa bu, `robots_state→_fetch_robots→request(...)` zincirini tetikler (arastir-ogren/scripts/oku.py:314-326) ve o iç `request`, aynı iş parçacığında `_local.ip`'i **yeniden atar**. Asıl içerik gönderimi `arastir-ogren/scripts/oku.py:197` `_send` bu (potansiyel olarak ezilmiş) değeri kullanır; `_send`'den önce pin yenilenmez.
- **Neden genel: aynı origin için `getaddrinfo` çoğunlukla aynı IP'yi döndürdüğü için pratikte etki küçük; SSRF zaten `check_url` ile engelli.** Ama "bağlantı doğrulanan IP'ye sabitlenir" (README.md:145) garantisi, robots.txt taze çekilirken kesin korunmuyor. Mevcut test (`arastir-ogren/scripts/test_oku.py:126`, `test_baglanti_dogrulanan_ipye_sabitlenir`) yalnız robots'sız yolu kapsar; bu ara yol testli değil.
- **Öneri:** İçerik `_send`'inden hemen önce `_local.ip`'i yeniden ata, ya da robots.txt çekimini `_local` durumuna dokunmayan ayrı bir `connect` yolundan yap; iki-çözümlemeli bir regresyon testi ekle.

### R4 — Gizli maskeleme dar ve yalnız "hata" metnine bağlı; CLI yolu nota ham yazıyor
- **Kanıt:** `arastir-ogren/scripts/arastir.py:86` `SECRET_RE` yalnız `api_key|token|secret|authorization|bearer` + `[A-Za-z0-9._\-]{8,}` kalıbını yakalar; `redact` (arastir-ogren/scripts/arastir.py:311-313) yalnız hata özetlerinde çağrılır. `work_cli`, `parse_text_output` çıktısını **maskesiz** nota yazar (arastir-ogren/scripts/arastir.py:465-473). `sk-…` gibi öneksiz bir anahtar değeri ya da çalışanın nota yazdığı herhangi bir sır bu kalıba girmez.
- **Etki:** README.md:336 bunu "sınırlı" diye dürüstçe kabul ediyor; yine de anahtar-not sızıntısı için somut bir açık kapı. Depodaki iddiada bir abartı yok, bu nedenle otomasyonu aşmayan bir boşluk.
- **Öneri:** Yapılandırılmış anahtarın *değerini* her çıktı dosyasında (not, calisma.json, denetim) bağımsız olarak karart; not yazılmadan önce isteğe bağlı bir gizli-tarama kapısı ekle.

### R5 — Test sayısı iddiaları kodla ve birbiriyle tutarsız
- **Kanıt:** README.md:351-352 "219 / 54 test" der; son sürüm notu README.md:394 "194 + 54" der; koddaki gerçek sayı `arastir-ogren/scripts/test_arastir.py`=235, `arastir-ogren/scripts/test_oku.py`=56 `def test_` yöntemi. Üç rakam birbirini tutmuyor.
- **Etki:** "Her düzeltmenin regresyon testi var" (README.md:153) gibi güçlü iddiaların denetlenebilirliği zayıflıyor. Testler bu incelemede çalıştırılmadı; sayılar yalnızca kaynakta tanımlı test metotlarının statik sayımıdır.
- **Öneri:** README'deki sayıyı test koleksiyonundan türet ya da sabit sayı yerine "kodun testi korur" vurgusuna dön; sürüm notundaki tarihli sayıları da tek kaynakta topla.

### R6 — OpenCode "varsayılanı yasakla" güvenlik sınırı harici bir çalışma ortamının davranışına dayanıyor; bu depoda doğrulanamaz
- **Kanıt:** `arastir-ogren/scripts/arastir.py:47` `OPENCODE_PERMISSIONS`, `arastir-ogren/scripts/arastir.py:406-427` `opencode_config` (`tools: {"*": false}`), `arastir-ogren/scripts/arastir.py:436` bu yapılandırmayı `OPENCODE_CONFIG_CONTENT` env'iyle çocuğa geçirir. "Yalnız `websearch` + `oku_*` araçları görünür", "bash/write/webfetch kapalı" iddiaları OpenCode'un bu JSON anahtarını gerçekten uygulamasına bağlı. README.md:143 bir güvenlik önlemini tarif ediyor; canlı ölçüm iddiası taşımıyor. OpenCode izinlerinin çalışma anında uygulanıp uygulanmadığı bu statik incelemede doğrulanamadı.
- **Etki:** En kritik güvenlik sözü (ele geçirilmiş çalışanın komut çalıştıramaması) kaynak koddan tek başına doğrulanamıyor; Quoteproof çalışanını sabitlenmiş bir OpenCode sürümünde yoklamak gerekir.
- **Öneri:** Bir "canlı OpenCode yoklama" testi ya da en azından sürüm-sabitli bir dokümante doğrulama adımı ekle; hangi OpenCode sürümünün hangi ayarı desteklediğini kaydet.

## 4. İlk 3 iş için yol haritası

1. **Kapsama doğruluğu (R1):** `arastir-ogren/scripts/kapsama.py`'yi `dogrulama.json` kararlarına bağla; "Erişilemedi/Kanıt yok" maddeleri olgu kapsamasına sayma. Test ekle: kısmen/erişilemedi bir madde olgu kapsamasına **girmesin**.
2. **PDF sayfa sınırı (R2):** `arastir-ogren/scripts/oku.py:735` `-l 60`'ı kaldır/parametrele; >60 sayfada davranışı dokümante et ve bir testle sabitle.
3. **Gizli maskeleme (R4):** `redact`'i not yazma yoluna da uygula ve yapılandırılmış anahtar değerini tüm çıktılarda karart; regression testi ekle.

(R3 ve R6 daha derin güvenlik/güven çalışması ister; R1-R2 doğru ölçüm, R4 veri koruması bakımından öncelikli ve maliyeti düşüktür.)

## 5. Denetimin sınırları

- **Salt statik okuma:** Testler çalıştırılmadı; R5'teki sayı farkı statik sayımdır, çalışma anı davranışı değildir. Bu nedenle "219/235 test geçer" türünde bir iddia **doğrulanamadı**.
- **Ağ erişimi yok:** `arastir-ogren/scripts/oku.py`'nin SSRF/robots/DNS davranışı, README'deki "9/9 alıntı bulundu" (docs/fact-check) ve canlı deneme rakamları canlı doğrulanamadı; yalnız koddaki eşleşme mantığı ve depo içi fact-check kayıtları okundu.
- **OpenCode davranışı (R6) ve komut satırı arka uçları** harici çalışma ortamlarına bağlı; bu ortamlar olmadan teyit edilemez.
- **Güvenlik incelemeleri** ("iki bağımsız LLM destekli inceleme", README.md:153) depoda yalnız sonuç olarak anlatılıyor; inceleme raporlarının kendisi bu kopyada yok, dolayısıyla içeriği doğrulanamadı.
- `.env`/anahtar dosyaları ve `quoteproof.example.json` şablonları açılmadı; bunların içeriği bu incelemenin kapsamı dışındaydı.
