"""Validasi rantai ID silsilah: induk -> telur -> anak.

Format:
  Breeder F0 : JB01 (jantan) / BB01 (betina)
  Telur/anak : {ID_Jantan}{ID_Betina}-{NN}  contoh: JB01BB02-01
  Chick      : {ID_Telur}-C{NN}             contoh: JB01BB02-01-C01

Aturan edit: prefix warisan dikunci, hanya suffix nomor yang boleh berubah.
ID lama (EGG-001, MRK-..., CHK-...) dilewati validasi agar data lama tetap bisa dibaca.
"""

import re
from typing import List, Optional

from .models import Breeder, Egg, Chick

RE_F0 = re.compile(r"^(JB|BB)(\d{1,3})$")
RE_ANAK = re.compile(r"^(JB\d{1,3})(BB\d{1,3})-(\d{1,3})$")
RE_CHICK = re.compile(r"^(.+)-C(\d{1,3})$")

JANTAN = "Jantan"
BETINA = "Betina"
_GENDER_ALIASES = {
    "jantan": JANTAN, "male": JANTAN, "laki": JANTAN, "l": JANTAN,
    "betina": BETINA, "female": BETINA, "bet": BETINA, "b": BETINA,
}


def normalize_gender(value) -> Optional[str]:
    """'jantan'/'male'/'JANTAN' -> 'Jantan'. Nilai tak dikenal -> None."""
    if value is None:
        return None
    key = str(value).strip().lower()
    if not key:
        return None
    return _GENDER_ALIASES.get(key)


