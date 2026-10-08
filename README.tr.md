<p align="center">
  <img src="assets/logo.svg" alt="Quoteproof" width="520">
</p>

<p align="center">
  <b>Yapay zekâ ajanları için kanıt öncelikli araştırma becerisi.</b><br>
  Aramayı ucuz modeller paralel yürütür. Bir bulguya, alıntısı gösterdiği sayfada düz bir Python betiğiyle bulunana kadar güvenilmez.
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.tr.md">Türkçe</a>
  &nbsp;|&nbsp;
  <img alt="lisans" src="https://img.shields.io/badge/lisans-MIT-blue">
  <img alt="python" src="https://img.shields.io/badge/python-3.9%2B-informational">
  <img alt="bağımlılık" src="https://img.shields.io/badge/ba%C4%9F%C4%B1ml%C4%B1l%C4%B1k-yok-success">
</p>

---

## 30 saniyede

Yapay zekâ araştırma ajanları hızlı ve akıcı yazar, ama **alıntı uydurur**. Alışılmış çözüm, ilk modelin işini ikinci bir LLM'e kontrol ettirmektir. Bu yöntem yavaştır, jeton harcar ve çoğu zaman ilk modelle aynı yerlerde yanılır.

Quoteproof bulgunun kendisini denetlenebilir kılar. Çalışanın yazdığı her bulgu, **sayfanın özgün dilinde kelimesi kelimesine bir alıntı ve bir URL** içermek zorundadır. **Hiç LLM jetonu harcamayan** bir betik, gösterilen her sayfayı açıp bu metni arar.

```text
Çalışanın yazdığı (örnek amaçlı)                         Quoteproof ne der
─────────────────────────────────────────────────────    ──────────────────────────────────────────
"uv is 100x faster than pip"        — docs.example.org    ✗ Bulunamadı  alıntı o sayfada yok
"10-100x faster than pip"           — github.com/…/uv     ✓ Doğrulandı  gösterilen sayfada bulundu
"kimsenin bulamayacağı bir parafraz" — blog.example.com   ✗ Bulunamadı  parafraz doğrulanamaz
```

Yalnızca bu denetimi geçen bulgular, son inceleme ve raporun yazımı için koordinatör modele gider.

> **Yazarın kendi koşularında ölçüldü:** Birebir alıntı şartı, otomatik doğrulanabilen bulguların oranını **14 bulgudan 3'ünden, 15 bulgudan yaklaşık 14'üne** çıkardı. Denetleyicide sonradan yapılan düzeltmeler, gerçek bir koşuda doğrulanan bulguları **21'de 7'den 21'de 19'a** yükseltti. Geri kalanlar, bir insanın bakması gerektiği için doğru biçimde işaretlenen meşru parafrazlardı.

## Fikir

| | Adım | Kim yapar | Maliyet |
|---|---|---|---|
| 1 | **Plan**: soruyu konulara böl | koordinatör model | tek çağrı |
| 2 | **Araştırma**: ara, oku, notu sabit biçimde yaz | ucuz çalışanlar, paralel | ucuz |
| 3 | **Denetim**: biçim, ölü bağlantı, depo etkinliği, kaynak güveni | Python | 0 jeton |
| 4 | **Doğrulama**: her alıntı, rakam ve sürüm gerçekten sayfada mı? | Python | 0 jeton |
| 5 | **İnceleme ve yazım**: anlamı kontrol et, raporu yaz | koordinatör model | birkaç çağrı |

Farkı yaratan tek kural şu: **özgün dilde, birebir alıntıla; yapamıyorsan alıntılama.** Çevrilmiş bir "alıntı" sayfada hiçbir zaman bulunamaz, dolayısıyla denetimi de geçemez.

## Nasıl çalışır

```mermaid
flowchart LR
    A[PLAN.json<br/>konular + sorular] --> B[arastir.py<br/>paralel çalışanlar]
    B -->|notlar/*.md<br/>alıntı + URL| C[denetle.py<br/>biçim · bağlantı · depo · kaynak güveni]
    C --> D[dogrula.py<br/>alıntı sayfada mı?]
    D -->|Doğrulandı / Kısmen /<br/>Bulunamadı / Erişilemedi| E[Koordinatör<br/>kontrol · rapor]
    B -. sayfaları bununla okur .-> F[oku.py<br/>güvenli, sıkıştırılmış okuyucu]
    D -. sayfaları bununla okur .-> F
```

