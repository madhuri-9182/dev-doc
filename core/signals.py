from django.core.mail import EmailMultiAlternatives
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.template.loader import render_to_string
from django.conf import settings
from django_rest_passwordreset.signals import reset_password_token_created
from .models import User


@receiver(post_save, sender=User)
def user_login_profile_cration_post_save_signal(sender, instance, created, **kwargs):
    from .models import UserProfile

    if created:
        UserProfile.objects.create(user=instance)
    else:
        try:
            profile = UserProfile.objects.get(user=instance)
            profile.save()
        except UserProfile.DoesNotExist:
            UserProfile.objects.create(user=instance)


@receiver(reset_password_token_created)
def password_reset_token_created(sender, reset_password_token, *args, **kwargs):

    # send an e-mail to the user
    site_full_name = "Hiringdog"

    # uid = urlsafe_base64_encode(
    #     force_bytes(reset_password_token.user.pk)
    # )  # .decode("utf-8")

    context = {
        "current_user": reset_password_token.user,
        "name": reset_password_token.user.email,
        "email": reset_password_token.user.email,
        "reset_password_url": "/auth/password-reset/{}".format(
            reset_password_token.key
        ),
        "site_domain": settings.SITE_DOMAIN,
    }

    email_html_message = render_to_string("reset_password.html", context)
    email_plaintext_message = render_to_string("reset_password.txt", context)

    msg = EmailMultiAlternatives(
        f"Password Reset for {site_full_name}",
        email_plaintext_message,
        (settings.EMAIL_HOST_USER if settings.DEBUG else settings.CONTACT_EMAIL),
        [reset_password_token.user.email],
    )
    msg.attach_alternative(email_html_message, "text/html")
    msg.send()
