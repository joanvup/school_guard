from pydantic import BaseModel
from typing import Optional

class StudentBase(BaseModel):
    student_id: str
    full_name: str
    course: str
    is_authorized: bool = False

class StudentCreate(StudentBase):
    pass

class StudentResponse(StudentBase):
    id: int
    photo_path: Optional[str] = None

    class Config:
        orm_mode = True