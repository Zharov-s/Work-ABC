"""
Одноразовый импорт заявок из «Перечень_заявок_27.03.2026».
Запустить на сервере один раз: python3 import_perechen_27032026.py
28 компаний (реальные входящие заявки на аренду), 26 новых + 2 пропущено как дубли.
"""
import re, sys
from datetime import datetime

sys.path.insert(0, '.')
from database import get_db

CONTACTS = [
    {"company_name": "ИП Ясенчук Г.Ю.", "inn": "701742503179", "person_name": "Георгий Юрьевич Ясенчук", "title": None, "email": "solarroot@gmail.com", "personal_email": None, "generic_email": "solarroot@gmail.com", "mobile_phone": "89009232299", "generic_phone": None, "segment": "light_industrial", "notes": "ОКВЭД: 43.39"},
    {"company_name": "ООО ИТК ЭНДОПРИНТ", "inn": "7729039986", "person_name": "Крайнов Николай Николаевич", "title": None, "email": "knn@endoprint.ru", "personal_email": "knn@endoprint.ru", "generic_email": None, "mobile_phone": "89037554655", "generic_phone": None, "segment": "medtech", "notes": "ОКВЭД: 26.60 | Площадь: 150-300 м²"},
    {"company_name": "ООО ПРОСТО ПОДУШКА", "inn": "9715478786", "person_name": None, "title": None, "email": "sale@prostopodushka.ru", "personal_email": None, "generic_email": "sale@prostopodushka.ru", "mobile_phone": None, "generic_phone": "7 495 118 32 13", "segment": "light_industrial", "notes": "Площадь: 500-700 м²"},
    {"company_name": "ООО ТИПОГРАФИЯ ВОЗРОЖДЕНИЕ", "inn": "7725570138", "person_name": "Маторина Вера Михайловна", "title": None, "email": "matorinavera@yandex.ru", "personal_email": None, "generic_email": "vozrod@yandex.ru", "mobile_phone": "89166854257", "generic_phone": None, "segment": "light_industrial", "notes": "Площадь: 1 500 м² | Формат: аренда"},
    {"company_name": "ООО НПО ПРОМ-ПК", "inn": "7723802792", "person_name": "Зимов Сергей Викторович", "title": None, "email": "zimov@prom-pc.ru", "personal_email": "zimov@prom-pc.ru", "generic_email": "info@prom-pc.ru", "mobile_phone": "89032727000", "generic_phone": None, "segment": "it_hardware", "notes": "Площадь: 800 м²"},
    {"company_name": "ООО КУБ", "inn": "5024202904", "person_name": "Кравцов Алексей Викторович", "title": None, "email": "a@vmmgame.ru", "personal_email": "a@vmmgame.ru", "generic_email": None, "mobile_phone": "8 995 120 25 55", "generic_phone": None, "segment": "light_industrial", "notes": "Площадь: 300-500 м²"},
    {"company_name": "ООО Хозлавочка", "inn": "7720333976", "person_name": "Власов Алексей Николаевич", "title": "генеральный директор", "email": "info@hozlavochka.ru", "personal_email": None, "generic_email": "info@hozlavochka.ru", "mobile_phone": None, "generic_phone": "7 (964) 558 28 35", "segment": "light_industrial", "notes": "Площадь: 600 м²"},
    {"company_name": "АО НИИЧАСПРОМ", "inn": "7712039346", "person_name": "Голованов Александр Викторович", "title": "Исполнительный директор", "email": "golovanov@niichasprom.ru", "personal_email": "golovanov@niichasprom.ru", "generic_email": None, "mobile_phone": "7 985 364-37-91", "generic_phone": None, "segment": "electronics", "notes": "ОКВЭД: 26.52 | Площадь: 2 000 м²"},
    {"company_name": "ООО Техстрой МСК", "inn": "9728055795", "person_name": "Васильев Александр Сергеевич", "title": "Генеральный директор", "email": "info@tehstroy.msk.ru", "personal_email": None, "generic_email": "info@tehstroy.msk.ru", "mobile_phone": "8 968 686 60 00", "generic_phone": None, "segment": "electronics", "notes": "Площадь: 1 000 м²"},
    {"company_name": "ООО Группа компаний ЭС-ТИ-АЙ", "inn": "3906242283", "person_name": "Азова О.А.", "title": "Коммерческий директор", "email": "office@sti-group.org", "personal_email": None, "generic_email": "office@sti-group.org", "mobile_phone": "8 906 212 36 27", "generic_phone": None, "segment": "electronics", "notes": "Площадь: 5 000 м² | Формат: аренда / выкуп"},
    {"company_name": "ООО Бьеф", "inn": "7715564960", "person_name": "Александр Семенцов", "title": "Ассистент", "email": "a.sementsov@zoom-lenses.ru", "personal_email": "a.sementsov@zoom-lenses.ru", "generic_email": "info@zoom-lenses.ru", "mobile_phone": "+7 904 680-40-60", "generic_phone": None, "segment": "medtech", "notes": "ОКВЭД: 26.70 | Площадь: 300 м²"},
    {"company_name": "ООО НПП АСИС", "inn": "7728387282", "person_name": "Свирилин Пётр Иванович", "title": None, "email": "p.svirilin@asys-npp.ru", "personal_email": "p.svirilin@asys-npp.ru", "generic_email": "info@asys-npp.ru", "mobile_phone": "7 (925) 017-017-7", "generic_phone": None, "segment": "electronics", "notes": "Площадь: 500-800 м²"},
    {"company_name": "АО Концерн Знак", "inn": "5904001222", "person_name": "Шарыгина Мария Игоревна", "title": "начальник юридического отдела", "email": "eivlieva@cznak.ru", "personal_email": "eivlieva@cznak.ru", "generic_email": "ur@cznak.ru", "mobile_phone": None, "generic_phone": "(926)5959596", "segment": "light_industrial", "notes": "Площадь: 3 000 м²"},
    {"company_name": "ООО ТПК ЮНИТА", "inn": "7703428890", "person_name": "Юнусов Ильдар Алмазович", "title": "ГД", "email": "zakaz@unita-cards.ru", "personal_email": None, "generic_email": "zakaz@unita-cards.ru", "mobile_phone": "89259250646", "generic_phone": None, "segment": "light_industrial", "notes": "Площадь: 1 500 м²"},
    {"company_name": "ООО ДОМ МОДЫ АНИКА КЕРИМОВА", "inn": "7726387520", "person_name": "Альберт", "title": None, "email": None, "personal_email": None, "generic_email": None, "mobile_phone": "7 925 102-11-82", "generic_phone": None, "segment": "light_industrial", "notes": "Площадь: 1 000 м²"},
    {"company_name": "ООО ИНФОРМАТИК", "inn": "7703606133", "person_name": "Артур Мальм", "title": None, "email": "malm.a.s@informatic.ru", "personal_email": "malm.a.s@informatic.ru", "generic_email": None, "mobile_phone": "89859172039", "generic_phone": None, "segment": "electronics", "notes": "ОКВЭД: 26.20 | Площадь: 600 м²"},
    {"company_name": "ИП Коняшкин С.В.", "inn": "773171673020", "person_name": "Коняшкин Сергей Викторович", "title": None, "email": "sk@2k-sport.com", "personal_email": "sk@2k-sport.com", "generic_email": None, "mobile_phone": "8 985 364 71 24", "generic_phone": None, "segment": "light_industrial", "notes": "Площадь: 200 м²"},
    {"company_name": "ООО ТД Независимость", "inn": "7736658962", "person_name": "Пеньковский Назар Артурович", "title": None, "email": "pna@t-d-n.ru", "personal_email": "pna@t-d-n.ru", "generic_email": None, "mobile_phone": "+79629356541", "generic_phone": None, "segment": "light_industrial", "notes": "Площадь: 800 м²"},
    {"company_name": "ООО МКРУС", "inn": "7736329326", "person_name": "Мерзляков Александр Александрович", "title": None, "email": "am@mkrus.ru", "personal_email": "am@mkrus.ru", "generic_email": None, "mobile_phone": "+7 (977) 884-98-33", "generic_phone": None, "segment": "electronics", "notes": "Площадь: 1 200 м²"},
    {"company_name": "ООО ПРИНТ-ЛЕЙБЛ", "inn": "7737548539", "person_name": "Серебряков Евгений Сергеевич", "title": "Генеральный директор", "email": "serebryakov@prlabel.ru", "personal_email": "serebryakov@prlabel.ru", "generic_email": None, "mobile_phone": "8-915-331-53-09", "generic_phone": None, "segment": "light_industrial", "notes": "Площадь: 500 м² | Формат: аренда"},
    {"company_name": "ООО НПК ЛЕДАРТ", "inn": "7721774765", "person_name": "Рыбников Александр Анатольевич", "title": "Заведующий отделом по маркетингу и сбыту", "email": "led@ledart.ru", "personal_email": None, "generic_email": "led@ledart.ru", "mobile_phone": "89859207996", "generic_phone": None, "segment": "light_industrial", "notes": "ОКВЭД: 27.40 | Площадь: 400 м²"},
    {"company_name": "ООО МЕДЕЛИЯ", "inn": "7743697514", "person_name": "Бойченко Евгения Сергеевна", "title": "Исполнительный директор", "email": "ok@medelia.ru", "personal_email": "ok@medelia.ru", "generic_email": None, "mobile_phone": "8-903-140-35-41", "generic_phone": None, "segment": "medtech", "notes": "Площадь: 200 м²"},
    {"company_name": "ООО БД", "inn": "7719550221", "person_name": "Поляков Павел Валерьевич", "title": "Юрисконсульт", "email": "p.pol@bdrosma.ru", "personal_email": "p.pol@bdrosma.ru", "generic_email": None, "mobile_phone": None, "generic_phone": "84991101638", "segment": "electronics", "notes": "Площадь: 1 500 м²"},
    {"company_name": "ИП НАЗАРОВА ЕЛЕНА ВИКТОРОВНА", "inn": None, "person_name": "Ованесов Станислав Александрович", "title": None, "email": "ovanesov@yandex.ru", "personal_email": None, "generic_email": "ovanesov@yandex.ru", "mobile_phone": "+7 925 230-64-80", "generic_phone": None, "segment": "light_industrial", "notes": "Площадь: 150 м²"},
    {"company_name": "ООО РПК Метрополитеновец", "inn": "7710956080", "person_name": "Литвинов Михаил Валентинович", "title": None, "email": "umetro59@mail.ru", "personal_email": None, "generic_email": "umetro59@mail.ru", "mobile_phone": "8-903-960-61-17", "generic_phone": None, "segment": "light_industrial", "notes": "Площадь: 700 м²"},
    {"company_name": "ООО ВЭЙВ", "inn": "7723887355", "person_name": "Павлов Алексей", "title": None, "email": "bruhov@wave-fc.ru", "personal_email": "bruhov@wave-fc.ru", "generic_email": None, "mobile_phone": "+7 926 901 47 90", "generic_phone": None, "segment": "medtech", "notes": "Площадь: 300 м²"},
]