### Bir çalışanın yazdığı not

Çalışanlar notu tek bir sabit biçimde yazmak zorundadır. Bölüm adları, araçlar bunları ayrıştırdığı için Türkçedir; içerik herhangi bir dilde olabilir.

```markdown
## uv'nin hızı resmî dokümanda nasıl anlatılıyor?
### Özet
Ana çıkarımı veren bir iki cümle.
### Alıntılı bulgular
- uv, pip'in 10–100 katı hız vaat ediyor — "10-100x faster than pip" — [uv README](https://github.com/astral-sh/uv) (2026-10, birincil)
### Çıkarımlar
- Çalışanın kendi çıkarımı (bulgulardan açıkça ayrı).
### Boşluklar
- Bulamadığı şey ve nedeni.
```

Her bulgu satırında dört öğe bulunur: **iddia**, **birebir alıntı**, **bulgunun kendi URL'si** ve tarihle birlikte kaynağın birincil (`birincil`) mi ikincil (`ikincil`) mi olduğunu gösteren bir etiket.

### Kararlar ne anlama gelir

| Karar | Anlamı | Ne yapmalı |
|---|---|---|
| **Doğrulandı** | Her alıntı, rakam, sürüm ve kod parçası gösterilen sayfada bulundu. | Önemli iddialarda *anlamı* yine de kendiniz kontrol edin. |
| **Kısmen** | Kanıtın bir kısmı bulundu ya da yalnızca tek bir zayıf öğe (tek başına bir rakam) eşleşti. | Sayfayı açıp bağlama bakın. |
| **Bulunamadı** | Kanıtın çoğu bulunamadı: alıntı uydurulmuş, çevrilmiş ya da başka bir sayfadan alınmış olabilir. | Kullanmayın. `--temiz-yaz`, bunlar çıkarılmış temiz bir not kopyası yazar. |
| **Erişilemedi** | Sayfa okunamadı: robots.txt engeli, JavaScript gerekliliği, zaman aşımı. | Kendiniz açın ya da ikinci bir kaynak bulun. |
| **Kanıt yok** | Bulguda aranacak alıntı ya da rakam yok. | Elle inceleyin. |

*Doğrulandı*, **alıntılanan metnin gösterilen sayfada bulunduğu** anlamına gelir; sayfanın doğru olduğunu göstermez. Bunun için güven puanına, ikinci bir kaynağa ve kendi kontrolünüze başvurun.

### İçinde ne var

| Betik | Görevi | Maliyet |
|---|---|---|
| `arastir.py` | Çalışanları paralel çalıştırır, başarısız olanı yeniden dener, gerekirse başka arka uca geçer, `notlar/<slug>.md` dosyalarını yazar, ardından denetim ve doğrulamayı çalıştırır | ucuz model |
| `denetle.py` | Notları denetler: biçim, bağlantının çalışıp çalışmadığı, GitHub deposunun var olup olmadığı ve etkinliği, **kaynak güveni**. Elle bakılmaya değer iddiaları seçer | 0 jeton |
| `dogrula.py` | Her alıntıyı, rakamı, sürümü ve kod parçasını gösterilen sayfada arar, karar verir | 0 jeton |
| `oku.py` | Sayfa okuyucu: yalnızca ana içeriği alır, BM25 ile pasaj seçer (tam sayfaya göre yaklaşık 20–40 kat az jeton), PDF ve GitHub README dosyalarını tanır | 0 jeton |
| `mcp_oku.py` | Okuyucuyu çalışanlara küçük bir MCP sunucusu olarak sunar | 0 jeton |
| `guven.py` | 0–100 arası sezgisel kaynak güvenilirlik puanı | 0 jeton |
| `rapor_kontrol.py` | **Son raporu**, kaynak gösterdiği sayfalarla karşılaştırır: yanlış özneye bağlanmış sayıları, birebir olmayan alıntıları ve araştırma notlarında hiç geçmeyen kaynakları yakalar | 0 jeton |
| `rapor_olc.py` | İki raporu aynı ölçütlerle ölçer (sözcük, başlık, kaynak, boşluk) | 0 jeton |