def clean_optional_str(value) -> Optional[str]:
    """String kosong/spasi dari form diubah jadi None (biar nullable DB aman)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validate_breeder_parent(db, child_id: Optional[str], parent_id: Optional[str],
                            expected_gender: str, label: str) -> None:
    """Validasi induk saat assign/diubah. Lempar ValueError (dipetakan ke 422).

    Dilakukan hanya bila nilai berubah agar data lama yang tak lengkap
    (mis. induk dihapus lama) tetap bisa disimpan apa adanya.
    """
    if not parent_id:
        return
    pid = str(parent_id).strip()
    if not pid:
        return
    if child_id and pid == str(child_id).strip():
        raise ValueError(f"{label} tidak boleh menunjuk diri sendiri")
    parent = db.query(Breeder).filter(Breeder.id == pid).first()
    if parent is None:
        raise ValueError(f"{label} '{pid}' tidak ditemukan sebagai indukan")
    gender = normalize_gender(parent.jenis_kelamin)
    if gender is not None and gender != expected_gender:
        raise ValueError(f"{label} '{pid}' berjenis kelamin {gender}, seharusnya {expected_gender}")
    if child_id and is_ancestor(db, child_id, pid):
        raise ValueError(f"{label} '{pid}' adalah turunan dari {child_id}, siklus silsilah")


def validate_egg_parent(db, parent_id: Optional[str], expected_gender: str, label: str) -> None:
    """Validasi induk telur (bila nilainya baru/berubah). Lempar ValueError."""
    if not parent_id:
        return
    pid = str(parent_id).strip()
    if not pid:
        return
    parent = db.query(Breeder).filter(Breeder.id == pid).first()
    if parent is None:
        raise ValueError(f"{label} '{pid}' tidak ditemukan sebagai indukan")
    gender = normalize_gender(parent.jenis_kelamin)
    if gender is not None and gender != expected_gender:
        raise ValueError(f"{label} '{pid}' berjenis kelamin {gender}, seharusnya {expected_gender}")


def is_ancestor(db, candidate_id: str, of_id: str) -> bool:
    """True bila candidate_id adalah leluhur dari of_id (ikut rantai parent)."""
    frontier = [str(of_id).strip()]
    seen = set()
    while frontier:
        current = frontier.pop()
        if not current or current in seen:
            continue
        seen.add(current)
        if current == candidate_id:
            return True
        row = db.query(Breeder).filter(Breeder.id == current).first()
        if row is None:
            continue
        frontier.extend([p for p in (row.parent_jantan_id, row.parent_betina_id) if p])
    return False


def telur_induk_refs(db, breeder_id: str):
    """(jumlah telur, jumlah anak breeder) yang merujuk breeder_id."""
    n_egg = db.query(Egg.id).filter(
        (Egg.induk_jantan_id == breeder_id) | (Egg.induk_betina_id == breeder_id)
    ).count()
    n_child = db.query(Breeder.id).filter(
        (Breeder.parent_jantan_id == breeder_id) | (Breeder.parent_betina_id == breeder_id)
    ).count()
    return n_egg, n_child


def gender_role_conflicts(db, breeder_id, new_gender) -> List[str]:
    """Daftar relasi yang jadi SALAH bila jenis kelamin breeder diubah.

    Ambil kasusnya: MALE-02 dipakai sebagai `induk_jantan` pada EGG-004. Bila
    jenis kelaminnya diubah jadi "Betina", telur itu otomatis punya induk
    jantan berkelamin betina — relasi yang tidak mungkin. API menolak perubahan
    ini dan menyebut relasi mana yang menghalangi, alih-alih menuliskan data
    yang diam-diam menyimpang.

    Daftar dikembalikan berupa teks siap tampil (maksimal 6 entri + sisa).
    """
    if new_gender == JANTAN:
        salah = BETINA
    elif new_gender == BETINA:
        salah = JANTAN
    else:
        return []

    refs: List[str] = []
    for egg in db.query(Egg).filter(Egg.induk_jantan_id == breeder_id).all():
        refs.append(("Jantan", f"induk jantan telur {egg.id}"))
    for egg in db.query(Egg).filter(Egg.induk_betina_id == breeder_id).all():
        refs.append(("Betina", f"induk betina telur {egg.id}"))
    for child in db.query(Breeder).filter(Breeder.parent_jantan_id == breeder_id).all():
        refs.append(("Jantan", f"parent jantan {child.id}"))
    for child in db.query(Breeder).filter(Breeder.parent_betina_id == breeder_id).all():
        refs.append(("Betina", f"parent betina {child.id}"))
    for chick in db.query(Chick).filter(Chick.induk_jantan_id == breeder_id).all():
        refs.append(("Jantan", f"induk jantan anakan {chick.id}"))
    for chick in db.query(Chick).filter(Chick.induk_betina_id == breeder_id).all():
        refs.append(("Betina", f"induk betina anakan {chick.id}"))

    conflicts = [label for role, label in refs if role == salah]
    if len(conflicts) > 6:
        return conflicts[:6] + [f"... dan {len(conflicts) - 6} relasi lain"]
    return conflicts


def is_legacy(obj_id: str) -> bool:
    if not obj_id:
        return True
    return not (RE_F0.match(obj_id) or RE_ANAK.match(obj_id) or RE_CHICK.match(obj_id))


def _fmt(nomor: int) -> str:
    return f"{nomor:02d}"


def next_nomor(existing_ids, ambil_nomor) -> int:
    nums = [n for n in (ambil_nomor(i) for i in existing_ids) if n is not None]
    return (max(nums) + 1) if nums else 1


def nomor_anak(obj_id: str, jantan: str, betina: str):
    m = RE_ANAK.match(obj_id or "")
    if m and m.group(1) == jantan and m.group(2) == betina:
        return int(m.group(3))
    return None


def nomor_chick(obj_id: str, egg_id: str):
    m = RE_CHICK.match(obj_id or "")
    if m and m.group(1) == egg_id:
        return int(m.group(2))
    return None


def nomor_f0(obj_id: str, kode: str):
    m = RE_F0.match(obj_id or "")
    if m and m.group(1) == kode:
        return int(m.group(2))
    return None


def build_telur(jantan: str, betina: str, nomor: int) -> str:
    return f"{jantan}{betina}-{_fmt(nomor)}"


def build_chick(egg_id: str, nomor: int) -> str:
    return f"{egg_id}-C{_fmt(nomor)}"


def build_f0(jenis_kelamin: str, nomor: int) -> str:
    kode = "JB" if str(jenis_kelamin).strip().lower() == "jantan" else "BB"
    return f"{kode}{_fmt(nomor)}"


def prefix_telur(obj_id: str):
    """Kembalikan (jantan, betina) atau None jika legacy/tidak cocok."""
    m = RE_ANAK.match(obj_id or "")
    return (m.group(1), m.group(2)) if m else None


def prefix_chick(obj_id: str):
    m = RE_CHICK.match(obj_id or "")
    return m.group(1) if m else None


def cek_edit_telur(old_id: str, new_id: str):
    old, new = prefix_telur(old_id), prefix_telur(new_id)
    if old and new and old != new:
        raise ValueError(f"Prefix induk dikunci ({old[0]}{old[1]}). Hanya nomor yang boleh diubah.")


def cek_edit_chick(old_id: str, new_id: str):
    old, new = prefix_chick(old_id), prefix_chick(new_id)
    if old and new and old != new:
        raise ValueError(f"Identitas telur dikunci ({old}). Hanya nomor -C yang boleh diubah.")


def cek_edit_breeder(old_id: str, new_id: str):
    mf0_old, mf0_new = RE_F0.match(old_id or ""), RE_F0.match(new_id or "")
    if mf0_old and mf0_new and mf0_old.group(1) != mf0_new.group(1):
        raise ValueError("Kode kelamin dikunci (JB=jantan, BB=betina). Hanya angka yang boleh diubah.")
    old, new = prefix_telur(old_id), prefix_telur(new_id)
    if old and new and old != new:
        raise ValueError("Prefix induk dikunci. Hanya nomor yang boleh diubah.")
