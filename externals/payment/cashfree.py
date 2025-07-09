import logging
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from cashfree_pg.api_client import Cashfree, CFEnvironment
from cashfree_pg.models.create_link_request import CreateLinkRequest
from cashfree_pg.models.link_customer_details_entity import LinkCustomerDetailsEntity
from cashfree_pg.models.link_meta_response_entity import LinkMetaResponseEntity
from cashfree_pg.models.link_notify_entity import LinkNotifyEntity
from hiringdogbackend.utils import log_action

Cashfree.XClientId = settings.CF_CLIENTID
Cashfree.XClientSecret = settings.CF_CLIENTSECRET
Cashfree.XEnvironment = (
    CFEnvironment.SANDBOX
    if settings.DEBUG or "api.hdiplatform.in" in settings.ALLOWED_HOSTS
    else CFEnvironment.PRODUCTION
)


def create_payment_link(user, user_name, payment_link_id, amount):
    try:
        payment_link = CreateLinkRequest(
            link_id=payment_link_id,
            link_amount=amount,
            link_currency="INR",
            link_purpose="HDIP Interviews Bill Payment",
            link_expiry_time=(timezone.now() + timedelta(days=1)).isoformat(),
            customer_details=LinkCustomerDetailsEntity(
                customer_phone=str(user.phone),
                customer_email=user.email,
                customer_name=user_name,
            ),
            link_notify=LinkNotifyEntity(send_email=False, send_sms=False),
            link_meta=LinkMetaResponseEntity(
                return_url=f"{settings.CF_RETURNURL}?payment_link_id={payment_link_id}",
                payment_methods="upi,cc,dc,nb",
            ),
        )

        response = Cashfree().PGCreateLink(
            x_api_version="2025-01-01", create_link_request=payment_link
        )
        return response
    except Exception as e:
        log_action(f"Error creating payment link: {str(e)}", level=logging.ERROR)
        return None


def is_valid_signature(body, received_signature, timestamp):
    try:
        Cashfree().PGVerifyWebhookSignature(received_signature, body, timestamp)
        return True
    except Exception as e:
        log_action(f"Error verifying signature: {str(e)}", level=logging.ERROR)
        return False
