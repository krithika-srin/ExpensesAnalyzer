from enum import StrEnum


class ExportColumns(StrEnum):
    """String enum for column names used in Splitwise exports."""

    DATE = "Date"
    AMOUNT = "Amount"
    CATEGORY = "Category"
    SUBCATEGORY = "Subcategory"
    DESCRIPTION = "Description"
    DETAILS = "Details"
    SPLIT_TYPE = "Split Type"
    PARTICIPANT_NAMES = "Participant Names"
    MY_PAID = "My Paid"
    MY_OWED = "My Owed"
    MY_NET = "My Net"
    FRIENDS_SPLIT = "Friends Split"
    ID = "Splitwise ID"
    FINGERPRINT = "Transaction Fingerprint"
