import re
from typing import Iterable

from fastapi import HTTPException

VEGETARIAN_DIETS = ("veg", "vegan")
LEGACY_UNVERIFIED_DIET = "legacy_unverified"

_FORBIDDEN_FOOD = re.compile(
    r"\b(?:"
    r"chicken|mutton|lamb|goat|beef|pork|bacon|ham|"
    r"fish|seafood|prawn|shrimp|crab|lobster|shellfish|"
    r"tuna|salmon|sardine|anchovy|squid|octopus|"
    r"egg|eggs|omelette|omelet|frittata|"
    r"meat|poultry|gelatin|gelatine|lard|tallow|rennet|"
    r"cochineal|carmine|shellac|isinglass|collagen|"
    r"bone\s+broth|animal\s+(?:products?|fat|stock|broth|rennet)|"
    r"meat\s+stock|chicken\s+stock|fish\s+sauce|"
    r"shrimp\s+paste|oyster\s+sauce|worcestershire"
    r")\b",
    re.IGNORECASE,
)


def ingredients_list(value) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [ingredient.strip() for ingredient in value if isinstance(ingredient, str) and ingredient.strip()]


def food_is_allowed(name: str, ingredients: Iterable[str] = ()) -> bool:
    if not isinstance(name, str) or not name.strip():
        return False
    return not any(_FORBIDDEN_FOOD.search(text) for text in (name, *ingredients_list(ingredients)))


def require_vegetarian_food(name: str, ingredients: Iterable[str]) -> None:
    if not food_is_allowed(name, ingredients):
        raise HTTPException(422, "Only lacto-vegetarian foods and ingredients are allowed")


def require_vegetarian_diet(diet: str) -> None:
    if diet not in VEGETARIAN_DIETS:
        raise HTTPException(422, "Diet must be vegetarian or vegan; eggs and animal products are not allowed")


def is_eligible_menu_item(item) -> bool:
    return bool(
        item
        and item.is_active
        and item.diet in VEGETARIAN_DIETS
        and food_is_allowed(item.name, item.ingredients)
    )
