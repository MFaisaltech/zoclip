#!/bin/sh
set -eu
# Only runs on an EMPTY PostgreSQL volume. Never interpolates SQL identifiers from input.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\set migrate_password `cat /run/secrets/migrate_password`
\set runtime_password `cat /run/secrets/runtime_password`
CREATE ROLE zoclip_migrate LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'migrate_password';
CREATE ROLE zoclip_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'runtime_password';
ALTER DATABASE zoclip OWNER TO zoclip_migrate;
REVOKE ALL ON DATABASE zoclip FROM PUBLIC;
GRANT CONNECT ON DATABASE zoclip TO zoclip_runtime;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO zoclip_migrate;
GRANT USAGE ON SCHEMA public TO zoclip_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE zoclip_migrate IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO zoclip_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE zoclip_migrate IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO zoclip_runtime;
SQL
