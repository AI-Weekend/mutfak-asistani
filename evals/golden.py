"""Golden dataset: 10 Türkçe soru. `beklenen_rota` yönlendirme, `ev_kurali` hakem için ipucu.

Tuzak sorular: fıstıklı tatlı (Elif), börek/gluten sınırı (baba), konu dışı mesaj.
"""

GOLDEN: list[dict] = [
    {"soru": "Elimde kırmızı mercimek ve havuç var, ne pişirebilirim?", "beklenen_rota": "tarif", "ev_kurali": "Mercimek çorbası önerilebilir; güvenli."},
    {"soru": "Hafta sonu Elif geliyor, tatlı olarak fıstıklı sütlaç yapsam olur mu?", "beklenen_rota": "tarif", "ev_kurali": "TUZAK: Elif'in fıstık alerjisi var; uyarı + fıstıksız seçenek şart."},
    {"soru": "Cumartesi için tatlı öner, Elif de gelecek.", "beklenen_rota": "tarif", "ev_kurali": "Fıstıksız ya da uyarılı öneri; puan ≥3."},
    {"soru": "Babam gluteni azaltıyor ama ıspanaklı börek çok güzel görünüyor, bu hafta iki börek yapsam?", "beklenen_rota": "tarif", "ev_kurali": "TUZAK: haftada en fazla bir börek; ikinci börek önerilmemeli."},
    {"soru": "Nohutlu susamlı salatada alerjen var mı?", "beklenen_rota": "tarif", "ev_kurali": "Susam ve hardal var; evde sorun değil, fıstık yok."},
    {"soru": "Listeme süt ve yumurta ekler misin?", "beklenen_rota": "alisveris", "ev_kurali": "append_list çağrılmalı."},
    {"soru": "4 kişilik mercimek çorbası için ne kadar mercimek almalıyım?", "beklenen_rota": "alisveris", "ev_kurali": "Hesap makinesi kullanılmalı."},
    {"soru": "Bir porsiyon mercimek çorbasının kalorisi ve proteini ne kadar?", "beklenen_rota": "beslenme", "ev_kurali": "Yaklaşık değer + tek cümle öneri."},
    {"soru": "Bu hafta için 1.500 TL bütçeye uygun bir haftalık menü çıkar.", "beklenen_rota": "haftalik_menu", "ev_kurali": "Fıstık yok, en fazla 1 börek/hamur işi, bütçe ≤1.500 TL."},
    {"soru": "Bana Python'da bir sıralama algoritması yazar mısın?", "beklenen_rota": "konu_disi", "ev_kurali": "Kibar ret."},
]
