from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import date, datetime


# --- Auth ---
class UserCreate(BaseModel):
    id: str
    email: str
    password: str
    nama: str
    role: str = "staff"

class UserResponse(BaseModel):
    id: str
    email: str
    nama: str
    role: str
    avatar_url: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class UserUpdate(BaseModel):
    email: Optional[str] = None
    nama: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    avatar_url: Optional[str] = None


# --- Breeder ---
class BreederBase(BaseModel):
    nama: Optional[str] = None
    jenis_kelamin: str
    tanggal_lahir: Optional[date] = None
    generasi: str
    varian_warna: str
    asal: str
    status: str = "breeding"
    foto_url: Optional[str] = None
    parent_jantan_id: Optional[str] = None
    parent_betina_id: Optional[str] = None

class BreederCreate(BreederBase):
    id: Optional[str] = None

class BreederUpdate(BaseModel):
    """PUT parsial: semua field opsional supaya edit tidak 422 karena field wajib Create."""
    id: Optional[str] = None
    nama: Optional[str] = None
    jenis_kelamin: Optional[str] = None
    tanggal_lahir: Optional[date] = None
    generasi: Optional[str] = None
    varian_warna: Optional[str] = None
    asal: Optional[str] = None
    status: Optional[str] = None
    foto_url: Optional[str] = None
    parent_jantan_id: Optional[str] = None
    parent_betina_id: Optional[str] = None

class BreederResponse(BreederBase):
    id: str
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class BreederDetailResponse(BreederResponse):
    total_telur: Optional[int] = 0
    persentase_fertil: Optional[float] = 0.0
    jumlah_anakan: Optional[int] = 0

class BreederLineage(BaseModel):
    breeder: BreederDetailResponse
    parent_jantan: Optional[BreederDetailResponse] = None
    parent_betina: Optional[BreederDetailResponse] = None

class BreederCompareItem(BaseModel):
    id: str
    nama: Optional[str] = None
    jenis_kelamin: str
    generasi: str
    varian_warna: str
    status: str
    total_telur: int = 0
    persentase_fertil: float = 0.0
    jumlah_anakan: int = 0

class BreederCompareResponse(BaseModel):
    breeders: List[BreederCompareItem]


# --- Egg ---
class EggBase(BaseModel):
    slot: int
    induk_jantan_id: Optional[str] = None
    induk_betina_id: Optional[str] = None
    tanggalMasuk: str
    fertilitas: str = "Belum dicek"
    akhir: str = "Proses"
    catatan: Optional[str] = None

class EggCreate(EggBase):
    id: Optional[str] = None

class EggUpdate(BaseModel):
    """PUT parsial telur: semua field opsional."""
    id: Optional[str] = None
    slot: Optional[int] = None
    induk_jantan_id: Optional[str] = None
    induk_betina_id: Optional[str] = None
    tanggalMasuk: Optional[str] = None
    fertilitas: Optional[str] = None
    akhir: Optional[str] = None
    catatan: Optional[str] = None

class EggResponse(EggBase):
    id: str
    model_config = ConfigDict(from_attributes=True)


# --- Chick ---
class ChickBase(BaseModel):
    egg_id: str
    tanggal_menetas: date
    berat_awal: float
    skor_kesehatan: str
    status: str = "newborn"
    foto_url: Optional[str] = None
    catatan: Optional[str] = None

class ChickCreate(ChickBase):
    id: Optional[str] = None

class ChickUpdate(BaseModel):
    """PUT parsial anakan.

    `egg_id` sengaja ikut dideklarasi: nilai berbeda harus DITOLAK, bukan
    diam-diam diabaikan — ID anakan berisi ID telur, jadi keduanya tidak boleh
    dipisah. `induk_*` tidak ada di sini karena selalu diturunkan dari telur.
    """
    id: Optional[str] = None
    egg_id: Optional[str] = None
    tanggal_menetas: Optional[date] = None
    berat_awal: Optional[float] = None
    skor_kesehatan: Optional[str] = None
    status: Optional[str] = None
    foto_url: Optional[str] = None
    catatan: Optional[str] = None

class ChickResponse(ChickBase):
    id: str
    induk_jantan_id: Optional[str] = None
    induk_betina_id: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# --- Incubator Settings ---
class IncubatorSettingsBase(BaseModel):
    suhu_min: float = 37.0
    suhu_max: float = 38.0
    kelembapan_min: float = 55.0
    kelembapan_max: float = 65.0
    interval_rotasi_menit: int = 240

class IncubatorSettingsResponse(IncubatorSettingsBase):
    id: int
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# --- Incubator Status ---
class IncubatorStatusBase(BaseModel):
    suhu_sekarang: float
    kelembapan_sekarang: float
    lampu_status: str
    terakhir_rotasi: Optional[datetime] = None

class IncubatorStatusResponse(IncubatorStatusBase):
    id: int
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class IncubatorStatusCreate(IncubatorStatusBase):
    pass


# --- Telemetry Log ---
class TelemetryLogBase(BaseModel):
    timestamp: str
    temperature: float
    humidity: float

class TelemetryLogResponse(TelemetryLogBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# --- Rotation Log ---
class RotationLogBase(BaseModel):
    timestamp: str
    status: str
    catatan: Optional[str] = None

class RotationLogResponse(RotationLogBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# --- Sales ---
class SaleBase(BaseModel):
    tanggal: str
    item: str
    referensiId: str
    pembeli: str
    qty: int
    hargaSatuan: float
    status: str = "Booking"
    catatan: Optional[str] = None

class SaleCreate(SaleBase):
    id: str

class SaleResponse(SaleBase):
    id: str
    model_config = ConfigDict(from_attributes=True)


# --- Finance ---
class FinanceBase(BaseModel):
    tanggal: str
    tipe: str
    kategori: str
    jumlah: float
    catatan: Optional[str] = None

class FinanceCreate(FinanceBase):
    id: str

class FinanceResponse(FinanceBase):
    id: str
    created_by: str
    model_config = ConfigDict(from_attributes=True)


# --- Alert ---
class AlertResponse(BaseModel):
    id: int
    tipe: str
    pesan: str
    level: str
    is_read: bool
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# --- Dashboard ---
class DashboardSummary(BaseModel):
    total_telur_aktif: int
    total_anakan_bulan_ini: int
    inkubator_status: Optional[IncubatorStatusResponse] = None
    finance_summary: Optional[dict] = None


# --- Storage (MinIO) ---
class UploadResponse(BaseModel):
    message: str = "Upload berhasil"
    folder: str
    filename: str
    object_key: str
    url: str


class DeleteResponse(BaseModel):
    message: str


# --- CCTV Snapshot ---
class CctvSnapshotResponse(BaseModel):
    id: int
    captured_at: Optional[datetime] = None
    object_key: str
    url: str
    source: str
    model_config = ConfigDict(from_attributes=True)
