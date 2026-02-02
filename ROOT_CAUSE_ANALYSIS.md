# Root Cause Analysis: Student 2374 Payment Allocation Issue

## Timeline
- **Jan 21, 2026 13:58**: Invoice issued and payment made (everything OK)
- **Morning (Feb 2, 2026)**: Audit check passed
- **Feb 2, 2026 11:33**: Student `updated_at` timestamp changed
- **Afternoon (Feb 2, 2026)**: Audit check shows discrepancies

## Root Cause Identified

### The Problem Chain:

1. **Invoice Save Triggers Student Update**
   - Every time an `Invoice.save()` is called, it triggers `student.recompute_outstanding_balance()` (line 305 in `finance/models.py`)
   - `recompute_outstanding_balance()` calls `student.save()` which updates `student.updated_at`
   - **This explains why student was updated at 11:33 on Feb 2**

2. **What Could Have Saved the Invoice at 11:33?**
   - Payment allocation recalculation
   - Invoice edit/view that triggered save
   - Bulk operation
   - Term transition (but only processes active students)

3. **The Core Issue:**
   - Student 2374 is **TRANSFERRED** but has an **ACTIVE invoice**
   - When a student is transferred, invoices should be deactivated (`is_active=False`)
   - The payment allocation logic checks for active invoices and allocates payments to them
   - **For transferred students, payments should go directly to `outstanding_balance`, NOT to invoices**

4. **Why the Discrepancy?**
   - Payment of 20,000 was allocated to invoice items
   - This reduced the invoice balance from 75,250 to 55,250
   - But for a transferred student:
     - Invoice should be inactive
     - Payment should reduce `outstanding_balance` directly
     - Invoice balance should remain at 75,250 (original)
     - Student `outstanding_balance` should be 55,250 (after payment)

## The Bug

**Location**: `payments/services/payment.py` and `payments/services/invoice.py`

**Issue**: Payment allocation logic doesn't check if student is transferred/graduated before allocating to invoices.

**What Happened**:
1. Student was transferred (invoices should have been deactivated)
2. Payment was made/processed
3. Payment allocation logic found active invoice (shouldn't exist)
4. Payment was allocated to invoice items
5. Invoice balance was recalculated (reduced by 20,000)
6. Student `outstanding_balance` was recalculated from invoice balance
7. This created the discrepancy

## Fixes Applied

1. **Added Safeguards** (✅ Already implemented):
   - `payments/services/payment.py`: Check student status before allocating
   - `payments/services/invoice.py`: Prevent allocation for transferred/graduated students

2. **Created Fix Command** (✅ Already created):
   - `fix_transferred_student_payment.py`: Fixes the data for student 2374

3. **Fixed Receipt Calculation** (✅ Already implemented):
   - `finance/views.py`: Handle transferred students correctly in receipt view

## What Needs to Happen

1. **Run the fix command** to correct the data:
   ```bash
   heroku run python manage.py fix_transferred_student_payment --admission-number 2374
   ```

2. **Verify the fix**:
   ```bash
   heroku run python manage.py audit
   ```

3. **Prevent Future Issues**:
   - The safeguards are already in place
   - Ensure invoices are properly deactivated when students are transferred
   - Consider adding a check in invoice save to prevent saving invoices for transferred students

## Additional Investigation Needed

To find out exactly what triggered the invoice save at 11:33, check:
1. Heroku logs around 11:33 on Feb 2
2. Any scheduled tasks or cron jobs
3. Any bulk operations that might have run
4. Any manual invoice edits

## Prevention

Consider adding a check in `Invoice.save()` to prevent saving invoices for transferred/graduated students:

```python
def save(self, *args, **kwargs):
    if self.student.status in ['transferred', 'graduated']:
        if self.is_active:
            logger.warning(
                f"Attempting to save active invoice {self.invoice_number} "
                f"for {self.student.status} student {self.student.admission_number}. "
                f"Setting is_active=False."
            )
            self.is_active = False
    # ... rest of save logic
```

