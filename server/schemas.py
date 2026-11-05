from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=6)
    name: str
    phone: str = ""
    role: str = "customer"  # customer | expert
    city: str = "الرياض"


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class ServiceIn(BaseModel):
    category: str
    name: str
    duration_min: int = 60
    price: int
    description: str = ""


class ExpertProfileIn(BaseModel):
    display_name: str
    title: str = "خبيرة تجميل"
    bio: str = ""
    categories: list[str] = []
    districts: list[str] = []
    city: str = "الرياض"
    modes: list[str] = ["home"]
    travel_fee: int = 25
    years_exp: int = 1
    portfolio: list[str] = []
    hours: dict = {}
    cover: str = ""
    tint: str = "lavender"
    iban: str = ""
    bank_name: str = ""
    freelance_number: str = ""
    nafath_verified: bool = False  # mock Nafath toggle
    services: list[ServiceIn] = []


class AddressIn(BaseModel):
    label: str
    details: str
    lat: float = 24.7136
    lng: float = 46.6753


class BookingIn(BaseModel):
    expert_id: str
    service_ids: list[str]
    mode: str = "home"
    date: str
    time: str
    address_id: str | None = None
    payment_method: str = "mada"


class RejectIn(BaseModel):
    reason: str
    suggested_time: str | None = None


class StartCodeIn(BaseModel):
    code: str


class RateIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = ""
