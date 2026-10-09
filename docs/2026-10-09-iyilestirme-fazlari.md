# Quoteproof — dört soruna yönelik iyileştirme fazları

Bu dosya `YOL_HARITASI.md` değildir. Depoda henüz bir tur defteri olmadığı için
birleştirmeye hazır, ayrı faz adayıdır. Başlangıç kanıtı:
`arastirma/2026-10-09-ham-ve-quoteproof-karsilastirmasi/KARSILASTIRMA.md`
(deney çıktısı git dışında tutuluyor). İki konu, tek koşu: süre ve maliyet için
genel sonuç çıkarılamaz.

## Değişmez sınırlar

- Doğrulama kaynak metnine dayanır; ikinci bir LLM hakem olarak eklenmez.
- Ağdan gelen içerik düşmanca girdidir; SSRF, yönlendirme, boyut ve süre sınırları korunur.
- `Doğrulandı` yalnız alıntının sayfada bulunduğunu ifade eder.
- Başarısız veya yarım model metni doğrulanmış araştırma notu sayılmaz.

## [x] F01 · İşçi akışının adım başına maliyet profilini kaydet
- amac: Başarıda ve zaman aşımında her model adımının araç sayısı, bitiş nedeni ve token dağılımı içerik/sır saklamadan `calisma.json` içinde görülsün.
- dosyalar: `arastir-ogren/scripts/arastir.py`, `arastir-ogren/scripts/test_arastir.py`
- kabul: `python3 arastir-ogren/scripts/test_arastir.py` → en az 225 test, 0 hata; zaman aşımı testi de adım profilini korur ve profil toplamları mevcut toplamlarla eşleşir.
- bagimli: —
- sure: 25dk
- kaynak: [OpenCode adım sınırı](https://opencode.ai/docs/agents/) · [DeepSeek önbellek sayaçları](https://api-docs.deepseek.com/guides/kv_cache/) · `arastir.py:236-282,392-413`
- kanit: 2026-10-09 · `python3 arastir-ogren/scripts/test_arastir.py` → 226/226 geçti; başarılı, kesilen ve zaman aşımı akışları için adım profili testleri eklendi.

Atomik işler:
1. JSON olaylarından yalnız sayısal adım profili çıkar; araç girdisi ve sayfa metnini tutma.
2. Profili başarılı/zaman aşımı/hata denemesinde sonuç dosyasına geçir.
3. Çevrimdışı başarılı ve kesilen akış örnekleriyle doğrula.

## [x] F02 · 304 vakasını ölç ve güvenilir sonlandırma tasarla
- amac: İşçi, araç bütçesinin sonunda elindeki kanıtla not yazabilsin; kanıt yoksa boşluğu açıkça belirtebilsin.
- dosyalar: `arastir-ogren/scripts/arastir.py`, `arastir-ogren/references/arastirmaci-istemi.md`, `arastir-ogren/scripts/test_arastir.py`
- kabul: `python3 arastir-ogren/scripts/test_arastir.py` → 0 hata; iki RFC'li 304 tekrarında `calisma.json` içinde `ok: true`, `kapsama.py` en az 5/6 olgu ve açık yazılmış boşluklar, `dogrula.py` 0 bulunamayan alıntı; süre ve tokenlar önceki 240 sn / 114291 girdi değerleriyle ayrıca raporlanır.
- bagimli: F01
- sure: 30dk
- kaynak: [OpenCode `steps` davranışı](https://opencode.ai/docs/agents/) · [DeepSeek bağlam önbelleği](https://api-docs.deepseek.com/guides/kv_cache/) · `arastir.py:160-185,370-413`
- kanit: 2026-10-09 · iki RFC'li tek tekrar: 304 işçisi tek denemede `ok: true`, 115 sn, 31.279 girdi / 6.755 çıktı tokenı, 4 okuyucu çağrısı; 15/15 alıntı kaynakta bulundu. Önceki koşu 240 sn, 114.291 girdi ve not yoktu. İlk kapsama regex'i 6/6 verdi; zorunlu başlık listesini kaçırdığı elle bulunup regex sıkılaştırıldı. Sıkı kapsam 5/6; okuyucunun kısa bağlantılı RFC liste öğesini düşürdüğü saptanıp düzeltildi. Hedefli ikinci koşu ile birleşim 6/6 oldu.

ÖN KOŞUL: canlı model erişimi; yoksa çevrimdışı kapı ölçülür, vaka ölçümü bekler.

Atomik işler:
1. F01 profilinden araçların nerede yoğunlaştığını ve bitiş nedenini belirle.
2. Okuma bütçesi ile son cevap için ayrılmış aşamayı ayır; `steps` değerini araç sayacı gibi sunma. OpenCode `run --session` devamı büyük bağlamı yeniden taşıyabilir; önce aynı oturumun sınır davranışını, gerekirse kısa kanıt paketli yeni çağrıyı ölç.
3. Nihai metin oluşmadığında ara düşünceyi not olarak kabul etme.

## [x] F03 · Dört bölümlü not sözleşmesini işçi kapısına bağla
- amac: Her plan sorusunun dört alt bölümü yoksa veya ek `##` bölüm soru gibi ayrıştırılıyorsa `ok: true` yazılmasın.
- dosyalar: `arastir-ogren/scripts/arastir.py`, `arastir-ogren/scripts/denetle.py`, `arastir-ogren/scripts/test_arastir.py`
- kabul: `python3 arastir-ogren/scripts/test_arastir.py` → 0 hata; üç sorulu temiz not kabul, eksik bölüm ve fazladan `## Notlar` örneklerinin ikisi de red; `denetle.py` ile sözleşme kapısı aynı bölüm sayısını üretir.
- bagimli: —
- sure: 25dk
- kaynak: [CommonMark ATX başlıkları](https://spec.commonmark.org/0.31.2/#atx-headings) · `arastir.py:299-310,506-529` · `denetle.py:58-86`
- kanit: 2026-10-09 · `python3 arastir-ogren/scripts/test_arastir.py` → 230/230 geçti; işçi, denetçi ve `--devam` aynı bölüm ayrıştırıcısını kullanıyor. Üç sorulu temiz not kabul, eksik bölüm ve ek `##` başlık reddi ölçüldü.

Atomik işler:
1. Bölüm ayrıştırmasını paylaş ve plan soru sayısını kapıya geçir.
2. Eski kısa notları sessizce başarılı saymadan test fikstürlerini güncelle.
3. Biçim hatasını doğrulama hatasından ayrı raporla.

## [x] F04 · Ham ve becerili raporlarda birebir alıntı kapısını zorunlu kıl
- amac: Çeviri veya özetin tırnak içinde kaynak alıntısı diye yayımlanması engellensin; kapsama eksiği ayrı görülsün.
- dosyalar: `arastir-ogren/SKILL.md`, `arastir-ogren/scripts/rapor_kontrol.py`, `arastir-ogren/scripts/test_arastir.py`
- kabul: `python3 arastir-ogren/scripts/test_arastir.py` → 0 hata; tırnaklı Türkçe çeviri için `rapor_kontrol.py --siki` çıkış kodu 1, özgün dilde kaynakta bulunan alıntı için 0; atıf URL'si olmayan ham cevap 0 hata/0 uyarı ile yayımlanamaz.
- bagimli: F03
- sure: 25dk
- kaynak: `rapor_kontrol.py:1-30,308+` · `kapsama.py:1-25` · [RFC 9110 §15.4.5](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.4.5)
- kanit: 2026-10-09 · `test_arastir.py` 235/235 geçti; birebir alıntı, tırnaklı çeviri, okunamayan kaynak ve URL'siz rapor kapıları sınandı. Skill, `rapor_kontrol.py --siki` çalıştırılmasını istiyor.

Atomik işler:
1. Nihai rapor kontrolünü kullanıcı akışındaki yayın kapısı olarak açık yaz.
2. Çeviri için tırnaksız/parafraz etiketli sunumu örnekle.
3. Sıfır uyarının anlamsal doğruluk garantisi olmadığını koru.

## [x] F05 · Alan adı çeşitliliğini plan kısıtıyla yorumla
- amac: Tek resmî yayımlayıcıya bilinçli kısıtlanan planda iki farklı belgeyi düşük değerli tek alan adı uyarısıyla cezalandırma.
- dosyalar: `arastir-ogren/scripts/denetle.py`, `arastir-ogren/scripts/arastir.py`, `arastir-ogren/scripts/test_arastir.py`
- kabul: `python3 arastir-ogren/scripts/test_arastir.py` → 0 hata; tek yayımlayıcı açıkça beklenen planda iki URL için 0 çeşitlilik uyarısı ve 1 açıklayıcı bilgi; açık uçlu tek alan adı örneğinde 1 uyarı.
- bagimli: —
- sure: 25dk
- kaynak: `denetle.py:251-265,304-331` · `guven.py:1-20` · [RFC Editor](https://www.rfc-editor.org/)
- kanit: 2026-10-09 · `test_arastir.py` 235/235 geçti; `single_publisher_host` ile iki RFC belgesi açıklayıcı bilgi, açık uçlu/yanlış alan/tek belge uyarı üretti.

Atomik işler:
1. Serbest metinden niyet tahmini yerine isteğe bağlı yapılandırılmış plan alanı tanımla.
2. Farklı belge sayısını ve farklı alan adı sayısını ayrı göster.
3. Açık uçlu araştırmalarda mevcut uyarıyı koru.

## [x] F06 · Dört düzeltmeyi sabit iki vakada yeniden ölç
- amac: 429 ve 304 sonuçlarını aynı kaynak/model koşullarında önceki ölçümle kıyasla; başarı, kapsam, süre, token ve yanlış alarmı ayrı raporla.
- dosyalar: `docs/2026-10-09-iyilestirme-fazlari.md`, `arastirma/` altında yeni, git dışı deney çıktısı
- kabul: iki vakada 2/2 işçi nihai notu, her notta plan sorusu başına 4/4 bölüm, doğrulanmış notlarda `kapsama.py` 6/6 olgu ve `rapor_kontrol.py --siki` 0 hata/uyarı; 304 süresi ve girdi tokenı sayısal olarak eski 240 sn / 114291 ile yan yana gösterilir.
- bagimli: F02, F03, F04, F05
- sure: 30dk
- kaynak: `arastirma/2026-10-09-ham-ve-quoteproof-karsilastirmasi/KARSILASTIRMA.md` · [DeepSeek token kullanım alanları](https://api-docs.deepseek.com/api/create-chat-completion/)
- kanit: 2026-10-09 · iki ana işçi 2/2 not; her soruda 4/4 bölüm; toplam 33/33 alıntı kaynakta bulundu. 429 kapsamı 6/6, 304 sıkı kapsamı ilk koşuda 5/6 ve okuyucu düzeltmesi sonrası hedefli notla birleşimde 6/6. `SONUC-RAPORU.md` için `rapor_kontrol.py --siki` 0 hata/0 uyarı/0 bilgi. Ölçüler ve sınırlamalar: [yeniden ölçüm](2026-10-09-yeniden-olcum.md).

ÖN KOŞUL: canlı model erişimi.

Atomik işler:
1. Aynı `PLAN.json` ve iki RFC kaynak kümesini kullan.
2. Ham ve becerili kolları ayrı ayrı denetle; doğrulanan alıntıyı anlamsal doğruluk sayma.
3. Yeni ölçümü tek koşu olarak etiketle, genelleme yapma.
