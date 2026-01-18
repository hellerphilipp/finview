import enum
from sqlalchemy import String, ForeignKey, Numeric, Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List
from .base import Base

class Currency(enum.Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CHF = "CHF"
    # Add others as needed

class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    
    # native_enum=False forces SQLite to store this as a simple VARCHAR
    currency: Mapped[Currency] = mapped_column(SqlEnum(Currency, native_enum=False))
    
    transactions: Mapped[List["Transaction"]] = relationship(back_populates="account")

    def __repr__(self):
        # Safety check in case currency is accessed before commit
        curr = self.currency.value if hasattr(self.currency, 'value') else self.currency
        return f"<Account {self.name} ({curr})>"

class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    
    description: Mapped[str] = mapped_column(String(255))
    
    original_value: Mapped[float] = mapped_column(Numeric(10, 2))
    
    # native_enum=False here as well
    original_currency: Mapped[Currency] = mapped_column(SqlEnum(Currency, native_enum=False))
    
    value_in_account_currency: Mapped[float] = mapped_column(Numeric(10, 2))
    date_str: Mapped[str] = mapped_column(String(20)) 

    account: Mapped["Account"] = relationship(back_populates="transactions")