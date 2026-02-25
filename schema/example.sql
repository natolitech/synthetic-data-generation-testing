CREATE TABLE patients (
    patient_id    VARCHAR(20)  PRIMARY KEY,
    first_name    VARCHAR(100) NOT NULL,
    last_name     VARCHAR(100) NOT NULL,
    dob           DATE,
    gender        VARCHAR(20),
    ssn           CHAR(11),
    email         VARCHAR(255),
    phone         VARCHAR(20),
    address       VARCHAR(255),
    city          VARCHAR(100),
    state         CHAR(2),
    zip           CHAR(10),
    mrn           VARCHAR(20),
    created_at    TIMESTAMP,
    deceased_flag BOOLEAN
);

CREATE TABLE encounters (
    encounter_id       VARCHAR(20) PRIMARY KEY,
    patient_id         VARCHAR(20) REFERENCES patients(patient_id),
    encounter_type     VARCHAR(50) NOT NULL,
    admit_datetime     TIMESTAMP   NOT NULL,
    discharge_datetime TIMESTAMP,
    department         VARCHAR(100),
    attending_npi      VARCHAR(10)
);
