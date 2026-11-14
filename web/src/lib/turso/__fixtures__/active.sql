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
INSERT INTO "activity" VALUES(1,9001,'2026-03-03','running',2700.0,9000.0,50.0,140.0,300.0,'{"activityName": "Footing", "maxHR": 165, "startTimeLocal": "2026-03-03 07:00:00"}',1,'auto');
INSERT INTO "activity" VALUES(2,9002,'2026-03-04','cycling',3600.0,25000.0,NULL,120.0,NULL,'{"activityName": "V\u00e9lo libre"}',NULL,NULL);
INSERT INTO "activity" VALUES(3,9003,'2026-03-09','running',2700.0,9000.0,NULL,NULL,NULL,'pas du json',NULL,NULL);
INSERT INTO "activity" VALUES(4,9004,'2026-03-10','running',2700.0,9000.0,NULL,NULL,NULL,'{"maxHR": true, "vO2MaxValue": "52"}',NULL,NULL);
INSERT INTO "activity" VALUES(5,9005,'2026-03-12','running',2700.0,9000.0,NULL,NULL,NULL,'{"eventType": {"typeKey": "race"}}',NULL,NULL);
INSERT INTO "activity" VALUES(6,9006,'2026-03-15','running',6500.0,21100.0,300.0,170.0,NULL,'{"activityName": "Semi", "eventType": {"typeKey": "race"}}',NULL,NULL);
INSERT INTO "activity" VALUES(7,9007,'2026-03-16','running',2700.0,9000.0,NULL,NULL,NULL,'{"eventType": {"typeKey": "race"}}',NULL,NULL);
INSERT INTO "activity" VALUES(8,9008,'2026-03-17','running',0.0,0.0,NULL,NULL,NULL,'{}',NULL,NULL);
INSERT INTO "activity" VALUES(9,9009,'2026-03-18','running',2700.0,9000.0,NULL,NULL,NULL,'{"hrTimeInZone_1": 100.0, "hrTimeInZone_2": 200.0, "hrTimeInZone_3": 300.0, "hrTimeInZone_4": 400.0, "hrTimeInZone_5": 500.0}',NULL,NULL);
INSERT INTO "activity" VALUES(10,9010,'2026-03-19','running',2700.0,9000.0,NULL,NULL,NULL,'{"hrTimeInZone_1": 100.0, "hrTimeInZone_2": 200.0, "hrTimeInZone_3": 300.0, "hrTimeInZone_4": 400.0}',NULL,NULL);
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
INSERT INTO "appstate" VALUES('history','{"status": "done", "imported": 42, "error": null}');
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
INSERT INTO "athletesnapshot" VALUES(1,'2026-02-20',50.0,188,52,NULL,310.0,'{"pace":{"récup":[403,450],"EF":[372,409],"marathon":[329,347],"seuil":[304,319],"VMA":[273,288]},"hr":{"Z1":[120,134],"Z2":[134,147],"Z3":[147,161],"Z4":[161,174],"Z5":[174,188]},"source":["lactate_threshold","karvonen"]}');
INSERT INTO "athletesnapshot" VALUES(2,'2026-03-01',52.0,190,50,NULL,300.0,'{"pace":{"récup":[390,435],"EF":[360,396],"marathon":[318,336],"seuil":[294,309],"VMA":[264,279]},"hr":{"Z1":[120,134],"Z2":[134,148],"Z3":[148,162],"Z4":[162,176],"Z5":[176,190]},"source":["lactate_threshold","karvonen"]}');
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
INSERT INTO "cycle" VALUES(1,'2026-03-01 08:00:00.000000','active','2026-03-02','2026-03-22',3,'["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]','dimanche',1,1,0,NULL);
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
INSERT INTO "event" VALUES(1,1,'2026-03-01 08:00:00.000000','injury','2026-03-10',NULL,NULL,NULL,NULL,'Tendinite');
INSERT INTO "event" VALUES(2,1,'2026-03-01 08:00:00.000000','light_week','2026-03-16','2026-03-22',2,'["mardi", "dimanche"]',NULL,'Déplacement');
INSERT INTO "event" VALUES(3,1,'2026-03-01 08:00:00.000000','fatigue','2026-03-05','2026-03-05',NULL,NULL,2,NULL);
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
INSERT INTO "goal" VALUES(1,'2026-03-01 08:00:00.000000','route',21.1,300,'2026-03-15',3,NULL,'{"distance_km": 21.1, "d_plus_m": 300}','active','2026-03-02',1,6600,'user','["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'principal');
INSERT INTO "goal" VALUES(2,'2026-03-01 08:00:00.000000','trail',42.0,2000,'2026-03-22',3,NULL,NULL,'active','2026-03-02',1,NULL,'claude','["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'secondaire');
INSERT INTO "goal" VALUES(3,'2026-03-01 08:00:00.000000','trail',80.0,5000,'2026-09-06',3,NULL,NULL,'active','2026-03-02',0,NULL,NULL,'["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'principal');
INSERT INTO "goal" VALUES(4,'2026-03-01 08:00:00.000000','route',10.0,0,'2025-11-02',3,NULL,NULL,'done','2026-03-02',1,2700,'user','["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'plaisir');
INSERT INTO "goal" VALUES(5,'2026-03-01 08:00:00.000000','trail',42.0,2000,'2026-04-12',3,NULL,NULL,'archived','2026-03-02',1,NULL,NULL,'["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'principal');
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
INSERT INTO "personalrecord" VALUES(1,'5k',1350.0,9001,'2026-03-03');
INSERT INTO "personalrecord" VALUES(2,'longest_run',21100.0,NULL,NULL);
CREATE TABLE proposal (
	id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	analysis VARCHAR NOT NULL, 
	changes_json VARCHAR NOT NULL, 
	estimates_json VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "proposal" VALUES(1,'2026-03-01 08:00:00.000000','Charge un peu haute, on allège.','[]','[]','pending');
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
INSERT INTO "race" VALUES(1,6,'Semi de test',6480,120,900,'V1H',15,100,0);
INSERT INTO "race" VALUES(2,7,'Course exclue',NULL,NULL,NULL,NULL,NULL,NULL,1);
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
INSERT INTO "session" VALUES(1,1,1,1,'mardi',NULL,'EF','run','hr','EF mardi','Description de la séance 1.','[{"kind": "warmup", "zone": "Z2", "duration_s": 600}]',NULL,NULL,'done',NULL,NULL,NULL,NULL,NULL,NULL,0);
INSERT INTO "session" VALUES(2,1,1,2,'jeudi','Après le vélo','seuil','run','pace','Seuil jeudi','Description de la séance 2.','[{"kind": "warmup", "zone": "EF", "duration_s": 600}, {"repeat": 5, "steps": [{"kind": "active", "zone": "seuil", "distance_m": 1000}, {"kind": "recovery", "zone": "récup", "duration_s": 90}]}, {"kind": "cooldown", "zone": "EF", "duration_s": 300}]',NULL,NULL,'missed',NULL,NULL,NULL,NULL,NULL,NULL,0);
INSERT INTO "session" VALUES(3,1,1,3,'dimanche',NULL,'sortie longue','run','hr','Sortie longue','Description de la séance 3.','[{"kind": "warmup", "zone": "Z2", "duration_s": 600}]',NULL,NULL,'exported','2026-03-08',111,222,NULL,NULL,NULL,0);
INSERT INTO "session" VALUES(4,1,2,1,'mardi',NULL,'EF','run','hr','Séance en erreur','Description de la séance 4.','[{"kind": "warmup", "zone": "Z2", "duration_s": 600}]',NULL,NULL,'sync_error',NULL,NULL,NULL,'Garmin indisponible',NULL,NULL,0);
INSERT INTO "session" VALUES(5,1,2,2,'mercredi',NULL,'EF','bike','hr','Vélo récup','Description de la séance 5.','[{"kind": "active", "zone": "Z1", "duration_s": 2400}]',NULL,NULL,'todo',NULL,NULL,NULL,NULL,NULL,NULL,0);
INSERT INTO "session" VALUES(6,1,2,3,'samedi',NULL,'EF','run','hr','Fartlek','Description de la séance 6.','[{"kind": "warmup", "zone": "Z2", "duration_s": 600}]',NULL,NULL,'todo',NULL,NULL,NULL,NULL,NULL,NULL,0);
INSERT INTO "session" VALUES(7,1,3,1,'mardi',NULL,'EF','run','hr','Dernier footing','Description de la séance 7.','[{"kind": "warmup", "zone": "Z2", "duration_s": 600}]',NULL,NULL,'todo',NULL,NULL,NULL,NULL,NULL,NULL,0);
INSERT INTO "session" VALUES(8,1,3,2,'dimanche',NULL,'course','run','pace','Course objectif','Description de la séance 8.','[{"kind": "active", "zone": "marathon", "distance_m": 21100}]',NULL,NULL,'todo',NULL,NULL,NULL,NULL,NULL,NULL,0);
CREATE INDEX ix_activity_date ON activity (date);
CREATE INDEX ix_event_cycle_id ON event (cycle_id);
CREATE INDEX ix_session_cycle_id ON session (cycle_id);
CREATE UNIQUE INDEX ix_activity_garmin_activity_id ON activity (garmin_activity_id);
CREATE UNIQUE INDEX ix_activitylaps_activity_id ON activitylaps (activity_id);
CREATE UNIQUE INDEX ix_race_activity_id ON race (activity_id);
CREATE UNIQUE INDEX ix_racestrategy_goal_id ON racestrategy (goal_id);
COMMIT;
