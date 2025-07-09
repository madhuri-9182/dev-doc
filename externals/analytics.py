from math import gcd
from django.db.models import Count, Q
from collections import defaultdict
from dashboard.models import Candidate


def get_candidate_analytics(candidates):
    def simplify_ratio(selected_count, total_count):
        factor = gcd(selected_count, total_count)
        if not factor:
            return 0, 0
        return selected_count // factor, total_count // factor

    analytics = candidates.aggregate(
        total_candidates=Count("id"),
        total_interviews=Count(
            "id", filter=Q(status__in=["NJ", "HREC", "REC", "NREC", "SNREC"])
        ),
        total_candidates_appearing_for_interview=Count(
            "id", filter=Q(status__in=["HREC", "REC", "NREC", "SNREC"])
        ),
        total_rejected_candidates=Count("id", filter=Q(status__in=["NREC", "SNREC"])),
        total_selected_candidates=Count("id", filter=Q(status__in=["REC", "HREC"])),
        top_performers=Count("id", filter=Q(score__gte=90)),
        good_candidates=Count("id", filter=Q(score__gte=60, score__lt=90)),
        declined_by_candidate=Count("id", filter=Q(status="NJ")),
        male_count=Count("id", filter=Q(gender="M")),
        female_count=Count("id", filter=Q(gender__in=["F", "TG"])),
        total_female_selected_candidates=Count(
            "id", filter=Q(gender="F", status__in=["HREC", "REC"])
        ),
    )

    # Group selected and rejected by current company
    candidates_by_companies = (
        candidates.filter(status__in=["HREC", "REC", "NREC", "SNREC"])
        .values("company")
        .annotate(
            selected_count=Count("id", filter=Q(status__in=["HREC", "REC"])),
            rejected_count=Count("id", filter=Q(status__in=["NREC", "SNREC"])),
        )
    )

    total_selected_candidates = analytics.pop("total_selected_candidates")
    total_rejected_candidates = analytics["total_rejected_candidates"]

    selected_dict = {}
    rejected_dict = {}

    if total_selected_candidates:
        selected_dict = {
            entry["company"]: int(
                (entry["selected_count"] / total_selected_candidates) * 100
            )
            for entry in candidates_by_companies
            if entry["selected_count"]
        }

    if total_rejected_candidates:
        rejected_dict = {
            entry["company"]: int(
                (entry["rejected_count"] / total_rejected_candidates) * 100
            )
            for entry in candidates_by_companies
            if entry["rejected_count"]
        }

    # Ratios
    total_female_selected_candidates = analytics.pop("total_female_selected_candidates")
    total_candidates_appearing_for_interview = analytics.pop(
        "total_candidates_appearing_for_interview"
    )

    ratio = simplify_ratio(
        total_selected_candidates, total_candidates_appearing_for_interview
    )
    selection_ratio = f"{ratio[0]}:{ratio[1]}" if total_selected_candidates else "0:0"

    diversity_ratio = f"{total_female_selected_candidates}:{total_selected_candidates - total_female_selected_candidates}"

    return {
        "status_info": analytics,
        "selected_candidates": selected_dict,
        "rejected_candidates": rejected_dict,
        "ratio_details": {
            "selection_ratio": selection_ratio,
            "selection_ratio_for_diversity": diversity_ratio,
            "total_male_vs_female": f"{analytics['male_count']}:{analytics['female_count']}",
        },
    }
