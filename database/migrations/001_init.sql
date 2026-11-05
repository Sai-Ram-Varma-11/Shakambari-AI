-- PlateSense AI schema (PostgreSQL). Generated from the SQLAlchemy models.
-- NOTE: the application also creates missing tables automatically on startup.

CREATE TABLE audit_logs (
	id SERIAL NOT NULL, 
	user_id INTEGER, 
	action VARCHAR(60) NOT NULL, 
	entity VARCHAR(60), 
	entity_id INTEGER, 
	detail VARCHAR(500), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id);

CREATE TABLE institutions (
	id SERIAL NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	code VARCHAR(40) NOT NULL, 
	data_mode VARCHAR(20) NOT NULL, 
	settings JSON, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);


CREATE TABLE alerts (
	id SERIAL NOT NULL, 
	institution_id INTEGER NOT NULL, 
	kind VARCHAR(40) NOT NULL, 
	severity VARCHAR(10), 
	title VARCHAR(200), 
	what TEXT, 
	evidence TEXT, 
	why TEXT, 
	action TEXT, 
	is_resolved BOOLEAN, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(institution_id) REFERENCES institutions (id) ON DELETE CASCADE
);

CREATE INDEX ix_alerts_institution_id ON alerts (institution_id);

CREATE TABLE meal_schedules (
	id SERIAL NOT NULL, 
	institution_id INTEGER NOT NULL, 
	date DATE NOT NULL, 
	meal_type VARCHAR(20) NOT NULL, 
	cutoff_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	is_holiday BOOLEAN, 
	event VARCHAR(120), 
	headcount INTEGER, 
	service_status VARCHAR(20), 
	PRIMARY KEY (id), 
	UNIQUE (institution_id, date, meal_type), 
	FOREIGN KEY(institution_id) REFERENCES institutions (id) ON DELETE CASCADE
);

CREATE INDEX ix_sched_date ON meal_schedules (institution_id, date);

CREATE TABLE menu_items (
	id SERIAL NOT NULL, 
	institution_id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	category VARCHAR(30), 
	diet VARCHAR(20), 
	portion_kg FLOAT NOT NULL, 
	cost_per_kg FLOAT NOT NULL, 
	is_active BOOLEAN, 
	PRIMARY KEY (id), 
	UNIQUE (institution_id, name), 
	FOREIGN KEY(institution_id) REFERENCES institutions (id) ON DELETE CASCADE
);

CREATE INDEX ix_menu_items_institution_id ON menu_items (institution_id);

CREATE TABLE ml_models (
	id SERIAL NOT NULL, 
	institution_id INTEGER NOT NULL, 
	algorithm VARCHAR(60) NOT NULL, 
	metrics JSON, 
	features JSON, 
	n_train INTEGER, 
	n_test INTEGER, 
	path VARCHAR(300), 
	data_mode VARCHAR(20), 
	is_active BOOLEAN, 
	trained_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(institution_id) REFERENCES institutions (id) ON DELETE CASCADE
);

CREATE INDEX ix_ml_models_institution_id ON ml_models (institution_id);

CREATE TABLE sustainability_snapshots (
	id SERIAL NOT NULL, 
	institution_id INTEGER NOT NULL, 
	period VARCHAR(10) NOT NULL, 
	data JSON, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(institution_id) REFERENCES institutions (id) ON DELETE CASCADE
);

CREATE INDEX ix_sustainability_snapshots_institution_id ON sustainability_snapshots (institution_id);

