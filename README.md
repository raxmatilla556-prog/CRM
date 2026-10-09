# Do'kon CRM

Uch rolli do'kon boshqaruv tizimi (Django).

| Rol | Imkoniyatlar |
|---|---|
| **Sotuvchi** | Kassa (tovar nomi bo'yicha qidiruv), naqd sotuv, qarzga sotish, chek chop etish, qarz daftari, qarz to'lovini qabul qilish, eslatma yuborish |
| **Omborchi** | Tovarlar, kirim (yetkazib beruvchidan), ombor ↔ do'kon ko'chirish, inventarizatsiya, kam qolgan / muddati yaqin tovarlar |
| **Ega** | Hammasi + daromad, sof foyda, top tovarlar, kam sotilayotganlar, sotuvchilar samaradorligi, xodimlar, harakatlar tarixi, Telegram hisobot |

## Ishga tushirish (Windows)

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_demo      # ega / sotuvchi / omborchi, parol: 123456
.venv\Scripts\python manage.py runserver
```

Brauzerda: http://127.0.0.1:8000. Demo foydalanuvchilar birinchi kirishda parolini almashtirishga majbur.
Ega xodimga bergan parol ham vaqtinchalik: xodim birinchi kirishda o'zinikiga almashtiradi.
5 marta noto'g'ri paroldan keyin login 10 daqiqaga bloklanadi.

`.env` da `DEBUG=0` bo'lishi kerak (xatoliklarda ichki ma'lumot ko'rsatilmaydi). Loglar: `logs/app.log`, `logs/bot.log`.
Sayt internetsiz ishlaydi: Bootstrap, ikonkalar va grafiklar `static/vendor` ichida.

## Kassa smenasi

Sotuvchi kassani ishlatishdan oldin smena ochadi (kassadagi boshlang'ich naqd), kun oxirida yopadi va
haqiqiy naqdni kiritadi. Tizim kutilgan summa (boshlang'ich + naqd sotuv + qarz to'lovlari − naqd vozvrat)
bilan solishtiradi, farqni egaga Telegramda yuboradi. Ega: **Smenalar** sahifasi.

## Ishga tushirish fayllari (`scripts/`)

- `kassa.bat` — kassani alohida oynada ochadi, chek tasdiqlash oynasiz standart printerga chiqadi
  (Windows'da termoprinterni "standart printer" qiling).
- `start_bot.vbs` — Telegram bot va avtomatik vazifalarni yashirin ishga tushiradi.
  Windows yoqilganda avtomatik ishlashi uchun `shell:startup` papkasida `DokonBot.vbs` bor.

## Zaxira nusxa

Har kuni `BACKUP_TIME` da (standart 21:30) `backups/` ga nusxa olinadi (oxirgi 30 tasi saqlanadi)
va egaga Telegramga fayl sifatida yuboriladi. Ega **Zaxira nusxa** sahifasidan istalgan payt yuklab oladi.

Tiklash: zip ichidagi `db.sqlite3` ni loyiha papkasiga qo'ying, yoki boshqa bazada:
`python manage.py migrate` va `python manage.py loaddata data.json`.

## Bulut bazasi (Neon / Supabase)

`.env` ga `DATABASE_URL=postgresql://...?...sslmode=require` yozing va `manage.py migrate` ni qayta ishga tushiring.

## Telegram

1. @BotFather dan bot yarating, tokenni `.env` dagi `TELEGRAM_BOT_TOKEN` ga yozing.
2. `python manage.py telegram_bot` — botni ishga tushiradi (doimiy ishlab turishi kerak).
3. Ega: Hisobotlar sahifasida **Telegramni ulash** tugmasini bosib, botda **Start** ni bosadi. Bir nechta ega ulanishi mumkin.
4. Qarzdor klient botga telefon raqamini yuborsa, qarz daftaridagi klientga avtomatik bog'lanadi.

Avtomatik vazifalar bot ichida bajariladi (vaqtlari `.env` da): kunlik hisobot `DAILY_REPORT_TIME` (21:00),
qarz eslatmalari `DEBT_REMINDER_TIME` (10:00), zaxira `BACKUP_TIME` (21:30). Kompyuter o'sha paytda o'chiq
bo'lsa, o'sha kuni yoqilganda bajariladi. Qo'lda: `python manage.py run_jobs --now daily_report`.

Tovar minimal qoldiqdan kam bo'lib qolganda va har bir vozvratda egaga Telegram xabari darhol yuboriladi.

## Vozvrat

Sotuvlar ro'yxatida yoki chekda ↩ tugmasi. Sotuvchi faqat o'zining bugungi sotuvini, ega istalganini qaytaradi.
Tovar do'kon qoldig'iga qaytadi; klientning qarzi bo'lsa summa avval qarzdan ayriladi, qolgani naqd qaytariladi.
Chegirmali sotuvda narx chegirma ulushiga kamaytiriladi. Hisobotlarda vozvrat qaytarilgan kunida ayriladi.

## SMS (Eskiz.uz)

`ESKIZ_EMAIL`, `ESKIZ_PASSWORD` ni to'ldiring. Klientda Telegram bo'lmasa, eslatma SMS orqali boradi.
Eskiz SMS matn shablonini oldindan tasdiqlatishni talab qiladi.

## Chek printer

Chek 80 mm uchun. 58 mm printer bo'lsa `templates/sales/receipt.html` da `--paper: 58mm` qiling.
Brauzerning chop etish oynasida termoprinterni tanlang (Chrome'da `--kiosk-printing` bilan oyna chiqmasdan chop etadi).

## Testlar

```bash
python manage.py test
```
