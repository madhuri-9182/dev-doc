from django.db.models.functions import TruncMonth
from collections import defaultdict
from dashboard.models import BillingRecord

qs_clb = BillingRecord.objects.filter(record_type="CLB")
qs_inp = BillingRecord.objects.filter(record_type="INP")
grouped_clb = defaultdict(list)
grouped_inp = defaultdict(list)

for record in qs_clb:
    key = (record.client_id, record.created_at.replace(day=1).date())
    grouped_clb[key].append(record)

for record in qs_inp:
    key = (record.interviewer_id, record.created_at.replace(day=1).date())
    grouped_inp[key].append(record)


def process_records(grouped):
    for _, records in grouped.items():
        if len(records) > 1:
            main = records[0]
            for r in records[1:]:
                main.amount_due += r.amount_due
                r.delete()
            main.save(update_fields=["amount_due"])


process_records(grouped_clb)
process_records(grouped_inp)


# For clients
# BillingRecord.objects.filter(record_type="CLB").annotate(
#     month=TruncMonth("created_at")
# ).values("client", "month").annotate(count=Count("id")).filter(count__gt=1)

# # For interviewers
# BillingRecord.objects.filter(record_type="INP").annotate(
#     month=TruncMonth("created_at")
# ).values("interviewer", "month").annotate(count=Count("id")).filter(count__gt=1)
