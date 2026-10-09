# Quoteproof — 429/304 yeniden ölçüm

9 Ekim 2026. Aynı DeepSeek `dsk` modeli, OpenCode arka ucu, resmî RFC kaynakları ve kapalı web aramasıyla yapılan tek vaka tekrarıdır. Önceki deneyin ayrıntıları git dışında tutulan `arastirma/2026-10-09-ham-ve-quoteproof-karsilastirmasi/KARSILASTIRMA.md` dosyasındadır. Yeni hafif kip 9 adımlı ve MCP okuyucu çağrısı soru sayısına göre sınırlıdır; eski koşu 12 adımdı. Bu nedenle farkı yalnız bir ayara bağlamak mümkün değildir.

| Konu | Eski Quoteproof | Yeni ilk koşu | Son kanıt durumu |
|---|---:|---:|---|
| 429 / Retry-After | 66 sn; 17.295 girdi / 3.061 çıktı; not var | 60 sn; 19.556 girdi / 3.270 çıktı; 2 okuma; tek deneme | 18/18 alıntı; 6/6 plan olgusu |
| 304 / önbellek | 240 sn zaman aşımı; 114.291 girdi / 3.348 çıktı; not yok | 115 sn; 31.279 girdi / 6.755 çıktı; 4 okuma; tek deneme | 15/15 alıntı; **sıkı kapsam 5/6** |

İki ilk işçi toplamı: **175 işçi saniyesi**, 50.835 girdi ve 10.025 çıktı tokenı; 2/2 nihai not. Eski toplam 306 işçi saniyesi, 131.586 girdi ve 6.409 çıktı tokenıydı; 1/2 not. Paralel yürütmede işçi süreleri duvar saati olarak toplanmamalıdır. Yeni koşu daha çok çıktı tokenı kullandı.

## Kapsama kör noktası ve okuyucu düzeltmesi

İlk `kapsama.py` raporu 304 için 6/6 dedi. Planın dördüncü regex'i `Content-Location.*Date.*ETag.*Vary|Cache-Control.*Expires` idi; ikinci seçenek tek başına eşleşince dört alan eksik olduğu hâlde olgu tam sayıldı. Ölçüm planında yalnız dört alanı birlikte isteyen kalıp kullanıldığında sonuç **5/6** oldu. Bu, regex kapsamasının anlam doğruluğu olmadığını somut olarak gösterir.

[RFC 9110 §15.4.5](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.4.5) bu dört alanı kısa ve tamamen bağlantılardan oluşan bir liste öğesinde veriyor. `oku.py` bunu menü gürültüsü sanıp atmıştı: ham blok 39 karakter, 29 bağlantı karakteri, `ana=False`. İki noktayla biten içerik cümlesini izleyen liste öğelerini koruyacak düzeltme yapıldı. Gerçek RFC HTML çıkarımında iki zorunlu alan listesi artık var; çevrimdışı regresyon testi de eklendi.

Eksik olgu için iki hedefli deneme yapıldı:

| Hedefli koşu | Süre | Girdi / çıktı | Sonuç |
|---|---:|---:|---|
| Eski okuyucuyla | 70 sn | 17.707 / 3.937 | 6/6 alıntı bulundu; dört alan listesi hâlâ yok, hedef olgu 0/1 |
| Düzeltilmiş okuyucuyla | 37 sn | 17.496 / 2.331 | 7/7 alıntı bulundu; `Content-Location, Date, ETag, Vary` listesi bulundu, hedef olgu 1/1 |

İlk 304 notu ve son hedefli notun doğrulanmış bulgularının **birleşiminde** sıkı kapsama 6/6 oldu. Hedefli plan oluşturucu iki URL'ye kısıtlı plan için yanlışlıkla `min_url: 3` yazdığı için iki hedefli CLI komutu `73` (zayıf not) ile döndü; her iki işçi `ok: true` ve alıntı doğrulaması başarılıydı. Oluşturucu artık plandaki `min_url_required: 2` değerini koruyor. Bu düzeltme sonrası aynı canlı komut tekrar çalıştırılmadı.

## Kapılar ve sınırlar

- Her iki ana notta plan sorusu başına dört bölüm var. Denetim iki resmî belgeyi tek alan adı kusuru diye göstermiyor; aynı yayımlayıcıdan bağımsız teyit gelmediğini açıkça yazıyor.
- İki ana notun 33/33 alıntısı sayfada bulundu. Hedefli okuyucu düzeltmesi sonrası 7/7 alıntı bulundu. Bunlar metinsel doğrulamalardır; yorumun doğru olduğunu tek başlarına kanıtlamaz.
- İlk 304 notu, dört alanı kaçırıp tam listenin ilgili bölümde bulunmadığını yanlış söyledi. Koordinatör bunu kaynak ve sıkı kapsama ile yakaladı. O not nihai rapor olarak kullanılmadı.
- Hedefli notun Çıkarımlar/Boşluklar bölümünde açıklama amaçlı Türkçe tırnaklar var; `rapor_kontrol.py --siki` 4 uyarı verdi. Araştırmacı istemi, tırnak içini birebir kaynak alıntısına ayıracak biçimde sıkılaştırıldı. Hedefli not da doğrudan yayımlanmadı.
- Düzeltilmiş bulgulardan oluşturulan `arastirma/2026-10-09-f06-yeniden-olcum/SONUC-RAPORU.md` için `rapor_kontrol.py --siki` sonucu **0 hata, 0 uyarı, 0 bilgi**. Sonuç raporu kullanıcıya sunulan sentezdir; ham notların otomatik aklanması değildir.
- Son kod durumunda `test_arastir.py` **235/235**, `test_oku.py` **56/56** geçti; `git diff --check` temiz.

Ölçüm dosyaları `arastirma/2026-10-09-f06-yeniden-olcum/` ve `arastirma/2026-10-09-f06-eksik-alanlar-okuyucu-duzeldi/` altında git dışında tutuluyor. Tek tekrar üzerinden genel hız, maliyet veya doğruluk garantisi çıkarılamaz.
