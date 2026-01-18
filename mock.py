from models.finance import Account, Transaction, Currency
from datetime import datetime, timedelta
import random

def get_mock_data():
    accounts = [
        Account(id=1, name="Checking Account", currency=Currency.USD),
        Account(id=2, name="Savings", currency=Currency.USD),
        Account(id=3, name="Travel Fund", currency=Currency.EUR),
    ]
    
    all_transactions = []
    for acc in accounts:
        for i in range(50):  # 50 transactions per account
            val = round(random.uniform(-500.0, 1000.0), 2)
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            tx = Transaction(
                id=len(all_transactions) + 1,
                account_id=acc.id,
                description=f"Transaction {i} for {acc.name}",
                original_value=val,
                original_currency=acc.currency,
                value_in_account_currency=val,
                date_str=date,
                account=acc
            )
            all_transactions.append(tx)
        acc.transactions = [t for t in all_transactions if t.account_id == acc.id]
        
    return accounts
