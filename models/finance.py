# FinView — terminal-based personal finance manager
# Copyright (C) 2026 Philipp Heller
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import enum
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, ForeignKey, Numeric, Enum as SqlEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List
from .base import Base

class Currency(enum.Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CHF = "CHF"

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    currency: Mapped[Currency] = mapped_column(SqlEnum(Currency, native_enum=False))
    mapping_spec: Mapped[str | None] = mapped_column(String(255))
    
    transactions: Mapped[List["Transaction"]] = relationship(back_populates="account")

    def __repr__(self):
        return f"<Account {self.name}>"

class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    description: Mapped[str] = mapped_column(String(255))
    original_value: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    original_currency: Mapped[Currency] = mapped_column(SqlEnum(Currency, native_enum=False))
    value_in_account_currency: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    
    date: Mapped[datetime] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    split_parent_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    merge_parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL")
    )

    account: Mapped["Account"] = relationship(back_populates="transactions")
    split_parent: Mapped["Transaction | None"] = relationship(
        "Transaction", remote_side=[id], foreign_keys=[split_parent_id], back_populates="split_children"
    )
    split_children: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="split_parent", cascade="all, delete-orphan",
        foreign_keys="[Transaction.split_parent_id]"
    )
    merge_parent: Mapped["Transaction | None"] = relationship(
        "Transaction", remote_side=[id], foreign_keys=[merge_parent_id],
        back_populates="merge_children"
    )
    merge_children: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="merge_parent",
        foreign_keys="[Transaction.merge_parent_id]"
    )