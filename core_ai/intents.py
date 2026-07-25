from enum import Enum


class Intent(str, Enum):
    GREETING = "greeting"

    SMALL_TALK = "small_talk"

    PRODUCT_QUESTION = "product_question"

    PRICING = "pricing"

    QUALIFICATION = "qualification"

    OBJECTION = "objection"

    BUYING_SIGNAL = "buying_signal"

    MEETING_REQUEST = "meeting_request"

    SUPPORT = "support"

    GOODBYE = "goodbye"

    INFORMATION = "information"

    UNKNOWN = "unknown"