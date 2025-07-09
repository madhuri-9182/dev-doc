from drf_spectacular.utils import extend_schema
from django.db import transaction
from django.db.models import Count, Q, Case, When, IntegerField, Min
from django.utils import timezone
from organizations.models import Organization
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from core.permissions import IsSuperAdmin, IsModerator, IsAdmin
from ..models import (
    InternalClient,
    InternalInterviewer,
    Agreement,
    Job,
    Candidate,
    ClientUser,
    HDIPUsers,
    DesignationDomain,
    InterviewerAvailability,
    Interview,
)
from ..serializer import (
    InternalClientSerializer,
    InterviewerSerializer,
    OrganizationSerializer,
    InternalClientUserSerializer,
    HDIPUsersSerializer,
    DesignationDomainSerializer,
    InternalClientStatSerializer,
    InternalClientDomainSerializer,
    OrganizationAgreementSerializer,
)


class InternalClientDomainView(APIView, LimitOffsetPagination):
    permission_classes = [IsAuthenticated, IsModerator | IsSuperAdmin | IsAdmin]
    serializer_class = InternalClientDomainSerializer

    def get(self, request):
        client_domain_qs = InternalClient.objects.values(
            "domain"
        ).annotate(  # Group by domain
            id=Min("id")
        )  # Pick the min id per domain
        paginated_qs = self.paginate_queryset(client_domain_qs, request)
        serializer = self.serializer_class(paginated_qs, many=True)
        paginated_response = self.get_paginated_response(serializer.data)
        return Response(
            {
                "status": "success",
                "message": "Successfully retrieved client's domain",
                **paginated_response.data,
            }
        )


class InternalEngagementView(APIView, LimitOffsetPagination):
    permission_classes = [IsAuthenticated, IsModerator | IsSuperAdmin | IsAdmin]

    def get(self, request):
        domains = request.query_params.get("domain")
        status_ = request.query_params.get("status")
        search_term = request.query_params.get("q")

        qs = Organization.objects.prefetch_related("candidate").order_by("-id")

        if domains:
            qs = qs.filter(internal_client__domain__in=domains.split(","))

        if status_:
            status_list = [
                True if status == "active" else False for status in status_.split(",")
            ]
            qs = qs.filter(is_active__in=status_list)

        if search_term:
            qs = qs.filter(name__icontains=search_term.lower())

        # Annotate each organization with candidate engagement details
        qs = qs.annotate(
            active_candidates=Count(
                "candidate",
                filter=Q(candidate__final_selection_status="SLD"),
                distinct=True,
            ),  # Count of candidates per organization
            scheduled=Count(
                "candidate",
                filter=Q(candidate__engagements__isnull=False)
                & Q(candidate__final_selection_status="SLD"),
                distinct=True,
            ),
            pending_scheduled=Count(
                "candidate",
                filter=Q(candidate__engagements__isnull=True)
                & Q(candidate__final_selection_status="SLD"),
                distinct=True,
            ),
        )

        # Select the fields to return
        qs_values = qs.values(
            "id",
            "name",
            "active_candidates",
            "scheduled",
            "pending_scheduled",
            # Add other fields as needed
        )

        # Paginate the queryset
        paginated_qs = self.paginate_queryset(qs_values, request)
        paginated_response = self.get_paginated_response(paginated_qs)

        return Response(
            {
                "status": "success",
                "message": "Successfully retrieved engagements",
                **paginated_response.data,
            }
        )


