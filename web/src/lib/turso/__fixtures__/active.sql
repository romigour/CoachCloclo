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
INSERT INTO "activity" VALUES(8,9008,'2026-03-17','trail_running',0.0,0.0,NULL,NULL,NULL,'{}',NULL,NULL);
INSERT INTO "activity" VALUES(9,9009,'2026-03-18','running',2700.0,9000.0,NULL,NULL,NULL,'{"hrTimeInZone_1": 100.0, "hrTimeInZone_2": 200.0, "hrTimeInZone_3": 300.0, "hrTimeInZone_4": 400.0, "hrTimeInZone_5": 500.0}',NULL,NULL);
INSERT INTO "activity" VALUES(10,9010,'2026-03-19','running',2700.0,9000.0,NULL,NULL,NULL,'{"hrTimeInZone_1": 100.0, "hrTimeInZone_2": 200.0, "hrTimeInZone_3": 300.0, "hrTimeInZone_4": 400.0}',NULL,NULL);
INSERT INTO "activity" VALUES(11,9011,'2026-03-08','running',2700.0,9000.0,NULL,NULL,NULL,'{}',6,'manual');
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
INSERT INTO "appstate" VALUES('schema_version','{"v": 5}');
INSERT INTO "appstate" VALUES('history','{"status": "done", "imported": 42, "error": null, "finished_at": "2026-11-10T08:00:00Z"}');
CREATE TABLE athletesnapshot (
	id INTEGER NOT NULL, 
	date DATE NOT NULL, 
	vo2max FLOAT, 
	hr_max INTEGER, 
	hr_rest INTEGER, 
	threshold_hr INTEGER, 
	threshold_pace_s_km FLOAT, 
	zones_json VARCHAR NOT NULL, 
	hr_rest_source VARCHAR, 
	hr_rest_nights INTEGER, 
	PRIMARY KEY (id)
);
INSERT INTO "athletesnapshot" VALUES(1,'2026-02-20',50.0,188,52,NULL,310.0,'{"pace":{"récup":[403,450],"EF":[372,409],"marathon":[329,347],"seuil":[304,319],"VMA":[273,288]},"hr":{"Z1":[120,134],"Z2":[134,147],"Z3":[147,161],"Z4":[161,174],"Z5":[174,188]},"source":["lactate_threshold","karvonen"]}',NULL,NULL);
INSERT INTO "athletesnapshot" VALUES(2,'2026-03-01',52.0,190,50,NULL,300.0,'{"pace":{"récup":[390,435],"EF":[360,396],"marathon":[318,336],"seuil":[294,309],"VMA":[264,279]},"hr":{"Z1":[120,134],"Z2":[134,148],"Z3":[148,162],"Z4":[162,176],"Z5":[176,190]},"source":["lactate_threshold","karvonen"]}',NULL,NULL);
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
	adjust_due BOOLEAN DEFAULT '0' NOT NULL, 
	adjust_notes_json VARCHAR DEFAULT '[]' NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "cycle" VALUES(1,'2026-03-01 08:00:00.000000','active','2026-03-02','2026-03-22',3,'["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]','dimanche',1,1,0,NULL,0,'[]');
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
	notes VARCHAR, 
	PRIMARY KEY (id)
);
INSERT INTO "goal" VALUES(1,'2026-03-01 08:00:00.000000','route',21.1,300,'2026-03-15',3,NULL,'{"distance_km": 21.1, "d_plus_m": 300}','active','2026-03-02',1,6600,'user','["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'principal',NULL);
INSERT INTO "goal" VALUES(2,'2026-03-01 08:00:00.000000','trail',42.0,2000,'2026-03-22',3,NULL,NULL,'active','2026-03-02',1,NULL,'claude','["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'secondaire',NULL);
INSERT INTO "goal" VALUES(3,'2026-03-01 08:00:00.000000','trail',80.0,5000,'2026-09-06',3,NULL,NULL,'active','2026-03-02',0,NULL,NULL,'["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'principal',NULL);
INSERT INTO "goal" VALUES(4,'2026-03-01 08:00:00.000000','route',10.0,0,'2025-11-02',3,NULL,NULL,'done','2026-03-02',1,2700,'user','["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'plaisir',NULL);
INSERT INTO "goal" VALUES(5,'2026-03-01 08:00:00.000000','trail',42.0,2000,'2026-04-12',3,NULL,NULL,'archived','2026-03-02',1,NULL,NULL,'["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]',NULL,0,'principal',NULL);
CREATE TABLE gpxfile (
	goal_id INTEGER NOT NULL, 
	data BLOB NOT NULL, 
	PRIMARY KEY (goal_id)
);
CREATE TABLE llmusage (
	id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	kind VARCHAR NOT NULL, 
	mode VARCHAR, 
	model VARCHAR, 
	attempts INTEGER NOT NULL, 
	input_tokens INTEGER NOT NULL, 
	output_tokens INTEGER NOT NULL, 
	cost_usd FLOAT, 
	duration_ms INTEGER NOT NULL, 
	status VARCHAR NOT NULL, 
	PRIMARY KEY (id)
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
	view_json VARCHAR, 
	view_updated_at DATETIME, 
	advice_json VARCHAR, 
	advice_at DATETIME, 
	advice_hash VARCHAR, 
	PRIMARY KEY (id)
);
INSERT INTO "racestrategy" VALUES(1,1,'{"start_time":"08:00","carbs_g_h":null,"water_ml_h":null,"carry_ml":1000,"aid_stations":[]}','{"captured_on":"2026-11-04","pred_5k_s":null,"pred_10k_s":null,"pred_half_s":null,"pred_marathon_s":null,"threshold_pace_s_km":300,"hr":{"Z1":[120,134],"Z2":[134,148],"Z3":[148,162],"Z4":[162,176],"Z5":[176,190]}}',NULL,NULL,NULL,NULL,NULL,NULL,'{"goal_id":1,"goal_type":"route","race_date":"2026-03-15","settings":{"start_time":"08:00","carbs_g_h":null,"water_ml_h":null,"carry_ml":1000,"aid_stations":[]},"target_time_s":6600,"target_source":"user","basis_date":"2026-11-04","profile":null,"plan":{"distance_km":21.1,"eq_km":21.1,"stops_s":0,"target_time_s":6600,"reference_time_s":6600,"segments":[{"kind":"plat","start_km":0.0,"end_km":1.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":1,"avg_grade_pct":0.0,"time_s":319,"pace_s_km":319,"elapsed_s":319,"clock":"08:05","target_kind":"pace","target_low":314,"target_high":324,"target_zone":null},{"kind":"plat","start_km":1.0,"end_km":2.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":2,"avg_grade_pct":0.0,"time_s":319,"pace_s_km":319,"elapsed_s":637,"clock":"08:11","target_kind":"pace","target_low":314,"target_high":324,"target_zone":null},{"kind":"plat","start_km":2.0,"end_km":3.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":3,"avg_grade_pct":0.0,"time_s":316,"pace_s_km":316,"elapsed_s":953,"clock":"08:16","target_kind":"pace","target_low":311,"target_high":321,"target_zone":null},{"kind":"plat","start_km":3.0,"end_km":4.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":4,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":1266,"clock":"08:21","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":4.0,"end_km":5.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":5,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":1578,"clock":"08:26","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":5.0,"end_km":6.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":6,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":1890,"clock":"08:32","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":6.0,"end_km":7.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":7,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":2203,"clock":"08:37","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":7.0,"end_km":8.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":8,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":2515,"clock":"08:42","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":8.0,"end_km":9.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":9,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":2828,"clock":"08:47","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":9.0,"end_km":10.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":10,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":3140,"clock":"08:52","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":10.0,"end_km":11.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":11,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":3452,"clock":"08:58","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":11.0,"end_km":12.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":12,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":3765,"clock":"09:03","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":12.0,"end_km":13.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":13,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":4077,"clock":"09:08","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":13.0,"end_km":14.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":14,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":4390,"clock":"09:13","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":14.0,"end_km":15.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":15,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":4702,"clock":"09:18","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":15.0,"end_km":16.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":16,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":5015,"clock":"09:24","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":16.0,"end_km":17.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":17,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":5327,"clock":"09:29","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":17.0,"end_km":18.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":18,"avg_grade_pct":0.0,"time_s":312,"pace_s_km":312,"elapsed_s":5639,"clock":"09:34","target_kind":"pace","target_low":307,"target_high":317,"target_zone":null},{"kind":"plat","start_km":18.0,"end_km":19.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":19,"avg_grade_pct":0.0,"time_s":311,"pace_s_km":311,"elapsed_s":5950,"clock":"09:39","target_kind":"pace","target_low":306,"target_high":316,"target_zone":null},{"kind":"plat","start_km":19.0,"end_km":20.0,"eq_km":1.0,"d_plus_m":0,"d_minus_m":0,"index":20,"avg_grade_pct":0.0,"time_s":309,"pace_s_km":309,"elapsed_s":6260,"clock":"09:44","target_kind":"pace","target_low":304,"target_high":314,"target_zone":null},{"kind":"plat","start_km":20.0,"end_km":21.1,"eq_km":1.1000000000000014,"d_plus_m":0,"d_minus_m":0,"index":21,"avg_grade_pct":0.0,"time_s":340,"pace_s_km":309,"elapsed_s":6600,"clock":"09:50","target_kind":"pace","target_low":304,"target_high":314,"target_zone":null}],"aid_passages":[],"nutrition":[],"warnings":["Fichier GPX introuvable : découpage sans profil"]},"workout_id":null,"export_error":null,"export_stale":false,"guide":{"band":"semi","reference_time_s":6600,"avg_pace_s_km":313,"phases":[{"name":"Départ","start_km":0.0,"end_km":2.0,"pace_low_s_km":313,"pace_high_s_km":323,"hr_zone":null,"hr_low":null,"hr_high":null,"elapsed_end_s":637,"clock_end":"08:11","terrain":[],"advice":"Pars un peu moins vite que ton allure moyenne. Laisse le peloton s''étirer et trouve ta place. Tu ne gagnes rien à aller vite ici, tu peux tout perdre."},{"name":"Installation","start_km":2.0,"end_km":8.5,"pace_low_s_km":308,"pace_high_s_km":318,"hr_zone":null,"hr_low":null,"hr_high":null,"elapsed_end_s":2672,"clock_end":"08:45","terrain":[],"advice":"Cale-toi sur ton allure et n''en bouge plus. Respiration régulière, foulée souple. Si tu es en avance sur tes passages, ne creuse pas l''écart."},{"name":"Cœur de course","start_km":8.5,"end_km":18.0,"pace_low_s_km":307,"pace_high_s_km":317,"hr_zone":null,"hr_low":null,"hr_high":null,"elapsed_end_s":5639,"clock_end":"09:34","terrain":[],"advice":"C''est ici que la course se joue. L''effort monte alors que l''allure reste la même : c''est normal. Pense à ta posture et prends tes gels à l''heure prévue."},{"name":"Final","start_km":18.0,"end_km":21.1,"pace_low_s_km":305,"pace_high_s_km":315,"hr_zone":null,"hr_low":null,"hr_high":null,"elapsed_end_s":6600,"clock_end":"09:50","terrain":[],"advice":"Si tu te sens bien, accélère un peu. Sinon, tiens simplement ton allure. Va chercher les coureurs devant toi, un par un."}],"splits":[{"km":5.0,"label":"5 km","elapsed_s":1578,"clock":"08:26"},{"km":10.0,"label":"10 km","elapsed_s":3140,"clock":"08:52"},{"km":15.0,"label":"15 km","elapsed_s":4702,"clock":"09:18"},{"km":20.0,"label":"20 km","elapsed_s":6260,"clock":"09:44"},{"km":21.1,"label":"Arrivée","elapsed_s":6600,"clock":"09:50"}],"nutrition":{"carbs_g_h":45,"water_ml_h":400,"recommended":true,"principle":"Entre 1 h 15 et 2 h 30, 30 à 60 g de glucides par heure t''aident à tenir l''allure jusqu''au bout. Prends tes gels à l''heure prévue, avec quelques gorgées d''eau. Bois à ta soif aux ravitos.","intakes":[{"km":7.6,"clock":"08:40","what":"Gel (25 g) + quelques gorgées"},{"km":14.0,"clock":"09:13","what":"Gel (25 g) + quelques gorgées"}]},"morning":[{"clock":"05:00","label":"Petit-déjeuner : un repas connu, riche en glucides, pauvre en fibres et en graisses"},{"clock":"07:00","label":"Arrivée sur place : toilettes, dépôt du sac, dernier coup d''œil au départ"},{"clock":"07:35","label":"Échauffement : 10 min de footing"},{"clock":"08:00","label":"Départ"}],"preparation":[{"title":"La semaine d''avant","items":["Réduis le volume d''environ un tiers. Garde une courte séance à allure semi en début de semaine.","Ne change rien : mêmes chaussures, mêmes repas, mêmes gels qu''à l''entraînement.","Dors bien toute la semaine. La nuit de l''avant-veille compte plus que la dernière."]},{"title":"La veille","items":["Prépare ton sac : dossard, épingles, tenue, chaussures, montre chargée.","Repère l''accès au départ : trajet, parking ou transports, heure à laquelle partir.","Dîner habituel, riche en glucides, pas trop tard. Évite l''alcool et les plats nouveaux.","Couche-toi à l''heure habituelle. Si tu dors mal, ce n''est pas grave.","Fais un footing très court avec 2 ou 3 accélérations, ou repose-toi."]},{"title":"Le matin","items":["Rien de nouveau aujourd''hui : ni chaussures, ni tenue, ni gels.","Bois quelques gorgées d''eau jusqu''à une heure avant le départ, puis passe aux toilettes.","S''il fait froid, garde un vieux haut à jeter dans le sas de départ."]}]},"advice":{"tips":[{"title":"Conseil 1","text":"Texte du conseil 1."},{"title":"Conseil 2","text":"Texte du conseil 2."},{"title":"Conseil 3","text":"Texte du conseil 3."}]},"advice_at":"2026-03-10T09:00:00Z","advice_stale":true}','2026-03-11 12:00:00.000000','{"tips": [{"title": "Conseil 1", "text": "Texte du conseil 1."}, {"title": "Conseil 2", "text": "Texte du conseil 2."}, {"title": "Conseil 3", "text": "Texte du conseil 3."}]}','2026-03-10 09:00:00.000000','ancien');
INSERT INTO "racestrategy" VALUES(2,2,'{"start_time":"08:00","carbs_g_h":null,"water_ml_h":null,"carry_ml":1000,"aid_stations":[]}','{"captured_on":"2026-11-04","pred_5k_s":null,"pred_10k_s":null,"pred_half_s":null,"pred_marathon_s":null,"threshold_pace_s_km":300,"hr":{"Z1":[120,134],"Z2":[134,148],"Z3":[148,162],"Z4":[162,176],"Z5":[176,190]}}',NULL,NULL,NULL,NULL,NULL,NULL,'{"goal_id":2,"goal_type":"trail","race_date":"2026-03-22","settings":{"start_time":"08:00","carbs_g_h":null,"water_ml_h":null,"carry_ml":1000,"aid_stations":[]},"target_time_s":null,"target_source":"claude","basis_date":"2026-11-04","profile":null,"plan":{"distance_km":42.0,"eq_km":42.0,"stops_s":0,"target_time_s":null,"reference_time_s":13730,"segments":[{"kind":"plat","start_km":0.0,"end_km":2.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":1,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":654,"clock":"08:11","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":2.0,"end_km":4.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":2,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":1308,"clock":"08:22","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":4.0,"end_km":6.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":3,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":1961,"clock":"08:33","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":6.0,"end_km":8.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":4,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":2615,"clock":"08:44","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":8.0,"end_km":10.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":5,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":3269,"clock":"08:54","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":10.0,"end_km":12.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":6,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":3923,"clock":"09:05","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":12.0,"end_km":14.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":7,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":4577,"clock":"09:16","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":14.0,"end_km":16.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":8,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":5230,"clock":"09:27","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":16.0,"end_km":18.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":9,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":5884,"clock":"09:38","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":18.0,"end_km":20.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":10,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":6538,"clock":"09:49","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":20.0,"end_km":22.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":11,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":7192,"clock":"10:00","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":22.0,"end_km":24.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":12,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":7846,"clock":"10:11","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":24.0,"end_km":26.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":13,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":8500,"clock":"10:22","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":26.0,"end_km":28.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":14,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":9153,"clock":"10:33","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":28.0,"end_km":30.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":15,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":9807,"clock":"10:43","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":30.0,"end_km":32.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":16,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":10461,"clock":"10:54","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":32.0,"end_km":34.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":17,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":11115,"clock":"11:05","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":34.0,"end_km":36.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":18,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":11769,"clock":"11:16","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":36.0,"end_km":38.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":19,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":12422,"clock":"11:27","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":38.0,"end_km":40.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":20,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":13076,"clock":"11:38","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"},{"kind":"plat","start_km":40.0,"end_km":42.0,"eq_km":2.0,"d_plus_m":0,"d_minus_m":0,"index":21,"avg_grade_pct":0.0,"time_s":654,"pace_s_km":327,"elapsed_s":13730,"clock":"11:49","target_kind":"hr","target_low":148,"target_high":162,"target_zone":"Z3"}],"aid_passages":[],"nutrition":[{"from_name":"Départ","to_name":"Arrivée","from_km":0.0,"to_km":42.0,"duration_s":13730,"carbs_g":286,"water_ml":1907,"over_capacity":true}],"warnings":[]},"workout_id":null,"export_error":null,"export_stale":false,"guide":{"band":"marathon","reference_time_s":13730,"avg_pace_s_km":null,"phases":[{"name":"Départ","start_km":0.0,"end_km":4.0,"pace_low_s_km":null,"pace_high_s_km":null,"hr_zone":"Z2","hr_low":134,"hr_high":148,"elapsed_end_s":1373,"clock_end":"08:23","terrain":[],"advice":"Ne suis pas le peloton : ceux qui partent vite marcheront plus tard. Reste sous ta zone FC et marche dès la première vraie montée."},{"name":"Installation","start_km":4.0,"end_km":17.0,"pace_low_s_km":null,"pace_high_s_km":null,"hr_zone":"Z3","hr_low":148,"hr_high":162,"elapsed_end_s":5492,"clock_end":"09:32","terrain":[],"advice":"Installe ta routine : quelques gorgées souvent, de quoi manger toutes les 30 à 40 minutes. Marche tôt dans les montées, cours souple sur le plat. Au ravito, remplis tes flasques avant de manger."},{"name":"Cœur de course","start_km":17.0,"end_km":35.5,"pace_low_s_km":null,"pace_high_s_km":null,"hr_zone":"Z3","hr_low":148,"hr_high":162,"elapsed_end_s":11670,"clock_end":"11:15","terrain":[],"advice":"Mange avant d''avoir faim, bois avant d''avoir soif. Garde ta FC dans la zone, même si d''autres te doublent. Ménage tes cuisses dans les descentes : petits pas, appuis légers."},{"name":"Final","start_km":35.5,"end_km":42.0,"pace_low_s_km":null,"pace_high_s_km":null,"hr_zone":"Z3","hr_low":148,"hr_high":162,"elapsed_end_s":13730,"clock_end":"11:49","terrain":[],"advice":"Tu as gardé du jus : c''est le moment de t''en servir. Relance dès que le terrain le permet. Reste prudent en descente, les chutes arrivent avec la fatigue."}],"splits":[],"nutrition":{"carbs_g_h":75,"water_ml_h":500,"recommended":true,"principle":"Au-delà de 2 h 30, la nutrition décide de ta course : vise 60 à 90 g de glucides par heure. Mange dès la première heure, peu à la fois et souvent. Alterne sucré et salé, et bois à ta soif. Le tableau par tronçon dit quoi emporter entre deux ravitos.","intakes":[]},"morning":[{"clock":"05:00","label":"Petit-déjeuner : un repas connu, riche en glucides, pauvre en fibres et en graisses"},{"clock":"07:00","label":"Arrivée sur place : toilettes, dépôt du sac, dernier coup d''œil au départ"},{"clock":"07:45","label":"Échauffement : 5 min de mobilité"},{"clock":"08:00","label":"Départ"}],"preparation":[{"title":"La semaine d''avant","items":["Tu es en affûtage : volume réduit, quelques rappels à allure marathon. La forme est là : tu ne peux plus la gagner, seulement la perdre.","Ne change rien : mêmes chaussures, mêmes repas, mêmes gels qu''à l''entraînement.","Dors bien toute la semaine. La nuit de l''avant-veille compte plus que la dernière.","Les 2 derniers jours, mange plus de glucides à chaque repas : pâtes, riz, pain, pommes de terre. Réduis les fibres et les graisses pour garder le ventre léger.","Regarde le profil : repère les grandes montées, les longues descentes et les ravitos.","Vérifie le matériel obligatoire et fais une sortie avec ton sac chargé.","Consulte la météo du parcours, en altitude aussi, et adapte tes affaires."]},{"title":"La veille","items":["Prépare ton sac : dossard, épingles, tenue, chaussures, montre chargée.","Repère l''accès au départ : trajet, parking ou transports, heure à laquelle partir.","Dîner habituel, riche en glucides, pas trop tard. Évite l''alcool et les plats nouveaux.","Couche-toi à l''heure habituelle. Si tu dors mal, ce n''est pas grave.","Repos, ou 15 à 20 min de footing très facile.","Prépare ton sac de course : matériel obligatoire, flasques, nourriture, coupe-vent. Charge montre et téléphone."]},{"title":"Le matin","items":["Rien de nouveau aujourd''hui : ni chaussures, ni tenue, ni gels.","Bois quelques gorgées d''eau jusqu''à une heure avant le départ, puis passe aux toilettes.","Vérifie ton sac une dernière fois : matériel obligatoire, eau, nourriture.","Mets de la crème anti-frottements aux endroits sensibles : pieds, aisselles, entrejambe."]}]},"advice":null,"advice_at":null,"advice_stale":false}','2026-03-11 12:00:00.000000',NULL,NULL,NULL);
CREATE TABLE session (
	id INTEGER NOT NULL, 
	cycle_id INTEGER NOT NULL, 
	week_index INTEGER NOT NULL, 
	"order" INTEGER NOT NULL, 
	suggested_day VARCHAR NOT NULL, 
	chaining_note VARCHAR, 
	type VARCHAR NOT NULL, 
	sport VARCHAR NOT NULL, 
	d_plus_m INTEGER, 
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
	export_hr_zones_json VARCHAR, 
	PRIMARY KEY (id)
);
INSERT INTO "session" VALUES(1,1,1,1,'mardi',NULL,'EF','run',NULL,'hr','EF mardi','Description de la séance 1.','[{"kind": "warmup", "zone": "Z2", "duration_s": 600}]',NULL,NULL,'done',NULL,NULL,NULL,NULL,NULL,NULL,0,NULL);
INSERT INTO "session" VALUES(2,1,1,2,'jeudi','Après le vélo','seuil','run',NULL,'pace','Seuil jeudi','Description de la séance 2.','[{"kind": "warmup", "zone": "EF", "duration_s": 600}, {"repeat": 5, "steps": [{"kind": "active", "zone": "seuil", "distance_m": 1000}, {"kind": "recovery", "zone": "récup", "duration_s": 90}]}, {"kind": "cooldown", "zone": "EF", "duration_s": 300}]',NULL,NULL,'missed',NULL,NULL,NULL,NULL,NULL,NULL,0,NULL);
INSERT INTO "session" VALUES(3,1,1,3,'dimanche',NULL,'sortie longue','run',600,'hr','Sortie longue','Description de la séance 3.','[{"kind": "warmup", "zone": "Z2", "duration_s": 600}]',NULL,NULL,'exported','2026-03-08',111,222,NULL,NULL,NULL,0,NULL);
INSERT INTO "session" VALUES(4,1,2,1,'mardi',NULL,'EF','run',NULL,'hr','Séance en erreur','Description de la séance 4.','[{"kind": "warmup", "zone": "Z2", "duration_s": 600}]',NULL,NULL,'sync_error',NULL,NULL,NULL,'Garmin indisponible',NULL,NULL,0,NULL);
INSERT INTO "session" VALUES(5,1,2,2,'mercredi',NULL,'EF','bike',NULL,'hr','Vélo récup','Description de la séance 5.','[{"kind": "active", "zone": "Z1", "duration_s": 2400}]',NULL,NULL,'todo',NULL,NULL,NULL,NULL,NULL,NULL,0,NULL);
INSERT INTO "session" VALUES(6,1,2,3,'samedi',NULL,'EF','run',NULL,'hr','Fartlek','Description de la séance 6.','[{"kind": "warmup", "zone": "Z2", "duration_s": 600}]',NULL,NULL,'todo',NULL,NULL,NULL,NULL,NULL,NULL,0,NULL);
INSERT INTO "session" VALUES(7,1,3,1,'mardi',NULL,'EF','run',NULL,'hr','Dernier footing','Description de la séance 7.','[{"kind": "warmup", "zone": "Z2", "duration_s": 600}]',NULL,NULL,'todo',NULL,NULL,NULL,NULL,NULL,NULL,0,NULL);
INSERT INTO "session" VALUES(8,1,3,2,'dimanche',NULL,'course','run',NULL,'pace','Course objectif','Description de la séance 8.','[{"kind": "active", "zone": "marathon", "distance_m": 21100}]',NULL,NULL,'todo',NULL,NULL,NULL,NULL,NULL,NULL,0,NULL);
CREATE INDEX ix_activity_date ON activity (date);
CREATE INDEX ix_event_cycle_id ON event (cycle_id);
CREATE INDEX ix_llmusage_created_at ON llmusage (created_at);
CREATE INDEX ix_session_cycle_id ON session (cycle_id);
CREATE UNIQUE INDEX ix_activity_garmin_activity_id ON activity (garmin_activity_id);
CREATE UNIQUE INDEX ix_activitylaps_activity_id ON activitylaps (activity_id);
CREATE UNIQUE INDEX ix_race_activity_id ON race (activity_id);
CREATE UNIQUE INDEX ix_racestrategy_goal_id ON racestrategy (goal_id);
COMMIT;
