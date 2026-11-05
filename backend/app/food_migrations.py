import json

from sqlalchemy import inspect, text

from .food_policy import LEGACY_UNVERIFIED_DIET, VEGETARIAN_DIETS, food_is_allowed, ingredients_list
from .util import today

_FORBIDDEN_SQL_TERMS = (
    "chicken", "mutton", "lamb", "goat", "beef", "pork", "bacon", "ham", "fish", "seafood", "prawn",
    "shrimp", "crab", "lobster", "shellfish", "tuna", "salmon", "sardine", "anchovy", "squid", "octopus",
    "egg", "eggs", "omelette", "omelet", "frittata", "meat", "poultry", "gelatin", "gelatine", "lard",
    "tallow", "rennet", "cochineal", "carmine", "shellac", "isinglass", "collagen", "bone broth",
    "animal products", "animal product", "animal fat", "animal stock", "animal broth", "animal rennet",
    "meat stock", "chicken stock", "fish sauce", "shrimp paste", "oyster sauce", "worcestershire",
)


def _column_names(connection, table):
    return {column["name"] for column in inspect(connection).get_columns(table)}


def _add_column(connection, table, column, declaration):
    if column not in _column_names(connection, table):
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"))


def _sqlite_forbidden_expression(expression):
    food_text = f"lower(' ' || COALESCE(CAST({expression} AS TEXT), '') || ' ')"
    return "(" + " OR ".join(
        f"{food_text} GLOB '*[^a-z]{term}[^a-z]*'" for term in _FORBIDDEN_SQL_TERMS
    ) + ")"


def _install_sqlite_triggers(connection, tables):
    menu_food = _sqlite_forbidden_expression(
        "NEW.name || ' ' || COALESCE(CAST(NEW.ingredients AS TEXT), '')"
    )
    connection.execute(text(f"""
        CREATE TRIGGER IF NOT EXISTS ck_menu_items_vegetarian_insert
        BEFORE INSERT ON menu_items
        WHEN NEW.is_active = 1 AND (NEW.diet IS NULL OR lower(NEW.diet) NOT IN ('veg', 'vegan') OR {menu_food})
        BEGIN
            SELECT RAISE(ABORT, 'Menu items must be lacto-vegetarian');
        END
    """))
    connection.execute(text(f"""
        CREATE TRIGGER IF NOT EXISTS ck_menu_items_vegetarian_update
        BEFORE UPDATE OF name, diet, ingredients, is_active ON menu_items
        WHEN NEW.is_active = 1 AND (NEW.diet IS NULL OR lower(NEW.diet) NOT IN ('veg', 'vegan') OR {menu_food})
        BEGIN
            SELECT RAISE(ABORT, 'Active menu items must be lacto-vegetarian');
        END
    """))
    if {"schedule_dishes", "meal_schedules"}.issubset(tables):
        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS ck_schedule_dishes_vegetarian_insert
            BEFORE INSERT ON schedule_dishes
            WHEN NOT EXISTS (
                SELECT 1 FROM menu_items mi
                WHERE mi.id = NEW.menu_item_id AND mi.is_active = 1 AND mi.diet IN ('veg', 'vegan')
            )
            BEGIN
                SELECT RAISE(ABORT, 'Only active vegetarian dishes can be scheduled');
            END
        """))
        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS ck_schedule_dishes_vegetarian_update
            BEFORE UPDATE ON schedule_dishes
            WHEN NOT EXISTS (
                SELECT 1 FROM menu_items mi
                WHERE mi.id = NEW.menu_item_id AND mi.is_active = 1 AND mi.diet IN ('veg', 'vegan')
            )
            BEGIN
                SELECT RAISE(ABORT, 'Only active vegetarian dishes can be scheduled');
            END
        """))
    if "surplus_listings" in tables:
        surplus_food = _sqlite_forbidden_expression(
            "NEW.food_name || ' ' || COALESCE(CAST(NEW.ingredients AS TEXT), '')"
        )
        surplus_bad = (
            "NEW.status IN ('pending_review', 'eligible', 'approved') AND "
            "(NEW.diet IS NULL OR lower(NEW.diet) NOT IN ('veg', 'vegan') OR "
            f"{surplus_food} OR (NEW.menu_item_id IS NOT NULL AND NOT EXISTS ("
            "SELECT 1 FROM menu_items mi WHERE mi.id = NEW.menu_item_id "
            "AND mi.is_active = 1 AND mi.diet = NEW.diet AND lower(mi.name) = lower(NEW.food_name))))"
        )
        connection.execute(text(f"""
            CREATE TRIGGER IF NOT EXISTS ck_surplus_vegetarian_insert
            BEFORE INSERT ON surplus_listings
            WHEN {surplus_bad}
            BEGIN
                SELECT RAISE(ABORT, 'Redistributable surplus must be lacto-vegetarian');
            END
        """))
        connection.execute(text(f"""
            CREATE TRIGGER IF NOT EXISTS ck_surplus_vegetarian_update
            BEFORE UPDATE OF food_name, diet, ingredients, status, menu_item_id ON surplus_listings
            WHEN {surplus_bad}
            BEGIN
                SELECT RAISE(ABORT, 'Redistributable surplus must be lacto-vegetarian');
            END
        """))


