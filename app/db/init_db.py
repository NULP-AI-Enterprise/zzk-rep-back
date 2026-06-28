from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_surname
from app.models.models import (
    User, UserRole, Region, PatientProfile,
    PatientStatus, SexType, DisabilityGroup, DiagnosisType, HistologyStatus,
)


async def init_db(db: AsyncSession):
    # 1. Регіони
    regions_list = [
        "Вінницька область", "Волинська область", "Дніпропетровська область",
        "Донецька область", "Житомирська область", "Закарпатська область",
        "Запорізька область", "Івано-Франківська область", "Київська область",
        "Кіровоградська область", "Луганська область", "Львівська область",
        "Миколаївська область", "Одеська область", "Полтавська область",
        "Рівненська область", "Сумська область", "Тернопільська область",
        "Харківська область", "Херсонська область", "Хмельницька область",
        "Черкаська область", "Чернівецька область", "Чернігівська область",
        "Автономна Республіка Крим", "м. Київ", "м. Севастополь"
    ]

    for name in regions_list:
        res = await db.execute(select(Region).where(Region.name == name))
        if not res.scalar_one_or_none():
            db.add(Region(name=name))

    await db.flush()   # ensure region IDs are available below

    # 2. Користувачі (без паролів — вхід через magic link)
    users_to_create = [
        {
            "email": "bohdan.m.pavlyk@lpnu.ua",
            "role": UserRole.ADMIN,
            "first": "Богдан",
            "last": "Павлик",
            "patronymic": "Михайлович",
            "job_position": "Розробник",
            "job_place": "Національний університет Львівська політехніка",
            "region_id": 12
        },
        {
            "email": "zormen4@gmail.com",
            "role": UserRole.ADMIN,
            "first": "Євген",
            "last": "Орза",
            "patronymic": "Сергійович",
            "job_position": "Розробник",
            "job_place": "Національний університет Львівська політехніка",
            "region_id": 12
        },
        {
            "email": "yorza@thesis-i.com",
            "role": UserRole.DOCTOR,
            "first": "Євген",
            "last": "Орза",
            "patronymic": "Сергійович",
            "job_position": "Лікар",
            "job_place": "Національний університет Львівська політехніка",
            "region_id": 12
        },
    ]

    for u in users_to_create:
        res = await db.execute(select(User).where(User.email == u["email"]))
        if not res.scalar_one_or_none():
            db.add(User(
                email=u["email"],
                role=u["role"],
                first_name=u["first"],
                last_name=u["last"],
                patronymic=u["patronymic"],
                job_position=u["job_position"],
                job_place=u["job_place"],
                region_id=u["region_id"],
            ))

    await db.flush()   # ensure user IDs are available for doctor_id below

    # 3. Тестовий пацієнт
    res = await db.execute(
        select(PatientProfile).where(PatientProfile.email == "yevheniiorza@gmail.com")
    )
    if not res.scalar_one_or_none():
        # Отримуємо лікаря, щоб прив'язати пацієнта
        doctor_res = await db.execute(
            select(User).where(User.email == "yorza@thesis-i.com")
        )
        doctor = doctor_res.scalar_one_or_none()

        db.add(PatientProfile(
            email="yevheniiorza@gmail.com",
            initials="ЄО",
            surname_encrypted=encrypt_surname("Орза"),
            sex=SexType.M,
            birth_year=1995,
            region_id=12,
            diagnosis=DiagnosisType.UC,
            histologically_confirmed=HistologyStatus.YES,
            disability=DisabilityGroup.NONE,
            status=PatientStatus.ATTACHED,
            doctor_id=doctor.id if doctor else None,
        ))

    await db.commit()
