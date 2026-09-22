-- ============================================================
-- BioBox · Datenbankfelder fuer die Gesundheitsbewertung (A-M3)
-- Von:   Atida Ashta     An: Edona Peraj
-- Werte kommen aus analyse.py / gesundheit.py (auswertung/ergebnis.csv)
-- Spezifikation: BB-SPEC-HEALTH-001
-- Hinter jeder Spalte steht der Name in ergebnis.csv.
-- ============================================================


-- 1) EINGANGSGROESSEN
--    Gehoeren zur Messung, werden einmal je Bild berechnet.
--    Bereits im Konzeptschema: greenness_index, yellow_fraction_pct.

ALTER TABLE image_measurements
    ADD COLUMN mean_r              NUMERIC(5,1),                    -- mittel_r
    ADD COLUMN mean_g              NUMERIC(5,1),                    -- mittel_g
    ADD COLUMN mean_b              NUMERIC(5,1),                    -- mittel_b
    ADD COLUMN mean_hue            NUMERIC(5,1),                    -- mittel_h  (0..179)
    ADD COLUMN mean_saturation     NUMERIC(5,1),                    -- mittel_s  (0..255)
    ADD COLUMN brown_fraction_pct  NUMERIC(5,2),                    -- braunanteil_pct
    ADD COLUMN usable              BOOLEAN NOT NULL DEFAULT false,  -- brauchbar
    ADD COLUMN quality_flags       TEXT;                            -- auffaelligkeit

-- stress_score aus dem Konzeptschema wird nicht mehr befuellt,
-- ersetzt durch health_assessments.health_score.


-- 2) REFERENZ
--    Jeder Score ist relativ zu dieser Referenz. Ohne sie ist
--    kein gespeicherter Wert erklaerbar. Neue Messreihe
--    (Kamera verschoben, nachfokussiert) = neue Referenz.

CREATE TABLE health_references (
    id                   BIGSERIAL PRIMARY KEY,
    device_id            UUID NOT NULL REFERENCES devices(id),
    first_image_id       BIGINT NOT NULL REFERENCES images(id),
    last_image_id        BIGINT NOT NULL REFERENCES images(id),
    image_count          SMALLINT NOT NULL,
    ref_greenness_index  NUMERIC(8,4) NOT NULL,
    ref_saturation       NUMERIC(5,1) NOT NULL,
    ref_hue              NUMERIC(5,1) NOT NULL,
    ref_yellow_pct       NUMERIC(5,2) NOT NULL,
    ref_brown_pct        NUMERIC(5,2) NOT NULL,
    -- Referenz wird nach Sichtpruefung manuell freigegeben
    -- (BB-SPEC-HEALTH-001, Abschnitt 4). NULL = noch nicht freigegeben.
    approved_by          UUID REFERENCES users(id),
    approved_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- 3) BEWERTUNG
--    Eigene Tabelle, weil Gewichte und Kennlinien bei der
--    Kalibrierung (PSP 3.8) noch geaendert werden. Jede Version
--    bekommt eigene Zeilen - alte Scores bleiben vergleichbar.
--    Zeilen erst anlegen, wenn eine Referenz existiert.

CREATE TABLE health_assessments (
    id                BIGSERIAL PRIMARY KEY,
    image_id          BIGINT NOT NULL REFERENCES images(id),
    reference_id      BIGINT NOT NULL REFERENCES health_references(id),
    scoring_version   TEXT NOT NULL,
    health_score      NUMERIC(5,1)                                  -- gesundheit
                      CHECK (health_score BETWEEN 0 AND 100),
    health_score_raw  NUMERIC(5,1)                                  -- gesundheit_roh
                      CHECK (health_score_raw BETWEEN 0 AND 100),
    health_category   TEXT                                          -- gesundheit_kategorie
                      CHECK (health_category IN ('sehr gut', 'gut', 'beobachten',
                                                 'auffaellig', 'kritisch', 'keine_daten')),
    health_trend_24h  NUMERIC(5,1),                                 -- gesundheit_trend_24h
    health_warnings   TEXT,                                         -- gesundheitswarnung
    score_green       NUMERIC(5,1),                                 -- score_gruen
    score_yellow      NUMERIC(5,1),                                 -- score_gelb
    score_brown       NUMERIC(5,1),                                 -- score_braun
    score_saturation  NUMERIC(5,1),                                 -- score_saettigung
    score_hue         NUMERIC(5,1),                                 -- score_farbton
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (image_id, scoring_version)
);

CREATE INDEX idx_health_image ON health_assessments (image_id);


-- ------------------------------------------------------------
-- Hinweise
--
-- health_score_raw und die score_*-Spalten sind bei unbrauchbaren
-- Bildern NULL; health_score traegt dann den geglaetteten Wert der
-- vorherigen Bilder weiter (BB-SPEC-HEALTH-001, Abschnitt 9.1).
--
-- health_warnings ist semikolongetrennt:
--   vergilbung ; nekrose ; chlorose ; entfaerbung ; wachstumsstillstand
--
-- Kategoriegrenzen: sehr gut >= 85, gut >= 70, beobachten >= 50,
--                   auffaellig >= 30, kritisch < 30
--
-- stunden_seit_start aus der CSV NICHT speichern -
-- ergibt sich aus images.captured_at.
-- ------------------------------------------------------------
