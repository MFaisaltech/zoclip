"""phase5 private clips, revisions and outputs"""

import sqlalchemy as sa

from alembic import op

revision = "a580f314c921"
down_revision = "91731e381b3a"
branch_labels = None
depends_on = None


def identity():
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.drop_constraint(op.f("ck_jobs_kind"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_kind"), "jobs", "kind IN ('VALIDATE','IMPORT','PROCESS','RENDER')"
    )
    op.create_table(
        "clips",
        *identity(),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("video_id", sa.Uuid(), sa.ForeignKey("source_videos.id"), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("suggestion_id", sa.Uuid(), sa.ForeignKey("clip_suggestions.id"), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("suggestion_id"),
        sa.CheckConstraint("revision > 0", name=op.f("ck_clips_revision")),
    )
    for column in ("user_id", "video_id", "job_id"):
        op.create_index(f"ix_clips_{column}", "clips", [column])
    op.create_table(
        "clip_revisions",
        *identity(),
        sa.Column("clip_id", sa.Uuid(), sa.ForeignKey("clips.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clip_id", "number"),
        sa.CheckConstraint("number > 0", name=op.f("ck_clip_revisions_number")),
    )
    op.create_index("ix_clip_revisions_clip_id", "clip_revisions", ["clip_id"])
    op.create_table(
        "render_outputs",
        *identity(),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("clip_id", sa.Uuid(), sa.ForeignKey("clips.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("object_id", sa.Uuid(), sa.ForeignKey("storage_objects.id"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clip_id", "revision"),
        sa.UniqueConstraint("object_id"),
        sa.CheckConstraint("revision > 0 AND failures >= 0", name=op.f("ck_render_outputs_counts")),
        sa.CheckConstraint(
            "state IN ('PENDING','COMPLETE','FAILED','DELETED')",
            name=op.f("ck_render_outputs_state"),
        ),
    )
    for column in ("user_id", "clip_id", "job_id"):
        op.create_index(f"ix_render_outputs_{column}", "render_outputs", [column])


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM clips) "
            "OR EXISTS (SELECT 1 FROM jobs WHERE kind = 'RENDER')"
        )
    ):
        raise RuntimeError("Refusing to erase render/revision history; use a forward fix")
    op.drop_table("render_outputs")
    op.drop_table("clip_revisions")
    op.drop_table("clips")
    op.drop_constraint(op.f("ck_jobs_kind"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_kind"), "jobs", "kind IN ('VALIDATE','IMPORT','PROCESS')"
    )
