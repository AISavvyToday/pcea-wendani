-- SQL commands to fix the specific invoice (PWA2374)
-- Run this AFTER migrations 0008, 0009, and 0010 are applied

BEGIN;

-- Update amount_paid (adds 20k to Collected stat)
UPDATE invoices 
SET amount_paid = amount_paid + 20000.00
WHERE id = '69c04e3d-0bcf-4f8d-bb85-8351d4117a3c';

-- Set balance_bf_original to original frozen value (44250.00)
-- This is the original balance_bf before the payment was made
UPDATE invoices 
SET balance_bf_original = 44250.00
WHERE id = '69c04e3d-0bcf-4f8d-bb85-8351d4117a3c';

-- Recalculate balance
UPDATE invoices 
SET balance = total_amount + balance_bf + prepayment - amount_paid
WHERE id = '69c04e3d-0bcf-4f8d-bb85-8351d4117a3c';

-- Update status if needed
UPDATE invoices 
SET status = CASE 
    WHEN balance <= 0 THEN 'paid'
    WHEN amount_paid > 0 THEN 'partially_paid'
    ELSE status
END
WHERE id = '69c04e3d-0bcf-4f8d-bb85-8351d4117a3c';

COMMIT;

-- Verify the changes
SELECT 
    invoice_number,
    balance_bf,
    balance_bf_original,
    amount_paid,
    total_amount,
    balance,
    status
FROM invoices
WHERE id = '69c04e3d-0bcf-4f8d-bb85-8351d4117a3c';

