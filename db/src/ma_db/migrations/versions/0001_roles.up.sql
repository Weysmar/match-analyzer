-- The API and the worker each connect with their own role, with only the rights they need. The
-- table privileges are granted next to each table. Roles belong to the cluster, not to a database:
-- they may already exist. Their passwords are set by `ma-db upgrade`, from the environment.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ma_api') THEN
        CREATE ROLE ma_api LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ma_worker') THEN
        CREATE ROLE ma_worker LOGIN;
    END IF;
END
$$;
