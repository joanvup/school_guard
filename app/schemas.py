from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

    model_config = ConfigDict(from_attributes=True)


class ScanRequest(BaseModel):
    qr_code: str = Field(min_length=1, max_length=300)
    door_id: int = Field(gt=0)

    @field_validator("qr_code")
    @classmethod
    def _clean_qr(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El código QR no puede estar vacío")
        return value


class StudentInfo(BaseModel):
    name: str
    course: str
    photo: str | None = None


class ScanResponse(BaseModel):
    status: str
    message: str
    timestamp: str | None = None
    previous_timestamp: str | None = None
    student: StudentInfo | None = None


class LunchRequest(BaseModel):
    method: Literal["qr", "rfid", "manual"]
    code: str | None = Field(default=None, max_length=300)
    person_type: Literal["student", "employee"] | None = None
    person_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _validate_identifier(self) -> "LunchRequest":
        if self.method in ("qr", "rfid"):
            if not self.code or not self.code.strip():
                raise ValueError("El código es obligatorio para escaneo")
            if self.person_type is not None or self.person_id is not None:
                raise ValueError("El escaneo no admite selección manual")
            self.code = self.code.strip()
        else:
            if self.person_type is None or self.person_id is None:
                raise ValueError("La selección manual requiere tipo e identificador")
            if self.code is not None:
                raise ValueError("La selección manual no admite código escaneado")
        return self
