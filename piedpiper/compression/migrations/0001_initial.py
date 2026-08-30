from __future__ import annotations

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Dictionary",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("corpus_key", models.CharField(db_index=True, max_length=128)),
                ("raw", models.BinaryField(editable=False)),
                ("sample_count", models.PositiveIntegerField()),
                ("trained_at", models.DateTimeField(auto_now_add=True)),
                ("retired_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"verbose_name_plural": "dictionaries"},
        ),
        migrations.CreateModel(
            name="Chunk",
            fields=[
                (
                    "digest",
                    models.CharField(max_length=64, primary_key=True, serialize=False),
                ),
                ("codec_id", models.PositiveSmallIntegerField()),
                ("raw_size", models.PositiveIntegerField()),
                ("stored_size", models.PositiveIntegerField()),
                ("refcount", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "dictionary",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="compression.dictionary",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Blob",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=512)),
                ("content_type", models.CharField(blank=True, max_length=128)),
                ("corpus_key", models.CharField(blank=True, db_index=True, max_length=128)),
                ("policy", models.CharField(default="balanced", max_length=16)),
                ("status", models.CharField(db_index=True, default="pending", max_length=16)),
                ("error", models.TextField(blank=True)),
                ("raw_size", models.BigIntegerField(default=0)),
                ("stored_size", models.BigIntegerField(default=0)),
                ("logical_size", models.BigIntegerField(default=0)),
                ("chunk_count", models.PositiveIntegerField(default=0)),
                ("dedup_hits", models.PositiveIntegerField(default=0)),
                ("sha256", models.CharField(blank=True, db_index=True, max_length=64)),
                ("encode_seconds", models.FloatField(default=0.0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blobs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ManifestEntry",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("index", models.PositiveIntegerField()),
                (
                    "blob",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="manifest",
                        to="compression.blob",
                    ),
                ),
                (
                    "chunk",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="compression.chunk",
                    ),
                ),
            ],
            options={"ordering": ["index"]},
        ),
        migrations.AddIndex(
            model_name="dictionary",
            index=models.Index(
                fields=["corpus_key", "-trained_at"], name="compression_corpus_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="chunk",
            index=models.Index(fields=["refcount"], name="chunk_refcount_idx"),
        ),
        migrations.AddIndex(
            model_name="chunk",
            index=models.Index(fields=["created_at"], name="compression_chunk_cre_idx"),
        ),
        migrations.AddIndex(
            model_name="blob",
            index=models.Index(
                fields=["owner", "-created_at"], name="compression_blob_owner_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="manifestentry",
            index=models.Index(
                fields=["blob", "index"], name="compression_manifest_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="manifestentry",
            constraint=models.UniqueConstraint(
                fields=("blob", "index"), name="manifest_blob_index_uniq"
            ),
        ),
    ]
