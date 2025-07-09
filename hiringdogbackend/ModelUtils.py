from django.db import models


class SoftDelete(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(archived=False)


class CreateUpdateDateTimeAndArchivedField(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived = models.BooleanField(default=False)

    class Meta:
        abstract = True