def run():
    conn = get_db()
    existing_emails = {r['email'].lower() for r in conn.execute(
        "SELECT email FROM contacts WHERE email IS NOT NULL AND email != ''"
    ).fetchall()}
    existing_inns = {r['inn'] for r in conn.execute(
        "SELECT inn FROM contacts WHERE inn IS NOT NULL"
    ).fetchall()}

    today = datetime.now().strftime('%Y-%m-%d')
    saved = skipped = 0

    for c in CONTACTS:
        inn = c.get('inn')
        email = c.get('email')
        if email and email.lower() in existing_emails:
            print(f'⏭  {c["company_name"][:40]} — email дубль')
            skipped += 1
            continue
        if inn and inn in existing_inns:
            print(f'⏭  {c["company_name"][:40]} — ИНН дубль')
            skipped += 1
            continue
        try:
            conn.execute(
                """INSERT OR IGNORE INTO contacts
                   (company_name, website, person_name, title,
                    email, personal_email, generic_email,
                    phone, mobile_phone, generic_phone,
                    inn, segment, region, date_found, status, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new',?)""",
                (c['company_name'], None,
                 c.get('person_name'), c.get('title'),
                 email, c.get('personal_email'), c.get('generic_email'),
                 c.get('mobile_phone') or c.get('generic_phone'),
                 c.get('mobile_phone'), c.get('generic_phone'),
                 inn, c.get('segment', 'light_industrial'), 'Москва',
                 today, c.get('notes'))
            )
            if email:
                existing_emails.add(email.lower())
            if inn:
                existing_inns.add(inn)
            saved += 1
            print(f'✅ {c["company_name"][:40]} | {email}')
        except Exception as e:
            print(f'❌ {c["company_name"]}: {e}')

    conn.commit()
    conn.close()
    print(f'\nДобавлено: {saved} | Пропущено: {skipped}')

if __name__ == '__main__':
    run()
