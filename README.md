# Shakambari AI

An AI-powered dining hall management system optimizing food preparation, reducing waste, and connecting surplus food with verified NGOs.

## Dietary policy

Shakambari AI is a strict lacto-vegetarian food management ecosystem. Active menu items and redistributable surplus must be classified as vegetarian or vegan and include ingredient information. The API and database enforce the policy; frontend filtering alone is not relied on.

On application startup, the backend migrates existing records without deleting historical transactions or relabeling historical dishes. Ineligible legacy menu items are retained but deactivated and removed from future schedules. Unverified legacy surplus remains in history but is marked ineligible.

For PostgreSQL installations applying migrations manually, run `database/migrations/003_vegetarian_policy.sql` after the preceding migrations. SQLite policy enforcement is installed by the backend migration at startup.
