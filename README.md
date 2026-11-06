# Shakambari AI

Shakambari AI is a role-based meal planning and food-waste management application for institutional dining halls. It connects student meal bookings, kitchen preparation and waste records, demand planning, and the safety-reviewed distribution of eligible surplus food to registered NGO partners.

The project addresses an operational problem: dining teams often make preparation decisions with incomplete attendance and booking information, record leftovers separately from meal planning, and lack a consistent process for offering safe surplus food to community partners. Shakambari AI provides a shared workflow and record of these activities. Its forecasts and recommendations support staff decisions; they do not replace human judgment or food-safety procedures.

## Problems the system addresses

### Uncertain meal demand

Dining teams need to prepare enough food for students who are likely to attend without consistently preparing more than will be consumed. Shakambari AI records meal bookings and attendance and provides demand predictions and preparation guidance based on available operational history.

Predictions are estimates. Their usefulness depends on the completeness, consistency, and representativeness of the institution's records.

### Disconnected preparation and waste records

When preparation quantities, consumption, attendance, and leftovers are recorded in different places, it is difficult to identify where excess food is occurring. The application connects meal schedules with kitchen preparation and outcome records so staff can review waste by meal, date, and dish.

### Unsafe or uncoordinated surplus redistribution

Surplus food should not be automatically treated as safe to distribute. Shakambari AI uses a staged process: automatic rule screening, human food-safety review, NGO collection request, mess approval, staff-confirmed handover, and NGO delivery recording. The system records these steps; it does not certify food safety.

### Limited coordination across roles

Students, kitchen staff, mess administrators, super administrators, and NGO partners need different information and permissions. Role-specific portals expose relevant workflows while the backend enforces authorization and validates state changes.

## Main workflows

### Students

- View meal schedules by date and meal session.
- Book or cancel meals, subject to the configured booking cutoff.
- Review booking history and access a QR meal pass for an eligible booking.

Cutoff rules are enforced by the backend, not only by the browser.

### Kitchen staff

- Review scheduled meals and demand information.
- Record preparation, consumption, and leftovers.
- Create surplus listings from eligible food records where applicable.

### Mess administrators

- Review demand predictions and cooking recommendations.
- Analyze operational waste data and request recommendations.
- Upload a CSV report for prototype analysis. Imported report data is analyzed in memory and is not added to operational records.
- Review surplus listings for food-safety eligibility and handle NGO collection requests.

### NGO partners

- View eligible surplus listings with available food, ingredient, storage, and use-by information.
- Request collection with a preferred pickup time and message.
- View a pickup code after approval.
- Record delivery after mess staff confirm the physical handover.

An NGO cannot mark food as picked up directly. Staff must verify the pickup code and record the quantity handed over.

### Super administrators

- Review mess registration requests.
- Approve or reject requests and view registered institutions.
- Review daily meal and kitchen records by institution.

## Prototype and AI disclosures

Not every feature described as “AI” is a trained machine-learning system.

- **Demand prediction:** uses recorded bookings, attendance, and operational history where available. Results depend on historical data quality and should be reviewed by staff.
- **Cooking recommendations:** provide guidance derived from available predictions and recent waste records. They are decision support, not automatic menu or preparation changes.
- **Uploaded report analysis:** analyzes a user-provided CSV using aggregation and simple rules. It is a prototype, does not train a model, and does not persist the imported report as operational data.
- **Food-safety screening:** applies configured rules and supports a human review process. Passing automatic checks does not mean food is certified safe for redistribution.

Demonstration or seeded records are synthetic and should not be interpreted as real institutional performance.

## Architecture

The project uses a React and TypeScript frontend with a FastAPI backend. The backend exposes a JSON API under `/api`, validates requests, enforces role permissions, and stores records through SQLAlchemy.

- **Frontend:** React, TypeScript, Vite, React Router, Recharts, and Tailwind CSS.
- **Backend:** Python, FastAPI, Pydantic, and SQLAlchemy.
- **Database:** SQLite for local development; PostgreSQL is supported for deployment.
- **Authentication:** bearer-token authentication with configurable email OTP and account protections.
- **Uploads and generated artifacts:** configurable local storage, with upload size limits.
- **Deployment:** Docker-based API deployment configuration is provided for Render. Docker Compose provides a local PostgreSQL database and API service.

### Repository layout

```text
backend/
  app/
    routers/       API routes for authentication, meals, bookings, kitchen, waste,
                   surplus, administration, alerts, and related workflows
    services/      Forecasting, analytics, storage, email, and supporting logic
  tests/           Backend tests
  Dockerfile
database/
  migrations/      SQL migrations, including policy and authentication changes
frontend/
  src/
    pages/         Role-specific application pages
    App.tsx        Routes, navigation, and authenticated application shell
  public/          Static assets and app icons
docker-compose.yml
render.yaml