CREATE TABLE users (
	id SERIAL NOT NULL, 
	institution_id INTEGER, 
	email VARCHAR(254) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(300) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	phone VARCHAR(30), 
	is_active BOOLEAN NOT NULL, 
	is_approved BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	last_login TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(institution_id) REFERENCES institutions (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_users_institution_id ON users (institution_id);
CREATE INDEX ix_users_role ON users (role);

CREATE TABLE attendance (
	id SERIAL NOT NULL, 
	schedule_id INTEGER NOT NULL, 
	student_id INTEGER NOT NULL, 
	was_booked BOOLEAN, 
	marked_by INTEGER, 
	marked_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (schedule_id, student_id), 
	FOREIGN KEY(schedule_id) REFERENCES meal_schedules (id) ON DELETE CASCADE, 
	FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_attendance_schedule_id ON attendance (schedule_id);

CREATE TABLE bookings (
	id SERIAL NOT NULL, 
	schedule_id INTEGER NOT NULL, 
	student_id INTEGER NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (schedule_id, student_id), 
	FOREIGN KEY(schedule_id) REFERENCES meal_schedules (id) ON DELETE CASCADE, 
	FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_bookings_schedule_id ON bookings (schedule_id);
CREATE INDEX ix_bookings_student_id ON bookings (student_id);

CREATE TABLE consumption_records (
	id SERIAL NOT NULL, 
	schedule_id INTEGER NOT NULL, 
	menu_item_id INTEGER NOT NULL, 
	consumed_qty FLOAT NOT NULL, 
	recorded_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (schedule_id, menu_item_id), 
	FOREIGN KEY(schedule_id) REFERENCES meal_schedules (id) ON DELETE CASCADE, 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id) ON DELETE CASCADE
);

CREATE INDEX ix_consumption_records_schedule_id ON consumption_records (schedule_id);

CREATE TABLE dish_preferences (
	id SERIAL NOT NULL, 
	student_id INTEGER NOT NULL, 
	menu_item_id INTEGER NOT NULL, 
	preference VARCHAR(10) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (student_id, menu_item_id), 
	FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id) ON DELETE CASCADE
);


CREATE TABLE image_observations (
	id SERIAL NOT NULL, 
	institution_id INTEGER NOT NULL, 
	schedule_id INTEGER, 
	menu_item_id INTEGER, 
	file_name VARCHAR(80) NOT NULL, 
	width INTEGER, 
	height INTEGER, 
	fmt VARCHAR(10), 
	size_bytes INTEGER, 
	predicted_label VARCHAR(40), 
	confidence FLOAT, 
	scores JSON, 
	corrected_label VARCHAR(40), 
	quantity_kg FLOAT, 
	status VARCHAR(12), 
	created_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(institution_id) REFERENCES institutions (id) ON DELETE CASCADE, 
	FOREIGN KEY(schedule_id) REFERENCES meal_schedules (id) ON DELETE SET NULL, 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id) ON DELETE SET NULL
);

CREATE INDEX ix_image_observations_institution_id ON image_observations (institution_id);

CREATE TABLE menu_recommendations (
	id SERIAL NOT NULL, 
	institution_id INTEGER NOT NULL, 
	menu_item_id INTEGER, 
	kind VARCHAR(30), 
	message TEXT, 
	evidence JSON, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(institution_id) REFERENCES institutions (id) ON DELETE CASCADE, 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id) ON DELETE SET NULL
);

CREATE INDEX ix_menu_recommendations_institution_id ON menu_recommendations (institution_id);

CREATE TABLE ngo_partners (
	user_id INTEGER NOT NULL, 
	org_name VARCHAR(200) NOT NULL, 
	registration_no VARCHAR(80), 
	address VARCHAR(300), 
	verified BOOLEAN NOT NULL, 
	verified_by INTEGER, 
	verified_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);


CREATE TABLE notifications (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	body VARCHAR(500), 
	link VARCHAR(120), 
	is_read BOOLEAN, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_notifications_user_id ON notifications (user_id);

CREATE TABLE predictions (
	id SERIAL NOT NULL, 
	schedule_id INTEGER NOT NULL, 
	menu_item_id INTEGER, 
	kind VARCHAR(12) NOT NULL, 
	value FLOAT NOT NULL, 
	lower FLOAT, 
	upper FLOAT, 
	active_bookings INTEGER, 
	model_id INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(schedule_id) REFERENCES meal_schedules (id) ON DELETE CASCADE, 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id) ON DELETE CASCADE
);

CREATE INDEX ix_predictions_schedule_id ON predictions (schedule_id);

CREATE TABLE preparation_records (
	id SERIAL NOT NULL, 
	schedule_id INTEGER NOT NULL, 
	menu_item_id INTEGER NOT NULL, 
	recommended_qty FLOAT, 
	prepared_qty FLOAT NOT NULL, 
	available_qty FLOAT, 
	recorded_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (schedule_id, menu_item_id), 
	FOREIGN KEY(schedule_id) REFERENCES meal_schedules (id) ON DELETE CASCADE, 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id) ON DELETE CASCADE
);

CREATE INDEX ix_preparation_records_schedule_id ON preparation_records (schedule_id);

