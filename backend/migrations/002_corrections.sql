CREATE TABLE corrections (
  id INT PRIMARY KEY AUTO_INCREMENT,
  reading_id INT NOT NULL,
  session_id INT NOT NULL,
  noise_before DECIMAL(5,2),
  noise_after DECIMAL(5,2),
  traffic_before INT,
  traffic_after INT,
  reason VARCHAR(350) NOT NULL,
  actor_id INT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX (reading_id, id),
  INDEX (session_id, id),
  FOREIGN KEY (reading_id) REFERENCES readings(id),
  FOREIGN KEY (session_id) REFERENCES sessions(id),
  FOREIGN KEY (actor_id) REFERENCES accounts(id)
);
CREATE TABLE runs (
  id INT PRIMARY KEY AUTO_INCREMENT,
  diagnostic_id INT NOT NULL,
  revision INT NOT NULL,
  correction_id INT,
  state ENUM('queued','complete','blocked','failed') NOT NULL DEFAULT 'queued',
  fingerprint CHAR(64) NOT NULL,
  snapshot JSON NOT NULL,
  result JSON,
  applied TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  finished_at TIMESTAMP NULL,
  UNIQUE KEY (diagnostic_id, revision),
  INDEX (state, id),
  FOREIGN KEY (diagnostic_id) REFERENCES diagnostics(id),
  FOREIGN KEY (correction_id) REFERENCES corrections(id)
);
ALTER TABLE diagnostics
  ADD COLUMN revision INT NOT NULL DEFAULT 0,
  ADD COLUMN basis_revision INT NOT NULL DEFAULT 0,
  ADD COLUMN arrangement ENUM('active','withdrawn') DEFAULT NULL,
  ADD COLUMN withdrawn_at TIMESTAMP NULL,
  ADD COLUMN withdraw_note VARCHAR(350) NULL;
INSERT INTO runs(diagnostic_id, revision, correction_id, state, fingerprint, snapshot, result, applied, created_at, finished_at)
  SELECT id, 0, NULL, state, fingerprint, snapshot, result, 1, created_at, finished_at FROM diagnostics;
UPDATE diagnostics SET arrangement='active' WHERE reviewed_at IS NOT NULL;
