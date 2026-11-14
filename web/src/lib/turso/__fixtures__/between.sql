BEGIN TRANSACTION;
CREATE TABLE activity (
	id INTEGER NOT NULL, 
	garmin_activity_id INTEGER NOT NULL, 
	date DATE NOT NULL, 
	type_key VARCHAR NOT NULL, 
	duration_s FLOAT, 
	distance_m FLOAT, 
	d_plus_m FLOAT, 
	avg_hr FLOAT, 
	avg_pace_s_km FLOAT, 
	raw_json VARCHAR NOT NULL, 
	session_id INTEGER, 
	match_source VARCHAR, 
	PRIMARY KEY (id)
);
CREATE TABLE activitylaps (
	id INTEGER NOT NULL, 
	activity_id INTEGER NOT NULL, 
	laps_json VARCHAR NOT NULL, 
	fetched_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE appstate (
	"key" VARCHAR NOT NULL, 
	value_json VARCHAR NOT NULL, 
	PRIMARY KEY ("key")
);
INSERT INTO "appstate" VALUES('schema_version','{"v": 1}');
CREATE TABLE athletesnapshot (
	id INTEGER NOT NULL, 
	date DATE NOT NULL, 
	vo2max FLOAT, 
	hr_max INTEGER, 
	hr_rest INTEGER, 
	threshold_hr INTEGER, 
	threshold_pace_s_km FLOAT, 
	zones_json VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE cycle (
	id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	status VARCHAR NOT NULL, 
	plan_start DATE NOT NULL, 
	end_date DATE NOT NULL, 
	sessions_per_week INTEGER NOT NULL, 
	available_days_json VARCHAR NOT NULL, 
	long_run_day VARCHAR, 
	include_bike BOOLEAN NOT NULL, 
	plan_accepted BOOLEAN NOT NULL, 
	needs_generation BOOLEAN NOT NULL, 
	recovery_from_goal_id INTEGER, 
	PRIMARY KEY (id)
);
INSERT INTO "cycle" VALUES(1,'2020-01-01 08:00:00.000000','done','2020-01-06','2020-03-01',4,'["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]','samedi',0,1,0,NULL);
CREATE TABLE event (
	id INTEGER NOT NULL, 
	cycle_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	kind VARCHAR NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE, 
	max_sessions INTEGER, 
	days_json VARCHAR, 
	session_id INTEGER, 
	note VARCHAR, 
	PRIMARY KEY (id)
);
CREATE TABLE garminlock (
	id INTEGER NOT NULL, 
	holder VARCHAR NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE goal (
	id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	type VARCHAR NOT NULL, 
	distance_km FLOAT NOT NULL, 
	d_plus_m INTEGER NOT NULL, 
	race_date DATE NOT NULL, 
	sessions_per_week INTEGER NOT NULL, 
	gpx_path VARCHAR, 
	gpx_summary_json VARCHAR, 
	status VARCHAR NOT NULL, 
	plan_start DATE NOT NULL, 
	plan_accepted BOOLEAN NOT NULL, 
	target_time_s INTEGER, 
	target_source VARCHAR, 
	available_days_json VARCHAR NOT NULL, 
	long_run_day VARCHAR, 
	include_bike BOOLEAN NOT NULL, 
	priority VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "goal" VALUES(1,'2026-03-01 08:00:00.000000','trail',50.0,1000,'2099-06-01',3,NULL,NULL,'active','2099-03-02',0,NULL,NULL,'["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'principal');
CREATE TABLE gpxfile (
	goal_id INTEGER NOT NULL, 
	data BLOB NOT NULL, 
	PRIMARY KEY (goal_id)
);
CREATE TABLE personalrecord (
	id INTEGER NOT NULL, 
	kind VARCHAR NOT NULL, 
	value FLOAT NOT NULL, 
	garmin_activity_id INTEGER, 
	date DATE, 
	PRIMARY KEY (id)
);
CREATE TABLE proposal (
	id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	analysis VARCHAR NOT NULL, 
	changes_json VARCHAR NOT NULL, 
	estimates_json VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE race (
	id INTEGER NOT NULL, 
	activity_id INTEGER NOT NULL, 
	name VARCHAR, 
	official_time_s INTEGER, 
	overall_rank INTEGER, 
	overall_total INTEGER, 
	category VARCHAR, 
	category_rank INTEGER, 
	category_total INTEGER, 
	excluded BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE racestrategy (
	id INTEGER NOT NULL, 
	goal_id INTEGER NOT NULL, 
	settings_json VARCHAR NOT NULL, 
	basis_json VARCHAR NOT NULL, 
	garmin_workout_id INTEGER, 
	garmin_schedule_id INTEGER, 
	pending_old_workout_id INTEGER, 
	pending_old_schedule_id INTEGER, 
	export_error VARCHAR, 
	exported_hash VARCHAR, 
	PRIMARY KEY (id)
);
CREATE TABLE session (
	id INTEGER NOT NULL, 
	cycle_id INTEGER NOT NULL, 
	week_index INTEGER NOT NULL, 
	"order" INTEGER NOT NULL, 
	suggested_day VARCHAR NOT NULL, 
	chaining_note VARCHAR, 
	type VARCHAR NOT NULL, 
	sport VARCHAR NOT NULL, 
	target_kind VARCHAR NOT NULL, 
	title VARCHAR NOT NULL, 
	description VARCHAR NOT NULL, 
	steps_json VARCHAR NOT NULL, 
	est_duration_min FLOAT, 
	est_distance_km FLOAT, 
	status VARCHAR NOT NULL, 
	scheduled_date DATE, 
	garmin_workout_id INTEGER, 
	garmin_schedule_id INTEGER, 
	sync_error VARCHAR, 
	pending_old_workout_id INTEGER, 
	pending_old_schedule_id INTEGER, 
	pending_removal BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_activity_date ON activity (date);
CREATE INDEX ix_event_cycle_id ON event (cycle_id);
CREATE INDEX ix_session_cycle_id ON session (cycle_id);
CREATE UNIQUE INDEX ix_activity_garmin_activity_id ON activity (garmin_activity_id);
CREATE UNIQUE INDEX ix_activitylaps_activity_id ON activitylaps (activity_id);
CREATE UNIQUE INDEX ix_race_activity_id ON race (activity_id);
CREATE UNIQUE INDEX ix_racestrategy_goal_id ON racestrategy (goal_id);
COMMIT;
