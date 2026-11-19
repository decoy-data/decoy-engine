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
ARG_RAISES_REASON = (
    "the provider refuses this argument in this locale (a missing key, type or value)"
)
ARG_UNSTABLE_REASON = "the provider draws from state the seed does not control for this argument"
ARG_PARSE_REASON = "Faker 40.23.0 refuses an ISO date string here (ParseError); a date object works"


def _arg_everywhere(count: int, reason: str, ids: str) -> dict[tuple[str, str], Entry]:
    """Argumented cases present in every locale of the lock, written as one id per word."""
    return {("argumented", i): (Everywhere(count=count), reason) for i in ids.split()}


EXPECTED_UNSTABLE: dict[tuple[str, str], Entry] = {
    **_arg_everywhere(
        1,
        ARG_UNSTABLE_REASON,
        "reflected.license_plate.temporary_plate_false "
        "reflected.license_plate.temporary_plate_true reflected.org_and_vat_id.dash_false "
        "reflected.org_and_vat_id.dash_true reflected.org_and_vat_id.long_false "
        "reflected.org_and_vat_id.long_true reflected.org_id.dash_false "
        "reflected.org_id.dash_true reflected.org_id.long_false reflected.org_id.long_true "
        "reflected.rfc.natural_false reflected.rfc.natural_true reflected.vat_id.prefix_false "
        "reflected.vat_id.prefix_true ",
    ),
    **_arg_everywhere(
        3, ARG_UNSTABLE_REASON, "reflected.nuss.company_false reflected.nuss.company_true "
    ),
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
    **_arg_everywhere(1, ARG_PARSE_REASON, "reflected.ssn.birthdate_absolute "),
    **_arg_everywhere(
        1,
        ARG_RAISES_REASON,
        "reflected.elector_code.gender_set reflected.full_name.gender_set "
        "reflected.jan.length_set reflected.license_plate.region_name_set "
        "reflected.pesel_compute_check_digit.pesel_set reflected.pincode_in_state.state_abbr_set "
        "reflected.plate_letter_prefix.region_name_set "
        "reflected.plate_region_code.region_name_set "
        "reflected.pwz_doctor_compute_check_digit.x_set reflected.ssn.birthdate_relative "
        "reflected.ssn.birthday_set ",
    ),
    **_arg_everywhere(2, ARG_PARSE_REASON, "reflected.rvnr.birthdate_absolute "),
    **_arg_everywhere(
        2,
        ARG_RAISES_REASON,
        "reflected.ape_code.version_set reflected.company_vat.siren_set "
        "reflected.postalcode_in_province.province_abbr_set "
        "reflected.postcode_in_province.province_abbr_set reflected.rvnr.birthdate_relative "
        "reflected.ssn.dob_set ",
    ),
    **_arg_everywhere(4, ARG_RAISES_REASON, "reflected.ssn.gender_set "),
    **_arg_everywhere(43, ARG_RAISES_REASON, "reflected.postalcode_in_state.state_abbr_set "),
    **_arg_everywhere(44, ARG_RAISES_REASON, "reflected.zipcode_in_state.state_abbr_set "),
    **_arg_everywhere(47, ARG_RAISES_REASON, "reflected.postcode_in_state.state_abbr_set "),
    **_arg_everywhere(
        51, ARG_RAISES_REASON, "reflected.ssn.taxpayer_identification_number_type_set "
    ),
    **_arg_everywhere(104, ARG_PARSE_REASON, "reflected.passport_dates.birthday_absolute "),
    **_arg_everywhere(104, ARG_RAISES_REASON, "reflected.passport_dates.birthday_relative "),
    **_arg_everywhere(106, ARG_RAISES_REASON, "adapter.address_zip.unexpected_keyword "),
    **_arg_everywhere(
        107,
        ARG_PARSE_REASON,
        "formula.date_between.start_date_end_date_absolute formula.future_date.end_date_absolute "
        "formula.past_date.start_date_absolute reflected.credit_card_expire.start_end_absolute "
        "reflected.date_between.start_date_end_date_absolute "
        "reflected.date_between_dates.date_start_date_end_absolute "
        "reflected.date_time_ad.start_datetime_end_datetime_absolute "
        "reflected.date_time_between.start_date_end_date_absolute "
        "reflected.date_time_between_dates.datetime_start_datetime_end_absolute "
        "reflected.future_date.end_date_absolute reflected.future_datetime.end_date_absolute "
        "reflected.past_date.start_date_absolute reflected.past_datetime.start_date_absolute "
        "reflected.unix_time.start_datetime_end_datetime_absolute ",
    ),
    **_arg_everywhere(
        107,
        ARG_RAISES_REASON,
        "adapter.address_city.unexpected_keyword adapter.address_full.unexpected_keyword "
        "adapter.address_state.unexpected_keyword adapter.address_street.unexpected_keyword "
        "adapter.person_first_name.unexpected_keyword adapter.person_full_name.unexpected_keyword "
        "adapter.person_last_name.unexpected_keyword adapter.person_name.unexpected_keyword "
        "adapter.person_phone.unexpected_keyword "
        "adapter.synthetic_account_number.unexpected_keyword "
        "address_override.address.unexpected_keyword formula.future_date.end_date_relative "
        "formula.future_date.end_date_typed formula.future_date.positional_end_date "
        "reflected.color.hue_set reflected.color_hsl.hue_set reflected.color_hsv.hue_set "
        "reflected.color_rgb.hue_set reflected.color_rgb_float.hue_set "
        "reflected.country_code.representation_set reflected.credit_card_full.card_type_set "
        "reflected.credit_card_number.card_type_set reflected.credit_card_provider.card_type_set "
        "reflected.credit_card_security_code.card_type_set reflected.currency_symbol.code_set "
        "reflected.del_arguments.argument_set reflected.dsv.dialect_set reflected.ean.length_set "
        "reflected.ean.prefixes_set reflected.ean13.prefixes_set reflected.ean8.prefixes_set "
        "reflected.file_extension.category_set reflected.file_name.category_set "
        "reflected.file_path.category_set reflected.file_path.file_system_rule_set "
        "reflected.fixed_width.data_columns_set reflected.future_date.end_date_relative "
        "reflected.future_date.end_date_typed reflected.get_formatter.formatter_set "
        "reflected.get_words_list.part_of_speech_set reflected.iso8601.timespec_set "
        "reflected.json.data_columns_set reflected.localized_ean.length_set "
        "reflected.mime_type.category_set reflected.nic_handle.suffix_set "
        "reflected.nic_handles.suffix_set reflected.pydecimal.min_value_max_value_equal "
        "reflected.pyfloat.min_value_max_value_equal reflected.random_sample.length_set "
        "reflected.swift.length_set reflected.word.part_of_speech_set "
        "reflected.words.part_of_speech_set ",
    ),
    ("argumented", "reflected.ssn.min_age_max_age_equal"): (
        (
            "et_EE",
            "lv_LV",
            "sv_SE",
        ),
        ARG_RAISES_REASON,
    ),
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
    **_arg_everywhere(
        1,
        ARG_CALENDAR_REASON,
        "reflected.pesel.sex_set reflected.ssn.area_code_set reflected.ssn.artificial_false "
        "reflected.ssn.artificial_true reflected.ssn.dash_false reflected.ssn.dash_true "
        "reflected.ssn.long_false reflected.ssn.long_true ",
    ),
    **_arg_everywhere(
        2,
        ARG_CALENDAR_REASON,
        "reflected.date.buddhist_era_false reflected.date.buddhist_era_true "
        "reflected.date.thai_digit_false reflected.date.thai_digit_true "
        "reflected.time.thai_digit_false reflected.time.thai_digit_true ",
    ),
    **_arg_everywhere(5, ARG_CALENDAR_REASON, "reflected.ssn.min_age_max_age_ordered "),
    **_arg_everywhere(104, ARG_CALENDAR_REASON, "reflected.passport_dates.birthday_typed "),
    **_arg_everywhere(
        107,
        ARG_CALENDAR_REASON,
        "formula.date_between.positional_start_date_end_date "
        "formula.date_between.start_date_end_date_relative "
        "formula.date_this_decade.after_today_false formula.date_this_decade.after_today_true "
        "formula.date_this_decade.before_today_false formula.date_this_decade.before_today_true "
        "formula.date_this_decade.positional_before_today_after_today "
        "formula.date_this_month.after_today_false formula.date_this_month.after_today_true "
        "formula.date_this_month.before_today_false formula.date_this_month.before_today_true "
        "formula.date_this_month.positional_before_today_after_today "
        "formula.date_this_year.after_today_false formula.date_this_year.after_today_true "
        "formula.date_this_year.before_today_false formula.date_this_year.before_today_true "
        "formula.date_this_year.positional_before_today_after_today "
        "formula.past_date.positional_start_date_tzinfo formula.past_date.start_date_relative "
        "formula.past_date.start_date_typed formula.past_date.tzinfo_set "
        "reflected.credit_card_expire.start_end_relative "
        "reflected.date_between.start_date_end_date_relative "
        "reflected.date_between_dates.date_start_date_end_relative "
        "reflected.date_this_century.after_today_false "
        "reflected.date_this_century.before_today_false "
        "reflected.date_this_century.before_today_true "
        "reflected.date_this_decade.after_today_false reflected.date_this_decade.after_today_true "
        "reflected.date_this_decade.before_today_false "
        "reflected.date_this_decade.before_today_true reflected.date_this_month.after_today_false "
        "reflected.date_this_month.after_today_true reflected.date_this_month.before_today_false "
        "reflected.date_this_month.before_today_true reflected.date_this_year.after_today_false "
        "reflected.date_this_year.after_today_true reflected.date_this_year.before_today_false "
        "reflected.date_this_year.before_today_true reflected.date_time.tzinfo_set "
        "reflected.date_time_ad.start_datetime_end_datetime_relative "
        "reflected.date_time_ad.tzinfo_set "
        "reflected.date_time_between.start_date_end_date_relative "
        "reflected.date_time_between.tzinfo_set "
        "reflected.date_time_between_dates.datetime_start_datetime_end_relative "
        "reflected.date_time_between_dates.tzinfo_set "
        "reflected.date_time_this_century.after_now_false "
        "reflected.date_time_this_century.before_now_false "
        "reflected.date_time_this_century.before_now_true "
        "reflected.date_time_this_century.tzinfo_set "
        "reflected.date_time_this_decade.after_now_false "
        "reflected.date_time_this_decade.after_now_true "
        "reflected.date_time_this_decade.before_now_false "
        "reflected.date_time_this_decade.before_now_true "
        "reflected.date_time_this_decade.tzinfo_set "
        "reflected.date_time_this_month.after_now_false "
        "reflected.date_time_this_month.after_now_true "
        "reflected.date_time_this_month.before_now_false "
        "reflected.date_time_this_month.before_now_true reflected.date_time_this_month.tzinfo_set "
        "reflected.date_time_this_year.after_now_false "
        "reflected.date_time_this_year.after_now_true "
        "reflected.date_time_this_year.before_now_false "
        "reflected.date_time_this_year.before_now_true reflected.date_time_this_year.tzinfo_set "
        "reflected.future_datetime.end_date_relative reflected.future_datetime.end_date_typed "
        "reflected.future_datetime.tzinfo_set reflected.iso8601.sep_set "
        "reflected.iso8601.tzinfo_set reflected.past_date.start_date_relative "
        "reflected.past_date.start_date_typed reflected.past_date.tzinfo_set "
        "reflected.past_datetime.start_date_relative reflected.past_datetime.start_date_typed "
        "reflected.past_datetime.tzinfo_set "
        "reflected.unix_time.start_datetime_end_datetime_relative reflected.uuid1.cast_to_set "
        "reflected.uuid7.cast_to_set reflected.xml.allowed_types_set "
        "reflected.xml.nb_elements_set reflected.xml.value_types_set "
        "reflected.xml.variable_nb_elements_true ",
    ),
    ("argumented", "adapter.person_email.domain_set"): (("bg_BG",), ARG_CALENDAR_REASON),
    ("argumented", "adapter.person_email.safe_true"): (("bg_BG",), ARG_CALENDAR_REASON),
    ("argumented", "reflected.email.domain_set"): (("bg_BG",), ARG_CALENDAR_REASON),
    ("argumented", "reflected.email.safe_true"): (("bg_BG",), ARG_CALENDAR_REASON),
    ("argumented", "reflected.ssn.min_age_max_age_equal"): (
        (
            "fi_FI",
            "zh_CN",
        ),
        ARG_CALENDAR_REASON,
    ),
    ("argumented", "reflected.xml.variable_nb_elements_false"): (
        (
            "am_ET",
            "ar_AA",
            "ar_AE",
            "ar_BH",
            "ar_DZ",
            "ar_EG",
            "ar_JO",
            "ar_PS",
            "ar_SA",
            "az_AZ",
            "bg_BG",
            "bn_BD",
            "bs_BA",
            "cs_CZ",
            "da_DK",
            "de",
            "de_AT",
            "de_CH",
            "de_DE",
            "de_LI",
            "de_LU",
            "dk_DK",
            "el_CY",
            "el_GR",
            "en",
            "en_AU",
            "en_BD",
            "en_CA",
            "en_GB",
            "en_IE",
            "en_IN",
            "en_KE",
            "en_MS",
            "en_NG",
            "en_NZ",
            "en_PH",
            "en_PK",
            "en_TH",
            "en_US",
            "es",
            "es_AR",
            "es_CA",
            "es_CL",
            "es_CO",
            "es_ES",
            "es_MX",
            "et_EE",
            "fa_IR",
            "fi_FI",
            "fil_PH",
            "fr_BE",
            "fr_CA",
            "fr_CH",
            "fr_DZ",
            "fr_FR",
            "fr_QC",
            "ga_IE",
            "gu_IN",
            "ha_NG",
            "hi_IN",
            "hr_HR",
            "hu_HU",
            "hy_AM",
            "id_ID",
            "ig_NG",
            "is_IS",
            "it_CH",
            "ja_JP",
            "ka_GE",
            "ko_KR",
            "la",
            "lb_LU",
            "lt_LT",
            "lv_LV",
            "mr_IN",
            "mt_MT",
            "ne_NP",
            "ng_NG",
            "nl_BE",
            "nl_NL",
            "no_NO",
            "or_IN",
            "pl_PL",
            "pt_BR",
            "pt_PT",
            "ro_RO",
            "ru_RU",
            "sk_SK",
            "sl_SI",
            "sq_AL",
            "sv_SE",
            "sw",
            "ta_IN",
            "th",
            "th_TH",
            "tl_PH",
            "tr_TR",
            "tw_GH",
            "uk_UA",
            "uz_UZ",
            "vi_VN",
            "yo_NG",
            "zh_CN",
            "zh_TW",
            "zu_ZA",
        ),
        ARG_CALENDAR_REASON,
    ),
    ("adapter", "person_email"): (("az_AZ", "bg_BG", "ru_RU"), CALENDAR_REASON),
    ("reflected", "am_pm"): (Everywhere(count=107), CALENDAR_REASON),
    ("reflected", "individuals_ogrn"): (("ru_RU",), CALENDAR_REASON),
    ("reflected", "ascii_company_email"): (("bg_BG", "ru_RU"), CALENDAR_REASON),
    ("reflected", "ascii_email"): (("az_AZ", "bg_BG", "ru_RU"), CALENDAR_REASON),
    ("reflected", "ascii_free_email"): (("az_AZ", "bg_BG", "ru_RU"), CALENDAR_REASON),
    ("reflected", "ascii_safe_email"): (("az_AZ", "bg_BG", "ru_RU"), CALENDAR_REASON),
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
    ("reflected", "email"): (
        ("az_AZ", "bg_BG", "ru_RU"),
        "email local part reads the clock in these locales",
    ),
    ("reflected", "free_email"): (("az_AZ", "bg_BG", "ru_RU"), CALENDAR_REASON),
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
    ("reflected", "safe_email"): (("az_AZ", "bg_BG", "ru_RU"), CALENDAR_REASON),
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
