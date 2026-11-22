# Sales hook (for when the Sales backend is added)

Your repo has no Sales backend yet, so nothing consumes lots yet. When Sales is added it needs exactly two calls
(I already tested both against my Sales module: sold 3 cylinders from lots bought at 1,300 and 1,400, cancelled, and
the lots came back):

In `sale_create`, inside the per-item loop, right after the line that computes `full_d` (the full cylinders leaving = refill + with_cylinder):

    if r + w:
        lots.consume_fifo(db, tid, r + w, "sale", sale_id)

In `sale_cancel`, once, just before the `UPDATE sales SET status = 'cancelled'`:

    lots.restore(db, "sale", sale_id)

and `import lots` at the top. Profit of a sale = (rate × cylinders) − `lots.cost_of(db, "sale", sale_id)`.