def _install_postgres_triggers(connection, tables):
    connection.execute(text(r"""
        CREATE OR REPLACE FUNCTION enforce_lacto_vegetarian_menu() RETURNS trigger AS $$
        DECLARE food_text text;
        BEGIN
            IF NEW.is_active THEN
                food_text := concat_ws(' ', NEW.name, NEW.ingredients::text);
                IF NEW.diet IS NULL OR NEW.diet NOT IN ('veg', 'vegan')
                   OR food_text ~* E'\\m(chicken|mutton|lamb|goat|beef|pork|bacon|ham|fish|seafood|prawn|shrimp|crab|lobster|shellfish|tuna|salmon|sardine|anchovy|squid|octopus|egg|eggs|omelette|omelet|frittata|meat|poultry|gelatin|gelatine|lard|tallow|rennet|cochineal|carmine|shellac|isinglass|collagen|bone broth|animal products?|animal fat|animal stock|animal broth|animal rennet|meat stock|chicken stock|fish sauce|shrimp paste|oyster sauce|worcestershire)\\M' THEN
                    RAISE EXCEPTION 'Menu items must be lacto-vegetarian';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    connection.execute(text("DROP TRIGGER IF EXISTS ck_menu_items_vegetarian ON menu_items"))
    connection.execute(text("""
        CREATE TRIGGER ck_menu_items_vegetarian
        BEFORE INSERT OR UPDATE ON menu_items
        FOR EACH ROW EXECUTE FUNCTION enforce_lacto_vegetarian_menu()
    """))
    if {"schedule_dishes", "meal_schedules"}.issubset(tables):
        connection.execute(text(r"""
            CREATE OR REPLACE FUNCTION enforce_vegetarian_schedule_dish() RETURNS trigger AS $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM menu_items mi
                    WHERE mi.id = NEW.menu_item_id AND mi.is_active AND mi.diet IN ('veg', 'vegan')
                ) THEN
                    RAISE EXCEPTION 'Only active vegetarian dishes can be scheduled';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """))
        connection.execute(text("DROP TRIGGER IF EXISTS ck_schedule_dishes_vegetarian ON schedule_dishes"))
        connection.execute(text("""
            CREATE TRIGGER ck_schedule_dishes_vegetarian
            BEFORE INSERT OR UPDATE ON schedule_dishes
            FOR EACH ROW EXECUTE FUNCTION enforce_vegetarian_schedule_dish()
        """))
    if "surplus_listings" in tables:
        connection.execute(text(r"""
            CREATE OR REPLACE FUNCTION enforce_lacto_vegetarian_surplus() RETURNS trigger AS $$
            DECLARE food_text text;
            BEGIN
                IF NEW.status IN ('pending_review', 'eligible', 'approved') THEN
                    food_text := concat_ws(' ', NEW.food_name, NEW.ingredients::text);
                    IF NEW.diet IS NULL OR NEW.diet NOT IN ('veg', 'vegan')
                       OR food_text ~* E'\\m(chicken|mutton|lamb|goat|beef|pork|bacon|ham|fish|seafood|prawn|shrimp|crab|lobster|shellfish|tuna|salmon|sardine|anchovy|squid|octopus|egg|eggs|omelette|omelet|frittata|meat|poultry|gelatin|gelatine|lard|tallow|rennet|cochineal|carmine|shellac|isinglass|collagen|bone broth|animal products?|animal fat|animal stock|animal broth|animal rennet|meat stock|chicken stock|fish sauce|shrimp paste|oyster sauce|worcestershire)\\M' THEN
                        RAISE EXCEPTION 'Redistributable surplus must be lacto-vegetarian';
                    END IF;
                    IF NEW.menu_item_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM menu_items mi WHERE mi.id = NEW.menu_item_id
                          AND mi.is_active AND mi.diet = NEW.diet AND lower(mi.name) = lower(NEW.food_name)
                    ) THEN
                        RAISE EXCEPTION 'Surplus classification must match an active vegetarian menu item';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """))
        connection.execute(text("DROP TRIGGER IF EXISTS ck_surplus_vegetarian ON surplus_listings"))
        connection.execute(text("""
            CREATE TRIGGER ck_surplus_vegetarian
            BEFORE INSERT OR UPDATE ON surplus_listings
            FOR EACH ROW EXECUTE FUNCTION enforce_lacto_vegetarian_surplus()
        """))


def apply_food_policy_migrations(engine):
    """Keep legacy food history; disable unverified items only in future operations."""
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        if "menu_items" not in tables:
            return

        _add_column(connection, "menu_items", "ingredients", "JSON")
        menu_rows = connection.execute(
            text("SELECT id, name, diet, ingredients, is_active FROM menu_items")
        ).mappings()
        invalid_ids = []
        valid_items = {}
        for item in menu_rows:
            ingredients = item["ingredients"]
            if isinstance(ingredients, str):
                try:
                    ingredients = json.loads(ingredients)
                except json.JSONDecodeError:
                    ingredients = []
            eligible = (
                bool(item["is_active"])
                and
                item["diet"] in VEGETARIAN_DIETS
                and food_is_allowed(item["name"], ingredients_list(ingredients))
            )
            if eligible:
                valid_items[item["id"]] = (item["diet"], ingredients_list(ingredients))
            else:
                invalid_ids.append(item["id"])
        if invalid_ids:
            for item_id in invalid_ids:
                connection.execute(
                    text("UPDATE menu_items SET is_active = :inactive WHERE id = :id"),
                    {"inactive": False, "id": item_id},
                )
                if {"schedule_dishes", "meal_schedules"}.issubset(tables):
                    connection.execute(
                        text(
                            "DELETE FROM schedule_dishes WHERE menu_item_id = :id "
                            "AND schedule_id IN (SELECT id FROM meal_schedules WHERE date >= :today)"
                        ),
                        {"id": item_id, "today": today().isoformat()},
                    )

        if "surplus_listings" in tables:
            _add_column(connection, "surplus_listings", "diet", "VARCHAR(20)")
            _add_column(connection, "surplus_listings", "ingredients", "JSON")
            listings = connection.execute(
                text("SELECT id, menu_item_id, food_name, diet, ingredients, status FROM surplus_listings")
            ).mappings()
            for listing in listings:
                diet = listing["diet"]
                ingredients = listing["ingredients"]
                if isinstance(ingredients, str):
                    try:
                        ingredients = json.loads(ingredients)
                    except json.JSONDecodeError:
                        ingredients = []
                linked_item = valid_items.get(listing["menu_item_id"])
                safe = (
                    (listing["menu_item_id"] is None or linked_item is not None)
                    and diet in VEGETARIAN_DIETS
                    and food_is_allowed(listing["food_name"], ingredients_list(ingredients))
                )
                if listing["diet"] is None and linked_item is not None:
                    item_diet, item_ingredients = linked_item
                    safe = food_is_allowed(listing["food_name"], item_ingredients)
                    if safe:
                        connection.execute(
                            text(
                                "UPDATE surplus_listings SET diet = :diet, ingredients = :ingredients WHERE id = :id"
                            ),
                            {
                                "diet": item_diet,
                                "ingredients": json.dumps(item_ingredients),
                                "id": listing["id"],
                            },
                        )
                if not safe:
                    connection.execute(
                        text(
                            "UPDATE surplus_listings SET diet = :diet, "
                            "status = CASE WHEN status IN ('pending_review', 'eligible', 'approved') "
                            "THEN :status ELSE status END WHERE id = :id"
                        ),
                        {"diet": LEGACY_UNVERIFIED_DIET, "status": "ineligible", "id": listing["id"]},
                    )

        if connection.dialect.name == "sqlite":
            _install_sqlite_triggers(connection, tables)
        elif connection.dialect.name == "postgresql":
            constraints = {
                constraint["name"]
                for constraint in inspect(connection).get_check_constraints("menu_items")
            }
            if "ck_menu_items_active_vegetarian" not in constraints:
                connection.execute(text("""
                    ALTER TABLE menu_items ADD CONSTRAINT ck_menu_items_active_vegetarian
                    CHECK (NOT is_active OR (diet IS NOT NULL AND diet IN ('veg', 'vegan')))
                """))
            if "surplus_listings" in tables:
                constraints = {
                    constraint["name"]
                    for constraint in inspect(connection).get_check_constraints("surplus_listings")
                }
                if "ck_surplus_eligible_vegetarian" not in constraints:
                    connection.execute(text("""
                        ALTER TABLE surplus_listings ADD CONSTRAINT ck_surplus_eligible_vegetarian
                        CHECK (status <> 'eligible' OR (diet IS NOT NULL AND diet IN ('veg', 'vegan')))
                    """))
            _install_postgres_triggers(connection, tables)
