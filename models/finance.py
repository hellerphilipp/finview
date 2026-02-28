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

    parent_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    merge_parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL")
    )

    account: Mapped["Account"] = relationship(back_populates="transactions")
    parent: Mapped["Transaction | None"] = relationship(
        "Transaction", remote_side=[id], foreign_keys=[parent_id], back_populates="children"
    )
    children: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="parent", cascade="all, delete-orphan",
        foreign_keys="[Transaction.parent_id]"
    )
    merge_parent: Mapped["Transaction | None"] = relationship(
        "Transaction", remote_side=[id], foreign_keys=[merge_parent_id],
        back_populates="merge_children"
    )
    merge_children: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="merge_parent",
        foreign_keys="[Transaction.merge_parent_id]"
    )