CREATE TABLE ratings (
	id SERIAL NOT NULL, 
	student_id INTEGER NOT NULL, 
	menu_item_id INTEGER NOT NULL, 
	schedule_id INTEGER, 
	rating INTEGER NOT NULL, 
	comment VARCHAR(500), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (student_id, menu_item_id, schedule_id), 
	FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id) ON DELETE CASCADE, 
	FOREIGN KEY(schedule_id) REFERENCES meal_schedules (id) ON DELETE CASCADE
);

CREATE INDEX ix_ratings_menu_item_id ON ratings (menu_item_id);

CREATE TABLE schedule_dishes (
	schedule_id INTEGER NOT NULL, 
	menu_item_id INTEGER NOT NULL, 
	PRIMARY KEY (schedule_id, menu_item_id), 
	FOREIGN KEY(schedule_id) REFERENCES meal_schedules (id) ON DELETE CASCADE, 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id) ON DELETE CASCADE
);


CREATE TABLE student_profiles (
	user_id INTEGER NOT NULL, 
	diet VARCHAR(20), 
	hostel VARCHAR(80), 
	dietary_notes VARCHAR(300), 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);


CREATE TABLE surplus_listings (
	id SERIAL NOT NULL, 
	institution_id INTEGER NOT NULL, 
	schedule_id INTEGER, 
	menu_item_id INTEGER, 
	food_name VARCHAR(150) NOT NULL, 
	category VARCHAR(30) NOT NULL, 
	quantity_kg FLOAT NOT NULL, 
	portions INTEGER, 
	prepared_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	storage_condition VARCHAR(20) NOT NULL, 
	storage_temp_c FLOAT, 
	use_by TIMESTAMP WITHOUT TIME ZONE, 
	status VARCHAR(20), 
	auto_check JSON, 
	review_notes VARCHAR(300), 
	verified_by INTEGER, 
	verified_at TIMESTAMP WITHOUT TIME ZONE, 
	created_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(institution_id) REFERENCES institutions (id) ON DELETE CASCADE, 
	FOREIGN KEY(schedule_id) REFERENCES meal_schedules (id) ON DELETE SET NULL, 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id) ON DELETE SET NULL
);

CREATE INDEX ix_surplus_listings_institution_id ON surplus_listings (institution_id);
CREATE INDEX ix_surplus_listings_status ON surplus_listings (status);

CREATE TABLE waste_records (
	id SERIAL NOT NULL, 
	schedule_id INTEGER NOT NULL, 
	menu_item_id INTEGER NOT NULL, 
	leftover_qty FLOAT NOT NULL, 
	edible_qty FLOAT, 
	inedible_qty FLOAT, 
	source VARCHAR(10), 
	observation_id INTEGER, 
	notes VARCHAR(300), 
	recorded_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(schedule_id) REFERENCES meal_schedules (id) ON DELETE CASCADE, 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id) ON DELETE CASCADE
);

CREATE INDEX ix_waste_records_schedule_id ON waste_records (schedule_id);

CREATE TABLE booking_cancellations (
	id SERIAL NOT NULL, 
	booking_id INTEGER NOT NULL, 
	reason VARCHAR(200), 
	cancelled_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(booking_id) REFERENCES bookings (id) ON DELETE CASCADE
);

CREATE INDEX ix_booking_cancellations_booking_id ON booking_cancellations (booking_id);

CREATE TABLE redistribution_requests (
	id SERIAL NOT NULL, 
	listing_id INTEGER NOT NULL, 
	partner_id INTEGER NOT NULL, 
	status VARCHAR(12), 
	pickup_time TIMESTAMP WITHOUT TIME ZONE, 
	message VARCHAR(300), 
	decided_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(listing_id) REFERENCES surplus_listings (id) ON DELETE CASCADE, 
	FOREIGN KEY(partner_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_redistribution_requests_listing_id ON redistribution_requests (listing_id);
CREATE INDEX ix_redistribution_requests_partner_id ON redistribution_requests (partner_id);

CREATE TABLE collection_records (
	id SERIAL NOT NULL, 
	request_id INTEGER NOT NULL, 
	collected_kg FLOAT NOT NULL, 
	portions INTEGER, 
	delivered_to VARCHAR(200), 
	collected_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(request_id) REFERENCES redistribution_requests (id) ON DELETE CASCADE
);

CREATE INDEX ix_collection_records_request_id ON collection_records (request_id);
