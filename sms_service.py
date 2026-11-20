import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import phonenumbers
from phonenumbers import NumberParseException


class SMSConfigurationError(RuntimeError):
    pass


class SMSDeliveryError(RuntimeError):
    pass


def normalize_kenyan_mobile(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        number = phonenumbers.parse(value.strip(), "KE")
    except NumberParseException:
        return None
    if number.country_code != 254 or not phonenumbers.is_valid_number_for_region(
        number, "KE"
    ):
        return None
    if phonenumbers.number_type(number) != phonenumbers.PhoneNumberType.MOBILE:
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def _infobip_endpoint():
    base_url = os.environ.get("INFOBIP_BASE_URL", "").strip()
    api_key = os.environ.get("INFOBIP_API_KEY", "").strip()
    sender = os.environ.get("INFOBIP_SENDER_ID", "").strip()
    if not base_url or not api_key or not sender:
        raise SMSConfigurationError("Infobip SMS configuration is incomplete.")

    parsed = urlsplit(base_url if "://" in base_url else f"https://{base_url}")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".api.infobip.com")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise SMSConfigurationError("Infobip base URL must be an HTTPS Infobip API host.")
    return f"https://{parsed.hostname}/sms/3/messages", api_key, sender


def send_infobip_sms(phone_number, text):
    endpoint, api_key, sender = _infobip_endpoint()
    payload = {
        "messages": [
            {
                "sender": sender,
                "destinations": [{"to": phone_number}],
                "content": {"text": text},
            }
        ]
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"App {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            response_body = response.read()
    except HTTPError as error:
        raise SMSDeliveryError(
            f"Infobip rejected the SMS request (HTTP {error.code})."
        )
    except TimeoutError:
        raise SMSDeliveryError("Infobip SMS request timed out.")
    except URLError:
        raise SMSDeliveryError("Could not connect to Infobip to send the SMS.")
    except OSError:
        raise SMSDeliveryError("An error occurred while sending the SMS to Infobip.")

    try:
        messages = json.loads(response_body).get("messages")
        message = messages[0]
        status = message["status"]["groupName"].upper()
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        raise SMSDeliveryError("Infobip returned an invalid SMS response.")
    if status not in {"PENDING", "ACCEPTED"}:
        raise SMSDeliveryError("Infobip did not accept the SMS.")
    return message.get("messageId")
