"""One immutable source-bound operator test, no customer financial changes."""

from alembic import op

revision = "c910a2e31f40"
down_revision = "8c42ab719e30"
branch_labels = None
depends_on = None


def upgrade():
    from zoclip.ai.live_test_models import LiveTest, LiveTestCall

    LiveTest.__table__.create(op.get_bind())
    LiveTestCall.__table__.create(op.get_bind())
    op.execute("""
    CREATE FUNCTION protect_isolated_live_test() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF ROW(NEW.id,NEW.job_id,NEW.video_id,NEW.user_id,NEW.actor_id,NEW.source_sha256,
             NEW.source_bytes,NEW.duration_ms,NEW.cap_usd,NEW.policy::text)
         IS DISTINCT FROM
         ROW(OLD.id,OLD.job_id,OLD.video_id,OLD.user_id,OLD.actor_id,OLD.source_sha256,
             OLD.source_bytes,OLD.duration_ms,OLD.cap_usd,OLD.policy::text)
         OR NEW.committed_usd < OLD.committed_usd
         OR (OLD.approval_hash IS NOT NULL AND
             ROW(NEW.approval_hash,NEW.approval_until,NEW.credential_hashes::text)
             IS DISTINCT FROM
             ROW(OLD.approval_hash,OLD.approval_until,OLD.credential_hashes::text))
         OR (OLD.state IN ('STOPPED','COMPLETED') AND NEW.state != OLD.state)
         OR (OLD.state = 'APPROVED' AND NEW.state = 'PREPARED') THEN
        RAISE EXCEPTION 'Immutable isolated test binding, budget or approval';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER isolated_test_guard BEFORE UPDATE ON isolated_live_test
      FOR EACH ROW EXECUTE FUNCTION protect_isolated_live_test();
    CREATE TRIGGER isolated_test_history BEFORE DELETE OR TRUNCATE ON isolated_live_test
      FOR EACH STATEMENT EXECUTE FUNCTION reject_financial_mutation();
    CREATE FUNCTION protect_isolated_live_call() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF ROW(NEW.id,NEW.test_id,NEW.component,NEW.ceiling_usd,NEW.created_at)
         IS DISTINCT FROM ROW(OLD.id,OLD.test_id,OLD.component,OLD.ceiling_usd,OLD.created_at)
         OR OLD.state != 'HELD' OR NEW.state NOT IN ('RECORDED','UNKNOWN') THEN
        RAISE EXCEPTION 'Immutable isolated test call or final outcome';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER isolated_call_guard BEFORE UPDATE ON isolated_live_test_calls
      FOR EACH ROW EXECUTE FUNCTION protect_isolated_live_call();
    CREATE TRIGGER isolated_call_history BEFORE DELETE OR TRUNCATE ON isolated_live_test_calls
      FOR EACH STATEMENT EXECUTE FUNCTION reject_financial_mutation();
    CREATE FUNCTION admit_isolated_live_call() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE test isolated_live_test; total numeric; expected numeric;
    BEGIN
      SELECT * INTO test FROM isolated_live_test WHERE id=NEW.test_id FOR UPDATE;
      SELECT COALESCE(SUM(ceiling_usd),0) INTO total FROM isolated_live_test_calls;
      expected := (test.policy->'ceilings'->>NEW.component)::numeric;
      IF test.state != 'APPROVED' OR test.approval_hash IS NULL
         OR test.approval_until IS NULL OR test.approval_until <= CURRENT_TIMESTAMP
         OR NEW.state != 'HELD' OR NEW.response IS NOT NULL
         OR expected IS NULL OR NEW.ceiling_usd != expected
         OR total != test.committed_usd OR total + NEW.ceiling_usd > test.cap_usd
         OR (SELECT breaker FROM system_limits WHERE id=1) IS DISTINCT FROM TRUE
         OR EXISTS (SELECT 1 FROM isolated_live_test_calls WHERE state != 'RECORDED')
         OR (NEW.component='deepgram' AND EXISTS (SELECT 1 FROM isolated_live_test_calls))
         OR (NEW.component='gemini' AND NOT EXISTS
             (SELECT 1 FROM isolated_live_test_calls WHERE component='deepgram'))
         OR (NEW.component='render' AND
             (SELECT COUNT(*) FROM isolated_live_test_calls
              WHERE component IN ('deepgram','gemini')) != 2) THEN
        RAISE EXCEPTION 'Isolated test admission refused';
      END IF;
      UPDATE isolated_live_test SET committed_usd = total + NEW.ceiling_usd WHERE id=1;
      RETURN NEW;
    END $$;
    CREATE TRIGGER isolated_call_admission BEFORE INSERT ON isolated_live_test_calls
      FOR EACH ROW EXECUTE FUNCTION admit_isolated_live_call();
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='zoclip_runtime') THEN
        REVOKE ALL ON isolated_live_test, isolated_live_test_calls FROM zoclip_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    from sqlalchemy import text

    if op.get_bind().scalar(text("SELECT EXISTS (SELECT 1 FROM isolated_live_test)")):
        raise RuntimeError("Refusing to erase isolated spending history")
    op.drop_table("isolated_live_test_calls")
    op.drop_table("isolated_live_test")
    op.execute("DROP FUNCTION admit_isolated_live_call()")
    op.execute(
        "DROP FUNCTION protect_isolated_live_call(); DROP FUNCTION protect_isolated_live_test()"
    )
