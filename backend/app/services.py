from uuid import uuid4

from sqlalchemy.orm import Session

from .models import Repair
from .schemas import RepairCreate
from . import campus_data


DEMO_GRADES = [
    {"course": "高等数学", "semester": "2025-2026 秋", "credits": 4, "score": 88},
    {"course": "大学英语", "semester": "2025-2026 秋", "credits": 3, "score": 91},
    {"course": "程序设计基础", "semester": "2025-2026 秋", "credits": 3, "score": 86},
]
DEMO_SCHEDULE = [
    {"weekday": "周一", "time": "08:00-09:40", "course": "高等数学", "room": "教学楼 A101"},
    {"weekday": "周二", "time": "10:00-11:40", "course": "大学英语", "room": "教学楼 B203"},
    {"weekday": "周四", "time": "14:00-15:40", "course": "程序设计基础", "room": "实验楼 302"},
]
DEMO_CLASSROOMS = [
    {"building": "教学楼 A", "room": "A102", "seats": 48, "available": True},
    {"building": "教学楼 A", "room": "A208", "seats": 60, "available": True},
    {"building": "实验楼", "room": "305", "seats": 36, "available": True},
]


def grades() -> dict:
    if campus_data.configured("grades"):
        return campus_data.fetch_source("grades")
    return {"demo": True, "items": DEMO_GRADES}


def schedule() -> dict:
    if campus_data.configured("schedule"):
        return campus_data.fetch_source("schedule")
    return {"demo": True, "items": DEMO_SCHEDULE}


def credits() -> dict:
    if campus_data.configured("credits"):
        return campus_data.fetch_source("credits")
    return {"demo": True, "required": 160, "earned": sum(row["credits"] for row in DEMO_GRADES)}


def classrooms(building: str | None = None, min_seats: int = 0) -> dict:
    if campus_data.configured("classrooms"):
        result = campus_data.fetch_source("classrooms")
        normalized_building = "".join((building or "").split()).lower()
        result["items"] = [room for room in result["items"]
                           if (not normalized_building or normalized_building in "".join(room["building"].split()).lower())
                           and room["seats"] >= min_seats and room.get("available", True)]
        return result
    normalized_building = "".join((building or "").split()).lower()
    items = [room for room in DEMO_CLASSROOMS if (not normalized_building or normalized_building in "".join(room["building"].split()).lower()) and room["seats"] >= min_seats]
    return {"demo": True, "items": items}


def submit_repair(db: Session, data: RepairCreate) -> dict:
    if campus_data.configured("repairs"):
        return campus_data.fetch_source("repairs", data.model_dump())
    repair = Repair(id=str(uuid4()), **data.model_dump())
    db.add(repair)
    db.commit()
    return {"id": repair.id, "status": repair.status, "demo": True}
