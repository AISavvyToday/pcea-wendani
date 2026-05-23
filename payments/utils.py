def get_payment_external_reference(payment):
    """
    Return the real M-Pesa/bank reference for a payment.

    Legacy records sometimes kept the bank reference only on the linked
    BankTransaction, while Payment.transaction_reference held another value.
    """
    if not payment:
        return ""

    bank_transactions = getattr(payment, "bank_transactions", None)
    if bank_transactions is not None:
        try:
            bank_tx = bank_transactions.order_by("created_at", "id").first()
            if bank_tx and bank_tx.transaction_id:
                return bank_tx.transaction_id
        except Exception:
            pass

    return getattr(payment, "transaction_reference", "") or ""


def get_payment_student_bill_reference(payment):
    """Return the student/bill reference captured by the gateway, when present."""
    if not payment:
        return ""

    bank_transactions = getattr(payment, "bank_transactions", None)
    if bank_transactions is not None:
        try:
            bank_tx = bank_transactions.order_by("created_at", "id").first()
            if bank_tx and bank_tx.transaction_reference:
                return bank_tx.transaction_reference
        except Exception:
            pass

    return ""
