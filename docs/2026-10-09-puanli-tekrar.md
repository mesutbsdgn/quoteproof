# Ham yanıt ve Quoteproof — puanlı tekrar

Tarih: 9 Ekim 2026. Aynı 429 ve 304 vakaları bir kez daha ölçüldü. Her iki kolda DeepSeek `dsk`, OpenCode, aynı iki RFC Editor kaynağı ve kapalı web araması kullanıldı. Ham kol Quoteproof'un araştırma şablonu, çıktı kapısı ve otomatik denetimleri olmadan çalıştı; iki kol da aynı güvenli MCP okuyucusuna erişti.

## Puanlama

Her başlık 0–5 puan; toplam ağırlıklı puan 100 üzerinden hesaplandı.

| Ölçüt | Ağırlık | Uygulanan ölçü |
|---|---:|---|
| Beklenen olguların kapsamı | %30 | 0/6=0; 1/6=1; 2/6=2; 3–4/6=3; 5/6=4; 6/6=5 |
| Birebir alıntı doğruluğu | %30 | Bulunan / toplam: alıntı yok veya <%20=0; %20–39=1; %40–59=2; %60–79=3; %80–99=4; %100=5 |
| Çıktı sözleşmesi | %15 | 0=yapı yok; 1=genel metin; 2=sorular var, dört bölüm yok; 3=soruların yarısı dört bölümle tam; 4=tüm sorular dört bölümle tam, küçük biçim kusuru; 5=tüm sorular dört bölümle tam ve ek/eksik başlık yok |
| Sıkı rapor denetimi | %15 | `rapor_kontrol.py --siki`: 0=okunamayan kaynak/ciddi hata; 1=4+ uyarı; 2=2–3 uyarı; 3=1 uyarı; 4=uyarı yok, bilgi var; 5=0 hata/uyarı/bilgi |
| Verim | %10 | Süre ve girdi tokenı: >240 sn veya >120k/no note=0; ≤240 sn/≤120k=1; ≤180 sn/≤80k=2; ≤120 sn/≤50k=3; ≤90 sn/≤30k=4; ≤60 sn/≤20k=5 |

Ham kol standart `Alıntılı bulgular` bölümlerini üretmediğinden `kapsama.py` onu biçim gereği 0/6 sayar. İçerik karşılaştırmasını aynı altı planlı olguyu ham notun kaynak alıntılarında elle arayarak yaptım; bu yöntem ve yapı puanı ayrı tutuldu. Ham kolun alıntı sayımı, blok alıntıları aynı kaynak önbelleğinde normalleştirip arayarak yapıldı. Her faz/kol tek tekrar olduğu için puanlar istatistiksel genelleme değildir.

## Sonuç puanları

| Kol / konu | Olgu kapsamı /30 | Alıntı /30 | Sözleşme /15 | Denetim /15 | Verim /10 | Toplam /100 |
|---|---:|---:|---:|---:|---:|---:|
| Ham · 429 | 5 (30) | 5 (30) | 2 (6) | 3 (9) | 4 (8) | **83** |
| Quoteproof · 429 | 4 (24) | 5 (30) | 5 (15) | 4 (12) | 5 (10) | **91** |
| Ham · 304 | 5 (30) | 5 (30) | 2 (6) | 3 (9) | 3 (6) | **81** |
| Quoteproof · 304 | 5 (30) | 5 (30) | 5 (15) | 2 (6) | 3 (6) | **87** |
| **Ortalama** |  |  |  |  |  | **Ham 82 · Quoteproof 89** |

## Ölçülen ham veriler

| Konu | Kol | Süre | Girdi / çıktı tokenı | Okuyucu çağrısı | Kapsam | Kaynakta bulunan alıntı | Sıkı denetim |
|---|---|---:|---:|---:|---:|---:|---|
| 429 | Ham | 41 sn | 27.562 / 3.345 | 4 | 6/6 | 14/14 | 1 uyarı, 23 bilgi |
| 429 | Quoteproof | 47 sn | 18.085 / 4.522 | 2 | 5/6 | 16/16 | 0 uyarı, 13 bilgi |
| 304 | Ham | 43 sn | 44.086 / 3.985 | 5 | 6/6 | 18/18 | 1 uyarı, 14 bilgi |
| 304 | Quoteproof | 40 sn | 31.793 / 3.928 | 4 | 6/6 | 14/14 | 2 uyarı, 2 bilgi |

Toplam girdi ham kolda 71.648, Quoteproof kolunda 49.878 token oldu; Quoteproof bu tek ölçümde girdiyi %30,4 azalttı. Çıktı tokenı 7.330'dan 8.450'ye yükseldi (%15,3). Süreler konu başına işçi süresidir; Quoteproof iki işçiyi paralel, ham kolu paylaşılan OpenCode veritabanında kilit riskini azaltmak için sırayla çalıştırdım. Bu yüzden süre toplamları duvar saati karşılaştırması değildir.

## Değerlendirme

- Quoteproof ortalama 7 puan önde. Farkı dört bölümlü sözleşme ve daha düşük girdi maliyeti taşıdı.
- Ham yanıt iki konuda da altı olguyu yakaladı. Quoteproof'un 429 notunda RFC 6585'in kullanıcıyı tanımlama ve istek sayma yöntemini belirlemediği bilgisi eksik kaldı; kapsam 5/6 oldu.
- Quoteproof alıntılarının tümü bu koşuda sayfada bulundu. Ham kolun doğrudan alıntıları da kaynakta bulundu; ancak her ham raporda denetçi, kaynakta olmayan bir bölüm başlığı ifadesini tırnak içinde bulup uyardı.
- Quoteproof 304 notunda iki Türkçe açıklama tırnak içinde kaldığı için sıkı denetim uyarı verdi. Bunlar alıntılı bulgular değil, çıkarım cümlelerindeki tırnaklardı; yine de `--siki` kapısından geçmediler.
- Kapsama ve alıntı doğrulaması metinsel ölçüdür. Kaynakta bulunan alıntı, iddianın doğru yorumlandığını tek başına kanıtlamaz.

## Ham koşu dosyaları

Tekrarın planı, ham notları, Quoteproof notlarını, süre/token kayıtlarını ve denetim raporlarını git dışında tutulan `arastirma/2026-10-09-puanli-tekrar/` dizinine yazdım.
