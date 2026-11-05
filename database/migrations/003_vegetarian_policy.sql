-- Shakambari AI strict lacto-vegetarian policy (PostgreSQL).
-- Keeps historical menu and transaction rows, but disables unverified food for new service.
ALTER TABLE public.menu_items ADD COLUMN IF NOT EXISTS ingredients JSON;

UPDATE public.menu_items
SET is_active = FALSE
WHERE diet IS NULL OR LOWER(diet) NOT IN ('veg', 'vegan');

DELETE FROM public.schedule_dishes sd
USING public.meal_schedules ms, public.menu_items mi
WHERE sd.schedule_id = ms.id
  AND sd.menu_item_id = mi.id
  AND ms.date >= CURRENT_DATE
  AND (mi.is_active = FALSE OR mi.diet IS NULL OR LOWER(mi.diet) NOT IN ('veg', 'vegan'));

ALTER TABLE public.menu_items
    DROP CONSTRAINT IF EXISTS ck_menu_items_active_vegetarian;
ALTER TABLE public.menu_items
    ADD CONSTRAINT ck_menu_items_active_vegetarian
    CHECK (NOT is_active OR (diet IS NOT NULL AND diet IN ('veg', 'vegan')));

ALTER TABLE public.surplus_listings ADD COLUMN IF NOT EXISTS diet VARCHAR(20);
ALTER TABLE public.surplus_listings ADD COLUMN IF NOT EXISTS ingredients JSON;

UPDATE public.surplus_listings sl
SET diet = mi.diet, ingredients = mi.ingredients
FROM public.menu_items mi
WHERE sl.menu_item_id = mi.id
  AND sl.diet IS NULL
  AND mi.is_active = TRUE
  AND mi.diet IN ('veg', 'vegan');

UPDATE public.surplus_listings
SET diet = 'legacy_unverified',
    status = CASE WHEN status IN ('pending_review', 'eligible', 'approved') THEN 'ineligible' ELSE status END
WHERE diet IS NULL OR diet NOT IN ('veg', 'vegan');

UPDATE public.surplus_listings sl
SET diet = 'legacy_unverified',
    status = CASE WHEN status IN ('pending_review', 'eligible', 'approved') THEN 'ineligible' ELSE status END
WHERE sl.menu_item_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM public.menu_items mi
    WHERE mi.id = sl.menu_item_id AND mi.is_active = TRUE AND mi.diet IN ('veg', 'vegan')
  );

ALTER TABLE public.surplus_listings
    DROP CONSTRAINT IF EXISTS ck_surplus_eligible_vegetarian;
ALTER TABLE public.surplus_listings
    ADD CONSTRAINT ck_surplus_eligible_vegetarian
    CHECK (status <> 'eligible' OR (diet IS NOT NULL AND diet IN ('veg', 'vegan')));

CREATE OR REPLACE FUNCTION public.enforce_lacto_vegetarian_menu()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE food_text text;
BEGIN
    IF NEW.is_active THEN
        food_text := concat_ws(' ', NEW.name, NEW.ingredients::text);
        IF NEW.diet IS NULL OR NEW.diet NOT IN ('veg', 'vegan')
           OR food_text ~* E'\\m(chicken|mutton|lamb|goat|beef|pork|bacon|ham|fish|seafood|prawn|shrimp|crab|lobster|shellfish|tuna|salmon|sardine|anchovy|squid|octopus|egg|eggs|omelette|omelet|frittata|meat|poultry|gelatin|gelatine|lard|tallow|rennet|cochineal|carmine|shellac|isinglass|collagen|bone broth|animal products?|animal fat|animal stock|animal broth|animal rennet|meat stock|chicken stock|fish sauce|shrimp paste|oyster sauce|worcestershire)\\M' THEN
            RAISE EXCEPTION 'Active menu items must be lacto-vegetarian';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ck_menu_items_vegetarian ON public.menu_items;
CREATE TRIGGER ck_menu_items_vegetarian
BEFORE INSERT OR UPDATE ON public.menu_items
FOR EACH ROW EXECUTE FUNCTION public.enforce_lacto_vegetarian_menu();

CREATE OR REPLACE FUNCTION public.enforce_vegetarian_schedule_dish()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.menu_items mi
        WHERE mi.id = NEW.menu_item_id AND mi.is_active AND mi.diet IN ('veg', 'vegan')
    ) THEN
        RAISE EXCEPTION 'Only active vegetarian dishes can be scheduled';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ck_schedule_dishes_vegetarian ON public.schedule_dishes;
CREATE TRIGGER ck_schedule_dishes_vegetarian
BEFORE INSERT OR UPDATE ON public.schedule_dishes
FOR EACH ROW EXECUTE FUNCTION public.enforce_vegetarian_schedule_dish();

CREATE OR REPLACE FUNCTION public.enforce_lacto_vegetarian_surplus()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE food_text text;
BEGIN
    IF NEW.status IN ('pending_review', 'eligible', 'approved') THEN
        food_text := concat_ws(' ', NEW.food_name, NEW.ingredients::text);
        IF NEW.diet IS NULL OR NEW.diet NOT IN ('veg', 'vegan')
           OR food_text ~* E'\\m(chicken|mutton|lamb|goat|beef|pork|bacon|ham|fish|seafood|prawn|shrimp|crab|lobster|shellfish|tuna|salmon|sardine|anchovy|squid|octopus|egg|eggs|omelette|omelet|frittata|meat|poultry|gelatin|gelatine|lard|tallow|rennet|cochineal|carmine|shellac|isinglass|collagen|bone broth|animal products?|animal fat|animal stock|animal broth|animal rennet|meat stock|chicken stock|fish sauce|shrimp paste|oyster sauce|worcestershire)\\M' THEN
            RAISE EXCEPTION 'Redistributable surplus must be lacto-vegetarian';
        END IF;
        IF NEW.menu_item_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.menu_items mi WHERE mi.id = NEW.menu_item_id
              AND mi.is_active AND mi.diet = NEW.diet AND lower(mi.name) = lower(NEW.food_name)
        ) THEN
            RAISE EXCEPTION 'Surplus classification must match an active vegetarian menu item';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ck_surplus_vegetarian ON public.surplus_listings;
CREATE TRIGGER ck_surplus_vegetarian
BEFORE INSERT OR UPDATE ON public.surplus_listings
FOR EACH ROW EXECUTE FUNCTION public.enforce_lacto_vegetarian_surplus();
