"""Reviewed lists for the Faker output lock sentry (`test_faker_output_lock.py`).

Each entry names the pairs the lock records as unstable, raising, or calendar-dependent, with a
one-line reason. The sentry requires each list to equal the lock exactly, so a pair that joins or
leaves a list needs an edit here, which shows in review. An `Everywhere` entry pins how many
locales it covers, so a new locale joining the lock fails until the count is edited.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Everywhere:
    """Every locale of the lock that has the provider, minus `except_`; `count` pins the total."""

    count: int
    except_: tuple[str, ...] = field(default=())


Entry = tuple["Everywhere | tuple[str, ...]", str]

RAISES_REASON = "provider raises with no arguments in this locale"
CALENDAR_REASON = "reads the date or time (clock-reading provider)"
ARG_CALENDAR_REASON = "the call resolves today or a relative bound, so its range follows the clock"
ARG_PARSE_REASON = "Faker 40.23.0 refuses an ISO date string here (ParseError); a date object works"

EXPECTED_UNSTABLE: dict[tuple[str, str], Entry] = {
    ("adapter", "address_city"): (
        ("it_IT",),
        "it_IT city list is built from a set, so its order follows the string hash seed",
    ),
    ("reflected", "cif"): (
        ("es", "es_CA", "es_ES"),
        "es_ES ssn uses unseeded module-level `random`",
    ),
    ("reflected", "city"): (
        ("it_IT",),
        "it_IT city list is built from a set, so its order follows the string hash seed",
    ),
    ("reflected", "curp"): (("es_MX",), "es_MX ssn uses unseeded module-level `random`"),
    ("reflected", "diplomatic_license_plate"): (
        ("uk_UA",),
        "uk_UA automotive uses unseeded module-level `random`",
    ),
    ("reflected", "elector_code"): (("es_MX",), "es_MX ssn uses unseeded module-level `random`"),
    ("reflected", "license_plate"): (
        ("uk_UA",),
        "uk_UA automotive uses unseeded module-level `random`",
    ),
    ("reflected", "nie"): (
        ("es", "es_CA", "es_ES"),
        "es_ES ssn uses unseeded module-level `random`",
    ),
    ("reflected", "nif"): (
        ("es", "es_CA", "es_ES"),
        "es_ES ssn uses unseeded module-level `random`",
    ),
    ("reflected", "nuss"): (
        ("es", "es_CA", "es_ES"),
        "es_ES ssn uses unseeded module-level `random`",
    ),
    ("reflected", "org_and_vat_id"): (
        ("sv_SE",),
        "sv_SE org_id uses unseeded module-level `random.shuffle`",
    ),
    ("reflected", "org_id"): (
        ("sv_SE",),
        "sv_SE org_id uses unseeded module-level `random.shuffle`",
    ),
    ("reflected", "passport_full"): (
        Everywhere(count=104),
        "passport_gender draws from unseeded module-level `random.choices`",
    ),
    ("reflected", "passport_gender"): (
        Everywhere(count=104),
        "draws from unseeded module-level `random.choices`",
    ),
    ("reflected", "plate_letter_prefix"): (
        ("uk_UA",),
        "uk_UA automotive uses unseeded module-level `random`",
    ),
    ("reflected", "plate_region_code"): (
        ("uk_UA",),
        "uk_UA automotive uses unseeded module-level `random`",
    ),
    ("reflected", "rfc"): (("es_MX",), "es_MX ssn uses unseeded module-level `random`"),
    ("reflected", "ssn"): (
        ("th", "th_TH", "uk_UA"),
        "th and uk_UA ssn use unseeded module-level `random`",
    ),
    ("reflected", "tin"): (("el_GR",), "el_GR tin uses unseeded module-level `random.choice`"),
    ("reflected", "vat_id"): (
        ("el_GR", "sv_SE", "th", "th_TH"),
        "el_GR, sv_SE and th vat_id use unseeded module-level `random`",
    ),
}

EXPECTED_RAISES: dict[tuple[str, str], Entry] = {
    ("argumented", "date_between.absolute_strings"): (Everywhere(count=107), ARG_PARSE_REASON),
    ("argumented", "future_date.absolute_string"): (Everywhere(count=107), ARG_PARSE_REASON),
    ("argumented", "past_date.absolute_string"): (Everywhere(count=107), ARG_PARSE_REASON),
    ("adapter", "address_state"): (
        (
            "ar_DZ",
            "az_AZ",
            "bn_BD",
            "de_CH",
            "el_GR",
            "en_BD",
            "en_CA",
            "en_GB",
            "en_IE",
            "en_NZ",
            "en_PH",
            "es_AR",
            "es_CL",
            "es_CO",
            "fil_PH",
            "fr_CA",
            "fr_CH",
            "fr_DZ",
            "fr_FR",
            "he_IL",
            "hu_HU",
            "ja_JP",
            "ka_GE",
            "ko_KR",
            "ne_NP",
            "nl_BE",
            "nl_NL",
            "no_NO",
            "pl_PL",
            "pt_PT",
            "ru_RU",
            "th",
            "th_TH",
            "tl_PH",
            "uk_UA",
            "zh_CN",
            "zh_TW",
            "zu_ZA",
        ),
        "no state list in this locale (adapter wraps AttributeError)",
    ),
    ("adapter", "person_phone"): (
        ("en_PH", "fil_PH", "tl_PH"),
        "no phone format in this locale (adapter wraps AttributeError)",
    ),
    ("reflected", "bank"): (
        (
            "bn_BD",
            "cs_CZ",
            "da_DK",
            "de",
            "de_AT",
            "de_DE",
            "en_IE",
            "en_PH",
            "es",
            "es_ES",
            "fi_FI",
            "fil_PH",
            "fr_FR",
            "it_IT",
            "nl_NL",
            "no_NO",
            "pl_PL",
            "pt_PT",
            "ro_RO",
            "sk_SK",
            "th",
            "th_TH",
            "tl_PH",
            "tr_TR",
        ),
        "no bank list in this locale (AttributeError)",
    ),
    ("reflected", "current_country"): (("en_MS",), "locale has no current country"),
    ("reflected", "del_arguments"): (
        Everywhere(count=107),
        "Faker helper that needs arguments; reflected with none",
    ),
    ("reflected", "get_formatter"): (
        Everywhere(count=107),
        "Faker helper that needs arguments; reflected with none",
    ),
    ("reflected", "is_leap_year"): (("it_IT",), "helper that needs an argument"),
    ("reflected", "name_female"): (("es_AR",), "locale has no female name list"),
    ("reflected", "name_male"): (("es_AR",), "locale has no male name list"),
    ("reflected", "pesel_compute_check_digit"): (("pl_PL",), "helper that needs an argument"),
    ("reflected", "pricetag"): (("bn_BD",), "locale has no currency symbol entry"),
    ("reflected", "provider"): (
        Everywhere(count=107),
        "Faker helper that needs arguments; reflected with none",
    ),
    ("reflected", "pwz_doctor_compute_check_digit"): (("pl_PL",), "helper that needs an argument"),
    ("reflected", "xml"): (("fr_FR", "pl_PL"), "xml() rejects the default size in this locale"),
}

EXPECTED_CALENDAR: dict[tuple[str, str], Entry] = {
    ("argumented", "date_between.relative"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_decade.after_only"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_decade.before_only"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_decade.neither_side"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_month.after_only"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_month.before_only"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_month.both_sides"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_month.neither_side"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_year.after_only"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_year.before_only"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_year.both_sides"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "date_this_year.neither_side"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "future_date.date_object"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "future_date.relative"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "past_date.date_object"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("argumented", "past_date.relative"): (Everywhere(count=107), ARG_CALENDAR_REASON),
    ("reflected", "am_pm"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "ascii_company_email"): (("bg_BG", "ru_RU"), CALENDAR_REASON),
    ("reflected", "ascii_email"): (("az_AZ", "ru_RU"), CALENDAR_REASON),
    ("reflected", "ascii_free_email"): (("bg_BG",), CALENDAR_REASON),
    ("reflected", "ascii_safe_email"): (("bg_BG",), CALENDAR_REASON),
    ("reflected", "birth_number"): (
        ("cs_CZ", "sk_SK"),
        "birth number reads today for the century digit",
    ),
    ("reflected", "company_email"): (("bg_BG", "ru_RU"), CALENDAR_REASON),
    ("reflected", "credit_card_expire"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "credit_card_full"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_between"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_between_dates"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_object"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_this_century"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_this_decade"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_this_month"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_this_year"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_time"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_time_ad"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_time_between"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_time_between_dates"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_time_this_century"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_time_this_decade"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_time_this_month"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "date_time_this_year"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "day_of_month"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "day_of_week"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "day_of_week_in_guj"): (("gu_IN",), CALENDAR_REASON),
    ("reflected", "email"): (("bg_BG",), "email local part reads the clock in this locale"),
    ("reflected", "free_email"): (("bg_BG",), CALENDAR_REASON),
    ("reflected", "future_date"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "future_datetime"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "iso8601"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "minguo_year"): (("zh_TW",), CALENDAR_REASON),
    ("reflected", "month"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "month_in_guj"): (("gu_IN",), CALENDAR_REASON),
    ("reflected", "month_name"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "month_name_in_guj"): (("gu_IN",), CALENDAR_REASON),
    ("reflected", "passport_dates"): (Everywhere(count=104), CALENDAR_REASON),
    ("reflected", "passport_dob"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "past_date"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "past_datetime"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "pesel"): (("pl_PL",), "check date reads today"),
    ("reflected", "rvnr"): (("de", "de_DE"), "insurance number reads today"),
    ("reflected", "safe_email"): (("bg_BG",), CALENDAR_REASON),
    ("reflected", "ssn"): (
        ("de_AT", "el_GR", "et_EE", "fi_FI", "lv_LV", "nl_BE", "no_NO", "pl_PL", "sv_SE", "zh_CN"),
        "national id embeds the birth date or age from today",
    ),
    ("reflected", "time"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "traditional_month_name"): (("ja_JP",), CALENDAR_REASON),
    ("reflected", "unix_time"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "user_name"): (("az_AZ", "bg_BG", "ru_RU"), CALENDAR_REASON),
    ("reflected", "uuid1"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "uuid7"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "xml"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "year"): (Everywhere(count=107), CALENDAR_REASON),
}

# Pairs that must be digests on both surfaces where they exist (the 2026-07-23 confusion was
# about names and addresses, so they are anchored).
ANCHORS: tuple[tuple[str, str, str], ...] = (
    ("en_US", "reflected", "first_name"),
    ("en_US", "reflected", "email"),
    ("en_US", "reflected", "address"),
    ("en_US", "reflected", "currency_code"),
    ("es_ES", "reflected", "bban"),
    ("en_GB", "reflected", "vat_id"),
    ("en_US", "adapter", "person_first_name"),
    ("en_US", "adapter", "person_email"),
)
EN_US_DIGEST_FLOOR = 253  # en_US reflected pairs whose two fields are digests, as captured