@extend_schema(tags=["Internal"])
class InternalClientView(APIView, LimitOffsetPagination):
    serializer_class = InternalClientSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin | IsModerator | IsAdmin]

    def get(self, request):
        client_ids = request.query_params.get("client_ids")
        domains = request.query_params.get("domain")
        status_ = request.query_params.get("status")
        search_term = request.query_params.get("q")

        query = InternalClient.objects.order_by("-id").values("id", "name")

        if client_ids:
            query = query.filter(pk__in=client_ids.split(","))

        if domains:
            query = query.filter(domain__in=domains.split(","))

        if status_:
            status_list = [
                True if status == "active" else False for status in status_.split(",")
            ]
            query = query.filter(is_signed__in=status_list)

        if search_term:
            query = query.filter(name__icontains=search_term.lower())

        client_stat = query.annotate(
            active_jobs=Count(
                "organization__clientuser__jobs",
                filter=Q(organization__clientuser__jobs__archived=False),
                distinct=True,
            ),
            passive_jobs=Count(
                "organization__clientuser__jobs",
                filter=Q(organization__clientuser__jobs__archived=True),
                distinct=True,
            ),
            total_candidates=Count(
                "organization__candidate",
                distinct=True,
            ),
        )
        # remember to add the role based retreival after creating the hdip user functionality
        paginated_queryset = self.paginate_queryset(client_stat, request)
        serializer = InternalClientStatSerializer(paginated_queryset, many=True)
        paginated_data = self.get_paginated_response(serializer.data)
        return Response(
            {
                "status": "success",
                "message": "Client user retrieve successfully.",
                **paginated_data.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": "success",
                    "message": "Client user added successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(
            {
                "status": "failed",
                "message": "Invalid data.",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def finalize_response(self, request, response, *args, **kwargs):
        if response.data.get("errors"):
            response.data["status"] = "failed"
            response.data["message"] = response.data.get("message", "Invalid data")
            errors = response.data["errors"]
            del response.data["errors"]
            response.data["errors"] = errors
        return super().finalize_response(request, response, *args, **kwargs)


@extend_schema(tags=["Internal"])
class InternalClientDetailsView(APIView):
    serializer_class = InternalClientSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin | IsModerator | IsAdmin]

    def get(self, request, pk):

        try:
            client = InternalClient.objects.get(pk=pk)
        except InternalClient.DoesNotExist:
            return Response(
                {"errors": "Client not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.serializer_class(client)
        return Response(
            {
                "status": "success",
                "message": "Client data retrieved successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        try:
            client = InternalClient.objects.get(pk=pk)
        except InternalClient.DoesNotExist:
            return Response(
                {"errors": "Client not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.serializer_class(
            client, data=request.data, partial=True, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": "success",
                    "message": "Client data updated successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        return Response(
            {
                "status": "failed",
                "message": "Invalid data.",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def delete(self, request, pk):
        try:
            client = InternalClient.objects.get(pk=pk)
        except InternalClient.DoesNotExist:
            return Response(
                {"errors": "Client not found"}, status=status.HTTP_404_NOT_FOUND
            )

        client.archived = True
        client.save()
        return Response(
            {
                "status": "success",
                "message": "Client data deleted successfully.",
            },
            status=status.HTTP_204_NO_CONTENT,
        )

    def finalize_response(self, request, response, *args, **kwargs):
        if response.data.get("errors"):
            response.data["status"] = "failed"
            response.data["message"] = response.data.get("message", "Invalid data")
            errors = response.data["errors"]
            del response.data["errors"]
            response.data["errors"] = errors
        return super().finalize_response(request, response, *args, **kwargs)


@extend_schema(tags=["Internal"])
class InterviewerView(APIView, LimitOffsetPagination):
    serializer_class = InterviewerSerializer
    permission_classes = [IsAuthenticated, IsModerator | IsSuperAdmin | IsAdmin]

    def get(self, request):
        strengths = request.query_params.get("strengths", "")
        experiences = request.query_params.get("experiences", "")
        search_terms = request.query_params.get("q")

        # Validate strengths
        if strengths:
            strengths = strengths.split(",")
            valid_strengths = dict(InternalInterviewer.STRENGTH_CHOICES).keys()
            invalid_strengths = [s for s in strengths if s not in valid_strengths]
            if invalid_strengths:
                return Response(
                    {
                        "status": "failed",
                        "message": f"Invalid strengths: {', '.join(invalid_strengths)}. Valid strengths are {', '.join(valid_strengths)}",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Validate experiences
        experience_choices = {
            "0-4": ("lte", 4),
            "5-8": ("range", (5, 8)),
            "9-10": ("range", (9, 10)),
            "11": ("gt", 11),
        }
        if experiences:
            experiences = experiences.split(",")
            invalid_experiences = [
                e for e in experiences if e not in experience_choices
            ]
            if invalid_experiences:
                valid_experience_choices = ", ".join(experience_choices.keys())
                return Response(
                    {
                        "status": "failed",
                        "message": f"Invalid experiences: {', '.join(invalid_experiences)}. Valid choices are {valid_experience_choices}",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Filter interviewers based on query parameters
        filters = Q()
        if experiences:
            for experience in experiences:
                filters |= Q(
                    **{
                        f"total_experience_years__{experience_choices[experience][0]}": experience_choices[
                            experience
                        ][
                            1
                        ]
                    }
                )
        if strengths:
            filters &= Q(strength__in=strengths)

        interviewers_qs = InternalInterviewer.objects.filter(filters).order_by("-id")

        if search_terms:
            interviewers_qs = interviewers_qs.filter(
                Q(name__icontains=search_terms)
                | Q(email__icontains=search_terms)
                | Q(phone_number=search_terms)
            )

        # Aggregate interviewer data
        interviewers_aggregation = InternalInterviewer.objects.aggregate(
            total_interviewers=Count("id"),
            years_0_4=Count("id", filter=Q(total_experience_years__lte=4)),
            years_5_8=Count("id", filter=Q(total_experience_years__range=(5, 8))),
            years_9_10=Count("id", filter=Q(total_experience_years__range=(9, 10))),
            years_11=Count("id", filter=Q(total_experience_years__gt=11)),
        )

        # Paginate and serialize the results
        paginated_qs = self.paginate_queryset(interviewers_qs, request)
        serializer = self.serializer_class(paginated_qs, many=True)
        paginated_data = self.get_paginated_response(serializer.data)

        return Response(
            {
                "status": "success",
                "message": "Interviewer list retrieved successfully.",
                **interviewers_aggregation,
                **paginated_data.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": "success",
                    "message": "Interviewer added successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        custom_error = serializer.errors.pop("errors", None)
        return Response(
            {
                "status": "failed",
                "message": "Invalid data.",
                "errors": serializer.errors if not custom_error else custom_error,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def finalize_response(self, request, response, *args, **kwargs):
        if response.data.get("errors"):
            response.data["status"] = "failed"
            response.data["message"] = response.data.get("message", "Invalid data")
            errors = response.data["errors"]
            del response.data["errors"]
            response.data["errors"] = errors
        return super().finalize_response(request, response, *args, **kwargs)


@extend_schema(tags=["Internal"])
class InterviewerDetails(APIView):
    serializer_class = InterviewerSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin | IsModerator | IsAdmin]

    def get(self, request, pk):
        try:
            interviewer = InternalInterviewer.objects.get(pk=pk)
        except InternalInterviewer.DoesNotExist:
            return Response(
                {"errors": "Interviewer not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.serializer_class(interviewer)
        return Response(
            {
                "status": "success",
                "message": "Interviewer data successfully retrived.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        try:
            interviewer = InternalInterviewer.objects.get(pk=pk)
        except InternalInterviewer.DoesNotExist:
            return Response(
                {
                    "status": "failed",
                    "message": "Interviewer not found",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.serializer_class(interviewer, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": "success",
                    "message": "Interviewer added successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        custom_error = serializer.errors.pop("errors", None)

        return Response(
            {
                "status": "failed",
                "message": "Invalid data.",
                "errors": serializer.errors if not custom_error else custom_error,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    @transaction.atomic
    def delete(self, request, pk):
        try:
            interviewer = InternalInterviewer.objects.get(pk=pk)
            interview = Interview.objects.filter(interviewer=interviewer, status="CSCH")
            if interview.exists():
                return Response(
                    {
                        "status": "failed",
                        "message": f"Interviewer cannot be dropped as it has {interview.count()} scheduled interviews",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Archive future availability
            InterviewerAvailability.objects.filter(
                interviewer=interviewer, date__gte=timezone.now()
            ).update(archived=True)

            # Archive interviewer and deactivate user
            interviewer.archived = True
            interviewer.user.is_active = False
            interviewer.user.save(update_fields=["is_active"])
            interviewer.save(update_fields=["archived"])

            return Response(
                {"status": "success", "message": "Interviewer deleted successfully"},
                status=status.HTTP_204_NO_CONTENT,
            )
        except InternalInterviewer.DoesNotExist:
            return Response(
                {"status": "failed", "message": "Interviewer not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def finalize_response(self, request, response, *args, **kwargs):
        if response.data.get("errors"):
            response.data["status"] = "failed"
            response.data["message"] = response.data.get("message", "Invalid data")
            errors = response.data["errors"]
            del response.data["errors"]
            response.data["errors"] = errors
        return super().finalize_response(request, response, *args, **kwargs)


class DomainDesignationView(APIView, LimitOffsetPagination):
    permission_classes = [IsAuthenticated]
    serializer_class = DesignationDomainSerializer

    def get_matching_db_values(self, choices, search_param):
        return [db for db, label in choices if search_param in label.lower()]

    def get(self, request):
        search_param = request.query_params.get("q")
        domain_qs = DesignationDomain.objects.all()

        if search_param:
            domain_qs = domain_qs.filter(
                name__in=self.get_matching_db_values(
                    InternalInterviewer.ROLE_CHOICES, search_param.lower()
                )
            )

        paginated_qs = self.paginate_queryset(domain_qs, request)
        serializer = self.serializer_class(paginated_qs, many=True)
        paginated_response = self.get_paginated_response(serializer.data)
        return Response(
            {
                "status": "success",
                "message": "Retrieved Successfully",
                **paginated_response.data,
            }
        )


@extend_schema(tags=["Internal"])
class OrganizationAgreementView(APIView, LimitOffsetPagination):
    serializer_class = OrganizationAgreementSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin | IsModerator | IsAdmin]

    def get(self, request):
        search_term = request.query_params.get("q")
        agreements_qs = Organization.objects.prefetch_related("agreements").order_by(
            "-id"
        )

        agreements_qs = agreements_qs.annotate(
            experience_0_4=Count(
                Case(
                    When(agreements__years_of_experience="0-4", then=1),
                    output_field=IntegerField(),
                )
            ),
            experience_4_6=Count(
                Case(
                    When(agreements__years_of_experience="4-6", then=1),
                    output_field=IntegerField(),
                )
            ),
            experience_6_8=Count(
                Case(
                    When(agreements__years_of_experience="6-8", then=1),
                    output_field=IntegerField(),
                )
            ),
            experience_8_10=Count(
                Case(
                    When(agreements__years_of_experience="8-10", then=1),
                    output_field=IntegerField(),
                )
            ),
            experience_10_plus=Count(
                Case(
                    When(agreements__years_of_experience="10+", then=1),
                    output_field=IntegerField(),
                )
            ),
        ).filter(
            Q(experience_0_4__gt=0)
            & Q(experience_4_6__gt=0)
            & Q(experience_6_8__gt=0)
            & Q(experience_8_10__gt=0)
            & Q(experience_10_plus__gt=0)
        )

        if search_term:
            agreements_qs = agreements_qs.filter(name__icontains=search_term)

        paginated_qs = self.paginate_queryset(agreements_qs, request)
        serializer = self.serializer_class(paginated_qs, many=True)
        paginated_data = self.get_paginated_response(serializer.data)

        return Response(
            {
                "status": "success",
                "message": "Agreement list retrieved successfully.",
                **paginated_data.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": "success",
                    "message": "Agreement added successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        custom_error = serializer.errors.pop("errors", None)
        return Response(
            {
                "status": "failed",
                "message": "Invalid data.",
                "errors": serializer.errors if not custom_error else custom_error,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@extend_schema(tags=["Internal"])
class OrganizationAgreementDetailView(APIView):
    serializer_class = OrganizationAgreementSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin | IsModerator | IsAdmin]

    def get(self, request, pk):
        try:
            agreement = Organization.objects.get(pk=pk)
        except Organization.DoesNotExist:
            return Response(
                {"errors": "Agreement not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.serializer_class(agreement)
        return Response(
            {
                "status": "success",
                "message": "Agreement successfully retrieved.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request, organization_id):
        try:
            organization_agreement = Organization.objects.get(pk=organization_id)
        except Organization.DoesNotExist:
            return Response(
                {
                    "status": "failed",
                    "message": "Agreement not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.serializer_class(
            organization_agreement,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": "success",
                    "message": "Agreement updated successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        custom_error = serializer.errors.pop("errors", None)
        return Response(
            {
                "status": "failed",
                "message": "Invalid data.",
                "errors": serializer.errors if not custom_error else custom_error,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def delete(self, request, pk):
        try:
            agreement = Agreement.objects.get(pk=pk)
        except Agreement.DoesNotExist:
            return Response(
                {
                    "status": "failed",
                    "message": "Agreement not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        agreement.archived = True
        agreement.save()
        return Response(
            {
                "status": "success",
                "message": "Agreement deleted successfully.",
            },
            status=status.HTTP_204_NO_CONTENT,
        )


class OrganizationView(APIView, LimitOffsetPagination):
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated, IsModerator | IsSuperAdmin | IsAdmin]

    def get(self, request):
        filter_criteria = (
            {"agreements__isnull": True}
            if request.resolver_match.url_name == "agreement-organization"
            else {"internal_client__assigned_to__isnull": True}
        )
        organization = Organization.objects.filter(**filter_criteria)
        paginated_queryset = self.paginate_queryset(organization, request)
        serializer = self.serializer_class(paginated_queryset, many=True)
        paginated_response = self.get_paginated_response(serializer.data)

        return Response(
            {
                "status": "success",
                "message": "Organization list retrieved successfully.",
                **paginated_response.data,
            },
            status=status.HTTP_200_OK,
        )


class InternalDashboardView(APIView):
    permission_classes = (IsAuthenticated, IsModerator | IsSuperAdmin | IsAdmin)

    def get(self, request):

        interviewers_stats = InternalInterviewer.objects.aggregate(
            total=Count("id"),
            pending_acceptance=Count(
                "interview_requests", filter=Q(interview_requests__status="pending")
            ),
            interview_declined=Count(
                "interview_requests", filter=Q(interview_requests__status="rejected")
            ),
        )

        candidates_stats = Candidate.objects.aggregate(
            recommended=Count("id", filter=Q(status="recommended")),
            rejected=Count("id", filter=Q(final_selection_status="rejected")),
            strong_candidates=Count("id", filter=Q(status="Highly Recommended")),
            scheduled=Count("id", filter=Q(status="scheduled")),
        )

        clients_stats = ClientUser.objects.aggregate(
            active_clients=Count("id", filter=Q(status="Active")),
            passive_clients=Count("id", filter=Q(status="Inactive")),
            pending_onboarding=Count("id", filter=Q(status="pending")),
            client_users=Count("id"),
        )

        general_stats = InternalInterviewer.objects.aggregate(
            total_interviewers=Count("id"),
            new_interviewers=Count("id", filter=Q(created_at__gte="2025-03-01")),
        )

        active_jobs = Job.objects.filter(reason_for_archived=False).count()
        total_candidates = Candidate.objects.count()

        response_data = {
            "interviewers": {**interviewers_stats, **candidates_stats},
            "clients": clients_stats,
            "details": {
                **general_stats,
                "active_jobs": active_jobs,
                "total_candidates": total_candidates,
            },
        }

        return Response(
            {
                "status": "success",
                "message": "Internal data retrieved successfully.",
                "data": response_data,
            },
            status=status.HTTP_200_OK,
        )


class InternalClientUserView(APIView, LimitOffsetPagination):
    serializer_class = InternalClientUserSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin | IsModerator | IsAdmin]

    def get(self, request, **kwrags):
        search_term = request.query_params.get("q")

        internal_user = ClientUser.objects.select_related(
            "organization", "organization__internal_client"
        ).order_by("organization__name")

        if search_term:
            internal_user = internal_user.filter(
                Q(organization__name__icontains=search_term)
                | Q(name__icontains=search_term)
                | Q(user__email__icontains=search_term)
            )

        paginated_queryset = self.paginate_queryset(internal_user, request)
        serializer = self.serializer_class(paginated_queryset, many=True)
        paginated_response = self.get_paginated_response(serializer.data)
        return Response(
            {
                "status": "success",
                "message": "internal user retrieve successfully.",
                **paginated_response.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, **kwargs):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": "success",
                    "message": "internal user added successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        custom_errors = serializer.errors.pop("errors", None)
        return Response(
            {
                "status": "failed",
                "message": "Invalid data.",
                "errors": serializer.errors if not custom_errors else custom_errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def patch(self, request, **kwargs):
        pk = kwargs.get("pk")
        if not pk:
            return Response(
                {"status": "failed", "message": "Invalid request"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            internal_client_user = ClientUser.objects.get(pk=pk)
        except ClientUser.DoesNotExist:
            return Response(
                {
                    "status": "failed",
                    "message": "User not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.serializer_class(
            internal_client_user,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": "success",
                    "message": "internal user data updated successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        custom_errors = serializer.errors.pop("errors", None)
        return Response(
            {
                "status": "failed",
                "message": "Invalid data.",
                "errors": serializer.errors if not custom_errors else custom_errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


class HDIPUsersViews(APIView, LimitOffsetPagination):
    serializer_class = HDIPUsersSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin | IsModerator | IsAdmin]

    def get(self, request, **kwrags):
        search_term = request.query_params.get("q")
        hdip_users = HDIPUsers.objects.all()

        if search_term:
            hdip_users = hdip_users.filter(
                Q(name__icontains=search_term) | Q(user__email__icontains=search_term)
            )

        paginated_queryset = self.paginate_queryset(hdip_users, request)
        serializer = self.serializer_class(paginated_queryset, many=True)
        paginated_response = self.get_paginated_response(serializer.data)
        return Response(
            {
                "status": "success",
                "message": "HDIP user retrieve successfully.",
                **paginated_response.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, **kwargs):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": "success",
                    "message": "HDIP user added successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        custom_errors = serializer.errors.pop("errors", None)
        return Response(
            {
                "status": "failed",
                "message": "Invalid data.",
                "errors": custom_errors if custom_errors else serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def patch(self, request, **kwargs):
        pk = kwargs.get("pk")
        if not pk:
            return Response(
                {"status": "failed", "message": "Invalid request"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            hdip_user = HDIPUsers.objects.get(pk=pk)
        except HDIPUsers.DoesNotExist:
            return Response(
                {"status": "failed", "message": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.serializer_class(
            hdip_user, data=request.data, partial=True, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": "success",
                    "message": "HDIP user data updated successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        custom_errors = serializer.errors.pop("errors", None)
        return Response(
            {
                "status": "failed",
                "message": "Invalid data.",
                "errors": custom_errors if custom_errors else serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
