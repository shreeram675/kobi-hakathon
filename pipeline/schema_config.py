"""Default runtime schema configuration for Kobie's ArcGuide fields.

The extraction engine remains generic; this module is the project-level schema
config that tells the generic extractor which fields Kobie currently cares
about.
"""

from __future__ import annotations

from functools import lru_cache

from pipeline.stages.extractor import FieldDef, ObjectTypeDef, SchemaConfig


FOCUSED_SCHEMA_FIELD_PATHS: tuple[str, ...] = (
    "program_basics.program_name",
    "program_basics.brand",
    "program_basics.industry",
    "program_basics.program_type",
    "program_basics.geography",
    "program_basics.membership_count",
    "earn_mechanics.base_earn_rate",
    "earn_mechanics.bonus_categories",
    "earn_mechanics.non_transactional_earn",
    "burn_mechanics.redemption_options",
    "burn_mechanics.redemption_thresholds",
    "burn_mechanics.point_value_cpp",
    "burn_mechanics.expiry_policy",
    "tier_system.tier_names",
    "tier_system.qualification_criteria",
    "tier_system.tier_benefits",
    "tier_system.qualification_period",
    "partnerships.partner_names",
    "partnerships.partnership_type",
    "partnerships.details",
    "digital_experience.mobile_app_available",
    "digital_experience.app_ratings",
    "digital_experience.personalization_features",
    "digital_experience.gamification_features",
    "member_sentiment.ratings",
    "member_sentiment.common_praise",
    "member_sentiment.common_complaints",
    "member_sentiment.sources_checked",
    "competitive_position.key_differentiators",
    "competitive_position.weaknesses",
    "competitive_position.closest_competitors",
)


IDENTITY_FIELD_PATHS = frozenset(
    {
        "program_basics.program_name",
        "program_basics.brand",
        "program_basics.geography",
    }
)


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("program_basics.program_name",),
    "brand": ("program_basics.brand",),
    "industry": ("program_basics.industry",),
    "type": ("program_basics.program_type",),
    "program_type": ("program_basics.program_type",),
    "geography": ("program_basics.geography",),
    "membership_count": ("program_basics.membership_count",),
    "earn_rate_base": ("earn_mechanics.base_earn_rate",),
    "base_earn_rate": ("earn_mechanics.base_earn_rate",),
    "bonus_categories": ("earn_mechanics.bonus_categories",),
    "non_transactional_earn": ("earn_mechanics.non_transactional_earn",),
    "redemption_value": ("burn_mechanics.point_value_cpp",),
    "point_value": ("burn_mechanics.point_value_cpp",),
    "cpp": ("burn_mechanics.point_value_cpp",),
    "redemption_options": ("burn_mechanics.redemption_options",),
    "redemption_thresholds": ("burn_mechanics.redemption_thresholds",),
    "expiry_policy": ("burn_mechanics.expiry_policy",),
    "tier_structure": (
        "tier_system.tier_names",
        "tier_system.qualification_criteria",
        "tier_system.tier_benefits",
        "tier_system.qualification_period",
    ),
    "tier_names": ("tier_system.tier_names",),
    "qualification_criteria": ("tier_system.qualification_criteria",),
    "qualification_period": ("tier_system.qualification_period",),
    "tier_benefits": ("tier_system.tier_benefits",),
    "partnerships": (
        "partnerships.partner_names",
        "partnerships.partnership_type",
        "partnerships.details",
    ),
    "partner_names": ("partnerships.partner_names",),
    "partner_details": ("partnerships.details",),
    "earn_details": ("partnerships.details",),
    "burn_details": ("partnerships.details",),
    "mobile_app": ("digital_experience.mobile_app_available",),
    "app_ratings": ("digital_experience.app_ratings",),
    "app_store_rating": ("digital_experience.app_ratings",),
    "play_store_rating": ("digital_experience.app_ratings",),
    "personalization": ("digital_experience.personalization_features",),
    "gamification": ("digital_experience.gamification_features",),
    "member_sentiment": (
        "member_sentiment.ratings",
        "member_sentiment.common_praise",
        "member_sentiment.common_complaints",
        "member_sentiment.sources_checked",
    ),
    "ratings": ("member_sentiment.ratings",),
    "sources_checked": ("member_sentiment.sources_checked",),
    "review_sources_checked": ("member_sentiment.sources_checked",),
    "forum_sources_checked": ("member_sentiment.sources_checked",),
    "competitive_position": (
        "competitive_position.key_differentiators",
        "competitive_position.weaknesses",
        "competitive_position.closest_competitors",
    ),
    "closest_competitors": ("competitive_position.closest_competitors",),
}


@lru_cache(maxsize=1)
def default_arcguide_schema_config() -> SchemaConfig:
    """Return the focused runtime schema required for the current report."""

    fields = [
        FieldDef(
            name=field_path,
            description=_field_description(field_path),
            value_type=_value_type_for_field(field_path),
            identity=field_path in IDENTITY_FIELD_PATHS,
        )
        for field_path in FOCUSED_SCHEMA_FIELD_PATHS
    ]
    return SchemaConfig(
        object_types=[
            ObjectTypeDef(
                object_type="loyalty_intelligence",
                description=(
                    "Competitive intelligence facts extracted from explicit source text. "
                    "Fields use ArcGuide dot paths."
                ),
                fields=fields,
            )
        ]
    )


def all_default_field_paths() -> list[str]:
    """Return the focused configured field paths."""

    return list(FOCUSED_SCHEMA_FIELD_PATHS)


def _field_description(field_path: str) -> str:
    section, field_name = field_path.split(".", 1)
    readable = field_name.replace("_", " ")
    section_readable = section.replace("_", " ")
    return f"Explicitly stated {readable} for the {section_readable} section."


def _value_type_for_field(field_path: str) -> str:
    if field_path.endswith(("membership_count", "point_value_cpp")):
        return "number"
    if field_path.endswith(
        (
            "app_ratings",
            "bonus_categories",
            "redemption_options",
            "transfer_options",
            "tier_names",
            "tier_benefits",
            "partner_names",
            "details",
            "sources_checked",
            "discontinued_partners",
            "closest_competitors",
        )
    ):
        return "array"
    return "string"
