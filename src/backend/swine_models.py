"""
Pydantic models for swine period reports.
Put this file next to main.py and swine_reports.py (src/backend/swine_models.py).
Requires Pydantic v2.
"""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

CATS = ("boar", "sow", "gilts", "piglets", "grower_fattener")
IN_TYPES = ("birth", "purchase", "transfer_in")
OUT_TYPES = ("sale", "slaughter", "death", "transfer_out", "depopulated")

CatName = Literal["boar", "sow", "gilts", "piglets", "grower_fattener"]
MovementType = Literal[
    "birth", "purchase", "transfer_in",
    "sale", "slaughter", "death", "transfer_out", "depopulated",
]


class MovementIn(BaseModel):
    movement_type: MovementType
    category: Optional[CatName] = None  # None for total-only reports
    quantity: int = Field(gt=0)


class PeriodReportBody(BaseModel):
    """What a farmer sends. The farmer id comes from the login token."""
    period_type: Literal["monthly", "quarterly"]
    period_end: date
    report_mode: Literal["total", "category"] = "category"  # not stored in the DB
    total: Optional[int] = Field(default=None, ge=0)
    counts: dict[str, int] = Field(default_factory=dict)
    movements: list[MovementIn] = Field(default_factory=list)
    remarks: Optional[str] = None

    @model_validator(mode="after")
    def check_shape(self):
        if self.period_end > date.today():
            raise ValueError("The count date cannot be in the future.")

        if self.report_mode == "total":
            if self.total is None:
                raise ValueError("Enter the total number of swine on hand.")
            if any(self.counts.values()):
                raise ValueError("A total-only report cannot include category counts.")
            if any(m.category is not None for m in self.movements):
                raise ValueError("A total-only report cannot have movements by category.")
        else:
            unknown = set(self.counts) - set(CATS)
            if unknown:
                raise ValueError(f"Unknown categories: {', '.join(sorted(unknown))}.")
            if any(v < 0 for v in self.counts.values()):
                raise ValueError("Counts cannot be negative.")
            # "total" may be larger than the category counts: the difference is the animals
            # not broken down yet. Movements without a category refer to those animals.
            if self.total is not None and self.total < sum(self.counts.values()):
                raise ValueError("The total cannot be less than the category counts.")
        return self

    @property
    def closing_total(self) -> int:
        return self.total if self.total is not None else sum(self.counts.values())


class SwineReportIn(PeriodReportBody):
    """Staff endpoint: adds the fields that staff choose."""
    farmer_id: int
    reported_by_role: Literal["staff", "farmer"]
    reported_by_user: Optional[str] = None