-- Database schema for Blood_Link
-- Run this once against your Render PostgreSQL database

-- users table
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    phone_number VARCHAR(20),
    user_type VARCHAR(20) NOT NULL CHECK (user_type IN ('donor', 'ngo')),
    registration_timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- donor_profiles table
CREATE TABLE IF NOT EXISTS donor_profiles (
    donor_profile_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    blood_group VARCHAR(5) NOT NULL,
    current_location VARCHAR(255) NOT NULL,
    is_available BOOLEAN NOT NULL DEFAULT TRUE
);

-- blood_requests table
CREATE TABLE IF NOT EXISTS blood_requests (
    request_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    patient_name VARCHAR(255) NOT NULL,
    required_blood_group VARCHAR(5) NOT NULL,
    hospital_location VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- donations table
CREATE TABLE IF NOT EXISTS donations (
    donation_id SERIAL PRIMARY KEY,
    donor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    receiver_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    ngo_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    donation_date DATE NOT NULL,
    location VARCHAR(255),
    verified BOOLEAN NOT NULL DEFAULT FALSE
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_donor_profiles_location ON donor_profiles(current_location);
CREATE INDEX IF NOT EXISTS idx_donor_profiles_blood_group ON donor_profiles(blood_group);
CREATE INDEX IF NOT EXISTS idx_blood_requests_status ON blood_requests(status);
