# Ölçümler (8 Eki 2026)

Tarihli deney sonuçları; ajan seçimi (tek ajan mı, çok çalışanlı hat mı) ya da sentez sınırı kararında oku.

## Ajan seçimi — iki yol (ölçüldü, 8 Eki 2026: askeri İHA, aynı brief, aynı rapor biçimi)

| | **Tek ajan + canlı web araması** (bir güçlü model, tek çağrı) | **Çok çalışanlı hat** (`arastir.py` → doğrulama → sentez; ucuz modeller) |
|---|---|---|
| Süre | **134 sn** (577k girdi / 13k çıktı jetonu) | 348 sn araştırma + 580 sn sentez = ~930 sn |
| Çıktı | 3.986 sözcük, 8/8 başlık, 11 yenilik satırı, **30 URL** (14'ü resmî) | 5.562 sözcük (kesik), 91 tablo satırı, **98 URL** (çoğu sektör basını; 12'si resmî) |
| Güçlü yan | iddiaları "üretici beyanı/bağımsız doğrulanmadı" diye dürüstçe etiketler; birincil kaynağa yaslanır; tek elden tutarlı rapor | geniş kapsam, sayısal bütçe/adet, çelişkileri tek tek listeler, çok kaynaklı |
| Zayıf yan | **büyük bir gelişmeyi atladı** (üretim sözleşmesi, resmî kaynakta Haz 2026); az kaynak, sektör basını ile çapraz teyit yok; bazı ülkeler "veri sınırlı" | 2 çalışan çöktü (plan metni / arama 429) → birincil belgeler eksik; tek çağrılık sentez çıktı sınırında KESİLDİ |
| Ne zaman | hızlı, resmî-kaynak ağırlıklı özet; ilk tur | geniş tarama, rakam/ihracat/bütçe, çok ülke |

**Önerilen hat (karma):** çalışanlar genişliği toplar → `dogrula.py` (tümü) → `notlar-temiz` → sentez (güçlü bir model, bölüm bölüm) → Claude kritik iddiaları açar. Tek ajan modunu "ikinci görüş / boşluk avı" için de kullan: çalışan notlarında olmayan resmî kaynakları bulur. İki rapor çelişirse (örn. "yalnız test" ↔ "üretim sözleşmesi") birincil kaynağı aç; ikisi de doğru olabilir, biri eksik olabilir. Karşılaştırmak için `references/ortak-brief-sablonu.md` ve `rapor_olc.py`.

**Sentez sınırları (ölçüldü):** ölçülen bir model/araç tek çağrıda ~32 bin jetondan uzun çıktı veremedi ve ~80 KB girdide takıldı (çıktı KESİLDİ ama başarı kodu döndü). Beş bin sözcükten uzun raporu **tek çağrıda** yazdırma: bölümlere ayır (1-2 / 3 / 4-5 / 6-8) ve birleştir. "Çıktı model sınırında kesildi" türü bir uyarı görürsen o çıktıyı tam sayma.
