# Shakambari AI

An AI-powered dining hall management system optimizing food preparation, reducing waste, and connecting surplus food with verified NGOs.

## Dietary policy

Shakambari AI is a strict lacto-vegetarian food management ecosystem. Active menu items and redistributable surplus must be classified as vegetarian or vegan and include ingredient information. The API and database enforce the policy; frontend filtering alone is not relied on.

On application startup, the backend migrates existing records without deleting historical transactions or relabeling historical dishes. Ineligible legacy menu items are retained but deactivated and removed from future schedules. Unverified legacy surplus remains in history but is marked ineligible.

For PostgreSQL installations applying migrations manually, run `database/migrations/003_vegetarian_policy.sql` after the preceding migrations. SQLite policy enforcement is installed by the backend migration at startup.

## Meal booking and operations

Students choose a calendar date to view the published morning, afternoon, and evening meal sessions. Each meal has its own booking cutoff, which is enforced by the API using the institution's meal schedule.

Mess administrators can review cooking quantities suggested from expected attendance and recent recorded leftovers. Superadmins can approve mess registration requests, view registered messes, and open a mess's daily meal and kitchen records.
