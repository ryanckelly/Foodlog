import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.models.schemas import (
    FoodEntryCreate,
    FoodEntryResponse,
    FoodEntryUpdate,
)
from foodlog.services.logging import EntryService

router = APIRouter(prefix="/entries", tags=["entries"])


@router.post("", status_code=201, response_model=list[FoodEntryResponse])
def create_entries(
    entries: list[FoodEntryCreate],
    db: Session = Depends(get_db),
):
    svc = EntryService(db)
    return svc.create_many(entries)


@router.get("", response_model=list[FoodEntryResponse])
def get_entries(
    date: datetime.date | None = None,
    meal_type: str | None = None,
    db: Session = Depends(get_db),
):
    svc = EntryService(db)
    target_date = date or datetime.date.today()
    return svc.get_by_date(target_date, meal_type=meal_type)


@router.put("/{entry_id}", response_model=FoodEntryResponse)
def update_entry(
    entry_id: int,
    data: FoodEntryUpdate,
    db: Session = Depends(get_db),
):
    svc = EntryService(db)
    entry = svc.update(entry_id, data)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.delete("/{entry_id}", status_code=204)
def delete_entry(
    entry_id: int,
    db: Session = Depends(get_db),
):
    svc = EntryService(db)
    if not svc.delete(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return Response(status_code=204)