## Özellikler, açıklamalı

- **Birebir alıntı sözleşmesi.** Denetlenebilir alıntısı olmayan bulgu rapora giremez. "Model öyle diyor" ile "sayfa öyle diyor" arasındaki farkı bu tek kural yaratır.
- **Örnekleme yok, her bulgu denetlenir.** Rapor kendi kapsamını da bildirir (denenen, kanıtsız, atlanan); böylece boşluk gizlenemez.
- **Sınırları gözeten eşleşme.** `1.2`, `11.20` içinde aranırken bulunmaz; `values[0]` ile `values0` farklıdır; `v1.2.3`, `1.2.3` ile eşleşir. Sayı biçimleri uzlaştırılır (`%26,2` ↔ `26.2%`, `100.000` ↔ `100,000`). Alıntıdaki kasıtlı `...` ve editör eki `[the]` hoş görülür.
- **Bağlam kontrolü.** Sayı içeren iddialarda, iddia cümlesindeki ayırt edici bir terim, sayfada doğrulanan alıntının yakınında da geçmelidir. Geçmezse karar *Doğrulandı*'dan *Kısmen*'e düşer ve nedeni yazılır. Bu ucuz bir sezgidir (gerçek koşularda bulguların %1'inin çok altında), kanıt değildir.
- **Rapor düzeyinde kontrol.** Hatalar çoğunlukla *sentez* aşamasında doğar: not doğrudur, ama rapor sayıyı yanlış özneye bağlar. `rapor_kontrol.py`, bitmiş raporu öğe öğe (tablo satırı, madde, alıntı) kaynak gösterdiği sayfalarla yeniden karşılaştırır. Sezgiseldir: temiz çıktı raporun doğru olduğunu değil, bu hata türlerinin görülmediğini söyler.
- **Kaldığı yerden sürdürülebilen koşular.** `--devam`, bitmiş konuları yeniden kullanır (istemin özet değeri aynı olmalıdır). Her konudan sonra tek adımda (atomik) bir kontrol noktası yazılır; koşu yarıda kesilse bile kayıp olmaz.
- **Güvenli tarafta kalan çalışanlar.** Araştırma yapmak yerine onay isteyen, 3'ten az benzersiz URL gösteren ya da hiç arama veya okuma aracı çağırmayan çalışan reddedilir; sıradaki arka uç işi devralır.
- **Kaynak güven puanı** (*öncelik belirlemeye yarar, asla kanıt değildir*). Alan adının sınıfından başlar, sonra URL sinyalleriyle ayarlanır:

  | Sınıf | Puan | | Sinyal | Puan |
  |---|---:|---|---|---:|
  | Resmî / standart kurumu | 90 | | Planda adı geçen kaynak | +10 |
  | Güvenlik standardı (OWASP, MITRE, CVE, CERT) | 88 | | Düz `http` | −10 |
  | Akademik yayıncı | 85 | | Liste / SEO tarzı URL | −8 |
  | Resmî doküman | 80 | | Şüpheli TLD | −10 |
  | Ön baskı · haber | 70 | | IP adresli ana makine | −15 |
  | Kod deposu | 65 | | İzleme parametreleri | −3 |
  | Ansiklopedi | 60 | | | |
  | Topluluk / sosyal | 25–55 | | | |
  | Bilinmeyen | 50 | | | |

  Ayrıca şu uyarıları verir: *zayıf kaynak*, *"birincil" denmiş ama alan adı birincil değil*, *eski* (bildirilen tarih 18 aydan eski).
- **Saygılı okuyucu.** robots.txt kurallarına uyar, host başına hız sınırı uygular, `Crawl-delay` değerine uyar.

## Tasarımdan gelen güvenlik

Web sayfalarına düşmanca girdi gözüyle bakılır. Tasarım, bir sayfanın çalışana talimat vermeye *çalışacağını* baştan kabul eder.

| Tehdit | Tasarım ne yapar |
|---|---|
| Bir sayfa çalışana "önceki talimatları yok say" der | OpenCode çalışanlarına, **varsayılanı "yasak" olan bir araç izin listesi** verilir: yalnızca arama ve okuma. Ele geçirilmiş bir çalışan komut çalıştıramaz, yerel dosya okuyamaz, başka servisleri çağıramaz. Çekilen metin *veridir, talimat değildir* diye etiketlenir ve bilinen enjeksiyon kalıpları işaretlenir. |
| Okuyucu iç bir adrese yönlendirilir (SSRF) | Yalnızca `http(s)` ve yalnızca genel ağda yönlendirilebilen adresler kabul edilir. Loopback, özel, link-local, operatör tipi NAT (CGNAT) ve IPv4 eşlemeli IPv6 aralıkları engellenir. |
| DNS rebinding | DNS bir kez çözülür ve bağlantı **doğrulanan IP'ye sabitlenir** (Host/SNI korunur). |
| İç ağa çıkan yönlendirme | Her yönlendirme adımı yeniden doğrulanır ve robots.txt'ye karşı yeniden denetlenir. Proxy kullanılmaz. |
| Çok büyük ya da kasten yavaş yanıtlar | Boyut sınırı (2 MB; PDF için 10 MB) ve DNS, yönlendirme ve gövdeyi kapsayan **toplam** süre sınırı. |
| Saygısız tarama | Her içerik isteğinde robots.txt (RFC 9309), host başına hız sınırı ve `Crawl-delay` uygulanır. Çalışanlar bunu kapatamaz. |
| Kötü niyetli bir robots.txt dosyası | Eşleştirici regex kullanmaz (ReDoS yok); kural sayısı, desen uzunluğu ve dosya boyutu sınırlıdır. |
| Günlüklere ya da alt süreçlere sızan sırlar | OpenCode ve MCP alt süreçlerine yalnızca izin verilen ortam değişkenleri (ve yapılandırılmış anahtar) geçer; hata metinlerindeki bazı anahtar benzeri değerler maskelenir. Kapsamı dardır, bkz. [Sınırlar](#sınırlar). |
| Zehirlenmiş önbellek | Anahtarı URL ve çekim kipinden oluşan, atomik, şema doğrulamalı önbellek; 6 saat TTL. |

Kod, LLM destekli iki bağımsız güvenlik incelemesinden geçti. İncelemelerin bulduğu her sorun, düzeltilmeden önce çevrimdışı ortamda yeniden üretildi ve her düzeltme için bir regresyon testi yazıldı. Bu tablo yalnızca OpenCode çalışanları ve okuyucu için geçerlidir; özel CLI arka ucunun sınırları [Sınırlar](#sınırlar) bölümünde anlatılır.

## Başlarken

### Gereksinimler

- **Python 3.9 ya da üstü.** Üçüncü taraf paket yok.
- **Araştırma çalışanlarını çalıştırmak için:** web arama aracı olan, komut satırından çalışan bir ajan ortamı ve istediğiniz bir LLM hesabı. Çalışan arka ucu küçük bir JSON dosyasıyla yapılandırılır (modeller, anahtarın yeri, isteğe bağlı komut satırı arka ucu). Koda gömülü, sağlayıcıya özel hiçbir şey yoktur.
- *İsteğe bağlı:* `gh` (GitHub depo denetimi; kimlik doğrulamasını `gh` yönetir) ve `pdftotext` (PDF sayfaları).

Okuyucu, denetleyici, doğrulayıcı ve güven puanlayıcı için **model, hesap ya da anahtar gerekmez**; bunlar tek başlarına da işe yarar.

### Kurulum (Claude Code skill olarak)

```bash
git clone https://github.com/mesutbsdgn/quoteproof.git
mkdir -p ~/.claude/skills
ln -s "$PWD/quoteproof/arastir-ogren" ~/.claude/skills/arastir-ogren
```

Skill klasörünün adı `arastir-ogren` ("araştır ve öğren"). `SKILL.md`, yazarın kendi iş akışı için Türkçe yazılmıştır; dilediğiniz gibi uyarlayabilirsiniz.

### Yapılandırma (yalnız araştırma çalışanları için)

```bash
mkdir -p ~/.config/quoteproof
cp quoteproof/arastir-ogren/quoteproof.example.json ~/.config/quoteproof/config.json   # sonra modellerinizi ve anahtar yerini doldurun
python3 ~/.claude/skills/arastir-ogren/scripts/ayar.py                                   # durumu yazar (anahtarın kendisini asla)
```

Çalışan anahtarı OpenCode'a aktarılır; GitHub kimlik doğrulamasını `gh` yönetir (Quoteproof GitHub token'ı tutmaz).

Dosyada şunlar tanımlanır: modelleriniz, anahtarı tutan ortam değişkeninin *adı* (isteğe bağlı olarak anahtar dosyaları) ve isteğe bağlı bir komut satırı arka ucu şablonu.

- Komut JSON ya da düz metin basabilir. `"format": "text"` ayarında standart çıktının tamamı not sayılır; böylece hemen her ajan CLI'ı çalışan olarak kullanılabilir.
- `"prompt_via": "stdin"` ayarında istem, komut satırı yerine standart girdiden verilir. Bu seçenek, stdin okuyan CLI'lar ve çok uzun istemler için uygundur.
- Özel CLI'a yapılandırılmış anahtar aktarılmaz; CLI yalnızca izin verilen ortam değişkenlerini alır ve kendi oturumunu ya da yapılandırmasını kullanmalıdır. Bu arka uç için güvenlik sınırları [Sınırlar](#sınırlar) bölümündedir.
- Dosya sırasıyla `QUOTEPROOF_CONFIG` ortam değişkeninde, skill klasöründeki `quoteproof.json` dosyasında ve `~/.config/quoteproof/config.json` yolunda aranır. Dosya git'e girmez.

### Bir araştırma koşturun

```bash
S=~/.claude/skills/arastir-ogren/scripts

# 1) araştırma: çalışanlar paralel çalışır (koşularımızda küçük bir konu için yaklaşık 30 sn)
python3 $S/arastir.py PLAN.json -d arastirmam -j 3 -e dusuk
#    kesildi mi?  --devam  ekleyin, kaldığı yerden sürer

# 2) denetim + doğrulama otomatik çalışır; istediğiniz zaman ücretsiz olarak yeniden çalıştırabilirsiniz:
python3 $S/denetle.py arastirmam/notlar --plan PLAN.json
python3 $S/dogrula.py arastirmam/notlar --plan PLAN.json --temiz-yaz arastirmam/notlar-temiz
```

`PLAN.json`, konuların listesidir:

```json
[
  {
    "slug": "uv-hizi",
    "konu": "uv (Astral) Python paket yöneticisinin hız iddiaları",
    "amac": "pip karşılaştırmasının resmî ifadesini doğrula",
    "sorular": ["uv resmî dokümanında pip'e göre hız farkı nasıl belirtiliyor?",
                "uv'nin güncel kararlı sürümü nedir?"],
    "kaynaklar": "docs.astral.sh, github.com/astral-sh/uv",
    "kisitlar": "yalnız birincil kaynak"
  }
]
```

`kaynaklar` alanına beklediğiniz kaynakları yazarsanız çalışan doğru yöne yönelir ve bu alan adları +10 güven puanı alır.

### Araçları tek başına kullanın

```bash
S=arastir-ogren/scripts
python3 $S/oku.py https://docs.astral.sh/uv/ --soru "pip uyumluluğu" --token 600   # yalnız kısa, ilgili pasajlar
python3 $S/oku.py URL --ara "10-100x faster"        # bu ifade ya da rakam sayfada geçiyor mu? (bağlamıyla birlikte)
python3 $S/oku.py URL --robots                      # robots.txt izin veriyor mu?
python3 $S/oku.py URL --llms                        # sitenin llms.txt dizini (varsa)
python3 $S/guven.py https://medium.com/x https://docs.python.org/3/   # kaynak güven puanı + gerekçeler
```

### Örnek doğrulama raporu (özet; değerler gerçek koşulardan)

```text
Özet: Doğrulandı 19 · Kısmen 2   (21 bulgu, hepsi denetlendi)
| Karar      | Kanıt | İddia                                              | Kaynak         | Güven |
|------------|------:|----------------------------------------------------|----------------|------:|
| Doğrulandı |   3/3 | 0.12.23 sürümü 2026-10-03'te yayımlandı            | github.com     |    75 |
| Doğrulandı |   2/2 | "10-100x faster than pip" (özellik listesi)        | docs.astral.sh |    85 |
| Kısmen     |   1/2 | v2, standart link relation'ları ekledi …           | llmstxt.org    |    60 |
```

### Çıkış kodları (`arastir.py`)

`0` başarı · `64` plan hatalı · `69` kullanılabilir arka uç yok · `70` hiçbir çalışan başarılı değil · `71` denetleyici çöktü · `72` doğrulayıcı çalışmadı (elle doğrulayın) · `73` kısmi (bazı konular başarısız ya da zayıf) · `78` yapılandırma eksik ya da hatalı.

## SSS

**Neden doğrulamayı başka bir LLM'e yaptırmıyoruz?**
Çünkü o da aynı şekilde yanılabilir ve her iddia için jeton harcar. Kaynak sayfada metin aramak ucuzdur, her seferinde aynı sonucu verir ve tekrarlanabilir. Üstelik en çok zarar veren hatayı hedefler: uydurulmuş ya da yanlış çevrilmiş alıntıları.

**"Doğrulandı" iddianın doğru olduğu anlamına mı gelir?**
Hayır. Alıntılanan metnin gösterilen sayfada bulunduğu anlamına gelir. Sayfanın doğru olup olmadığı ayrı bir sorudur; bunu güven puanı, ikinci bir kaynak ve önemli iddiaları kontrol eden bir insan (ya da koordinatör model) değerlendirir.

**Belirli bir model ya da sağlayıcı gerekir mi?**
Denetim araçları için hiçbiri gerekmez. Araştırma çalışanları için bir ajan ortamı ve bir LLM hesabı gerekir; ikisi de küçük bir JSON dosyasıyla yapılandırılır. [Gereksinimler](#gereksinimler) bölümüne bakın.

**Bazı adlar neden Türkçe?**
Araç, Türkçe bir iş akışı olarak başladı. Notlardaki bölüm adları (`Özet`, `Alıntılı bulgular`, …) ve komut satırı bayrakları Türkçedir; ayrıştırıcılar bu biçimi okur. *İçerik* herhangi bir dilde olabilir, alıntılar da her zaman kaynağın dilinde kalır.

**Ne kadar sürüyor?**
Koşularımızda küçük bir konu, çalışan başına yaklaşık 30 saniye sürdü. Bütün bir koşunun denetimi ve doğrulaması, kaynak sayfaların indirilme süresi hariç birkaç saniyelik işlemci zamanı tutar.

## Sınırlar

- Doğrulama **metinsel**dir, anlamsal değildir: alıntı sayfada bulunup yine de yanlış anlaşılmış olabilir. Önemli iddialarda anlamı kendiniz kontrol edin.
- Güven puanı, alan adları ve URL biçimleri üzerine elle yazılmış bir sezgisel yöntemdir; alışılmadık siteleri yanlış sıralayabilir. Yalnızca öncelik belirlemek için kullanın.
- Çalışanlar için, LLM sağlayıcınıza bağlanmış hazır bir ajan ortamı gerekir; proje ortama yalnızca hangi model kimliklerini ve anahtar değişkenini kullanacağını bildirir. Farklı bir ortam için `scripts/arastir.py` dosyasına yeni bir arka uç işlevi eklemek gerekir.
- **Güvenlik sınırı özel CLI arka ucunu kapsamaz.** Varsayılanı "yasak" olan araç izinleri yalnızca OpenCode için tanımlıdır. Özel CLI yalnızca izin verilen ortam değişkenleriyle çalıştırılır ve `api_key_env` anahtarı bu yoldan aktarılmaz. Ortam değişkenlerini süzmek, CLI'ın dosya sistemine ya da ağa erişimini kısıtlamaz. Güvenmediğiniz bir CLI'ı kendi izolasyonunuzda (kapsayıcı, ayrı kullanıcı) çalıştırın.
- **Gizli bilgi maskeleme sınırlıdır.** Basit bir kalıpla yalnızca hata metinlerindeki bazı anahtar benzeri değerler maskelenir. Çalışan çıktısı, özel CLI yolu dahil, olduğu gibi not dosyasına yazılır; genel bir temizleme garantisi yoktur. `denetle.py`, `gh` alt sürecini ana sürecin ortamıyla çalıştırır.
- Yalnızca JavaScript ile yüklenen sayfalar tarayıcı olmadan okunamaz. Üçüncü taraf bir okuyucu seçeneği (`--jina`) vardır, ama URL'yi üçüncü tarafa gönderdiği için isteğe bağlıdır ve çalışanlar bunu hiçbir zaman kullanmaz.
- Okuyucu proxy kullanmaz ve DNS'i kendisi çözer. Yalnızca proxy üzerinden dışarı çıkılabilen ortamlarda çevrimiçi okuma ve alıntı doğrulama çalışmaz; çevrimdışı birim testleri etkilenmez.
- Çalışan istemleri, notlar ve raporlar varsayılan olarak Türkçedir (alıntılar kaynağın dilinde kalır).
- Test setleri çevrimdışı birim testleridir; canlı hat uçtan uca elle denendi, CI'da çalışmaz.

## Testler

```bash
python3 arastir-ogren/scripts/test_arastir.py   # 137 test: ayrıştırma, sözleşme, devam, doğrulama, güven puanı, yapılandırma, MCP sunucusu
python3 arastir-ogren/scripts/test_oku.py       # 50 test: ayıklama, BM25, önbellek, SSRF, yönlendirme, robots.txt, PDF
```

İki set de ağ erişimi olmadan çalışır.

## Depo yapısı

```text
arastir-ogren/            skill (~/.claude/skills/ altına kopyalayın ya da bağlayın)
├── SKILL.md              koordinatör talimatları (Türkçe)
├── quoteproof.example.json   yapılandırma şablonu (~/.config/quoteproof/config.json olarak kopyalayın)
├── references/           çalışan istemi, rapor şablonu, tasarımın dayandığı notlar
└── scripts/              arastir · denetle · dogrula · rapor_kontrol · oku · mcp_oku · guven · rapor_olc · ayar  (+ testler)
assets/                   logo
docs/fact-check/          bu README'nin doğrulaması (aşağıya bakın)
```

## Sürüm notları

Depoda henüz etiketli sürüm yok; kayıtlar en yeniden en eskiye, commit sırasıyla verilir. Ölçümlerin ayrıntısı kapatılmış [issue'lardadır](https://github.com/mesutbsdgn/quoteproof/issues?q=is%3Aissue+is%3Aclosed).

### Yayımlanmamış (belgeler)

- README yeniden yazıldı; Türkçe metin sadeleştirildi.
- Güvenlik anlatımı daraltıldı: kapalı-varsayılan araç izinleri ve ortam süzme yalnızca OpenCode çalışanları için geçerlidir, özel CLI arka ucu kapsam dışıdır. Gizli bilgi maskeleme yalnızca hata metinlerindeki bazı anahtar benzeri değerleri kapsar.
- Yapılandırma dosyasının arama yolu düzeltildi (`./quoteproof.json` yerine skill klasöründeki `quoteproof.json`).
- Okuyucunun proxy kullanmadığı, bu yüzden yalnızca proxy ile dışarı çıkılan ortamlarda çalışmadığı Sınırlar bölümüne eklendi.

### Rapor düzeyinde kaynak kontrolü ([`c88db28`](https://github.com/mesutbsdgn/quoteproof/commit/c88db28), [#4](https://github.com/mesutbsdgn/quoteproof/issues/4))

- Yeni `rapor_kontrol.py`, bitmiş raporu öğe öğe kaynak gösterdiği sayfalarla karşılaştırır. Gerekçe: gerçek bir olayda not doğruydu, ama rapor tablosu %43–98 aralığını tek bir saldırı varyantına bağlamıştı. Notların hepsi doğrulamayı geçtiği için hata ancak rapor düzeyinde görülebiliyordu.
- Gerçek bir 238 öğelik raporda ilk sürüm 129 hata verdi (neredeyse hepsi, tarih sütununun sayı aralığı sanılmasından). Ayarlamadan sonra 6 hata kaldı; bağlam bulgularında yanlış alarm görülmedi. Yeniden kurulan olay doğru işaretlendi.
- `--siki`, herhangi bir bulguda 1 koduyla çıkar; sentez aşamasında kapı olarak kullanılabilir.
- Sınır: sezgiseldir. Temiz çıktı raporun doğru olduğunu göstermez. Okunamayan sayfalar denetlenemez, ayrıca listelenir. Gerçek bir raporda doğrulanmış tek gerçek pozitif, yeniden kurulan olaydır.
- Testler: 137 + 50.

### Bağlam kontrolü ve güvenlik kaynakları için güven sınıfları ([`5711d99`](https://github.com/mesutbsdgn/quoteproof/commit/5711d99), [#2](https://github.com/mesutbsdgn/quoteproof/issues/2), [#3](https://github.com/mesutbsdgn/quoteproof/issues/3))

- **Bağlam kontrolü** (`dogrula.baglam_kontrol`): sayı içeren iddiada ayırt edici terim doğrulanan alıntıdan uzaksa *Doğrulandı* yerine *Kısmen* verilir. Üç gerçek koşuda yaklaşık 395 doğrulanmış bulgudan 0, 0 ve 3'ünü işaretledi (%1'in altında). **Gerçek veride doğrulanmış bir gerçek pozitif bulunmadı**; davranış, olayı yeniden kuran yapay bir testle sabitlendi.
- **Güvenlik kaynakları**: OWASP, MITRE, USENIX, PortSwigger gibi kaynaklar artık "belirsiz 50" değil. Yeni sınıflar: güvenlik standardı/rehberi 88, akademik güvenlik yayın yeri 85, resmî doküman 80, sektör basını 68. Gerçek bir güvenlik koşusunun 156 bulgusunun 154'ü artık "belirsiz" değil (ortalama puan 82,2). Benzer görünümlü alan adları (`owasp.org.evil.example` gibi) sınıflandırılmaz.

### İlk sürüm ([`60bd605`](https://github.com/mesutbsdgn/quoteproof/commit/60bd605), [#1](https://github.com/mesutbsdgn/quoteproof/issues/1), [#5](https://github.com/mesutbsdgn/quoteproof/issues/5))

- Birebir alıntı sözleşmesi, `denetle.py`, `dogrula.py`, `oku.py`, `guven.py` ve paralel çalışan hattı.
- Sağlayıcıdan bağımsız yapılandırma: modeller, anahtarın yeri ve isteğe bağlı komut satırı arka ucu bir yapılandırma dosyasında tutulur. Arka uç JSON ya da düz metin çıktı verebilir (`"format": "text"`), istemi argümanla ya da stdin ile alabilir (`"prompt_via": "stdin"`).
- PDF doğrulaması: okuma sırasına göre metin çıkarma, satır sonu tirelemesine ve tablo ayraçlarına toleranslı eşleşme. Bir gerçek koşuda *Doğrulandı* 141'den 148'e çıktı, *Bulunamadı* 8'den 2'ye düştü; kalan ikisi gerçek bir parafraz ve kesik bir alıntıydı.
- Sertleştirilmiş okuyucu: SSRF koruması ve IP sabitleme, robots.txt (RFC 9309), hız sınırı.
- Kaynak güven puanı ve bayrakları, kaldığı yerden sürdürülebilen koşular, güvenli tarafta kalan çalışan sözleşmesi.
- İngilizce ve Türkçe README, README'deki dış iddiaların doğrulaması.
- Testler: 115 + 50.

## Lisans

MIT. Ayrıntı için [LICENSE](LICENSE) dosyasına bakın.

---

## Doğrulama

Bu README'deki **dış standartlara ve araçlara** dayanan iddialar şunlardır: robots.txt'nin nasıl yorumlanması gerektiği (RFC 9309), operatör tipi NAT adres aralığı (RFC 6598), BM25 ve DNS rebinding'in ne olduğu, `llms.txt`'nin ne önerdiği ve örnekte kullanılan hız iddiası. Bunlar, projenin kendi doğrulayıcısı `dogrula.py` ile 2026-10-08'de denetlendi:

> **9 alıntının 9'u gösterilen sayfalarda bulundu.**

Notlar ve üretilen rapor [`docs/fact-check/`](docs/fact-check/) klasöründedir. Bu denetim de diğerleri gibi alıntılanan metnin sayfada bulunduğunu gösterir, sayfanın doğru olduğunu göstermez. Projenin kendi davranışına ilişkin iddialar (test sayıları, ölçülen oranlar) ise test setleri ve yazarın koşu günlükleriyle desteklenir.

---

*Bu belgenin Türkçe metni, Türkçe yazı kalıplarını sadeleştiren **Durulaç** becerisiyle gözden geçirildi.*
