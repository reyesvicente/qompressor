from __future__ import annotations

from django.db import transaction
from django.db.models import Sum
from django.http import StreamingHttpResponse
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FileUploadParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Blob, Chunk, ManifestEntry
from ..pipeline import decode_blob
from ..storage import get_chunk_store, get_staging
from ..tasks import _DictProvider, ingest_blob


class BlobSerializer(serializers.ModelSerializer):
    ratio = serializers.FloatField(read_only=True)
    marginal_ratio = serializers.SerializerMethodField()
    dedup_rate = serializers.FloatField(read_only=True)

    class Meta:
        model = Blob
        fields = (
            "id",
            "name",
            "content_type",
            "corpus_key",
            "policy",
            "status",
            "error",
            "raw_size",
            "stored_size",
            "logical_size",
            "chunk_count",
            "dedup_hits",
            "dedup_rate",
            "ratio",
            "marginal_ratio",
            "sha256",
            "encode_seconds",
            "created_at",
            "completed_at",
        )
        read_only_fields = tuple(f for f in fields if f not in {"name", "policy", "corpus_key", "content_type"})

    def get_marginal_ratio(self, obj) -> float | None:
        value = obj.marginal_ratio
        return None if value == float("inf") else value


class BlobViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = BlobSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FileUploadParser]

    def get_queryset(self):
        return Blob.objects.filter(owner=self.request.user)

    @action(detail=False, methods=["post"], url_path="upload")
    def upload(self, request):
        """Accept an upload, stage it, and hand off to a worker.

        The request never holds the object in memory: `chunks()` yields the
        multipart stream straight to disk. Encoding is explicitly *not* done
        inline — a 2 GB archival encode would hold a gunicorn worker for
        minutes and time out behind any sane proxy.
        """
        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "No file provided under 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        blob = Blob.objects.create(
            owner=request.user,
            name=request.data.get("name") or upload.name,
            content_type=upload.content_type or "",
            corpus_key=request.data.get("corpus_key", ""),
            policy=request.data.get("policy", Blob.Policy.BALANCED),
        )
        get_staging().receive(blob.id, upload.chunks())

        # on_commit, not a bare delay(): cookiecutter-django sets
        # ATOMIC_REQUESTS, so this view runs inside a transaction. Publishing
        # immediately lets the worker pick the message up before the Blob row
        # is visible to any other connection, and ingest dies on DoesNotExist.
        transaction.on_commit(lambda: ingest_blob.delay(str(blob.id)))

        return Response(
            BlobSerializer(blob).data,
            status=status.HTTP_202_ACCEPTED,
            headers={"Location": f"/api/blobs/{blob.id}/"},
        )

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Reassemble and stream. Never materialises the object server-side."""
        blob = self.get_object()
        if blob.status != Blob.Status.READY:
            return Response(
                {"detail": f"Blob is {blob.status}."},
                status=status.HTTP_409_CONFLICT,
            )

        store = get_chunk_store()
        dictionaries = _DictProvider()
        digests = list(
            blob.manifest.order_by("index").values_list("chunk_id", flat=True)
        )

        def stream():
            for digest in digests:
                yield decode_blob(store.get(digest), dictionaries)

        response = StreamingHttpResponse(
            stream(), content_type=blob.content_type or "application/octet-stream"
        )
        response["Content-Length"] = str(blob.raw_size)
        response["Content-Disposition"] = f'attachment; filename="{blob.name}"'
        response["X-Checksum-Sha256"] = blob.sha256
        return response

    def perform_destroy(self, instance):
        # Releases refcounts; the sweeper reclaims bytes later. Deleting chunks
        # synchronously would mean a long lock on the hottest table you have.
        instance.release()
        instance.delete()

    @action(detail=False, methods=["get"])
    def stats(self, request):
        owned = self.get_queryset().filter(status=Blob.Status.READY)
        logical = owned.aggregate(n=Sum("raw_size"))["n"] or 0
        # Subquery rather than a reverse join: ManifestEntry.chunk is declared
        # related_name="+", so there is no `manifestentry` accessor to traverse.
        # Filtering on the digest (Chunk's primary key) also makes each chunk
        # count once without a .distinct(), which a join would have needed.
        physical = (
            Chunk.objects.filter(
                digest__in=ManifestEntry.objects.filter(blob__in=owned).values(
                    "chunk_id"
                )
            ).aggregate(n=Sum("stored_size"))["n"]
            or 0
        )
        return Response(
            {
                "objects": owned.count(),
                "logical_bytes": logical,
                "physical_bytes": physical,
                "effective_ratio": (logical / physical) if physical else None,
                "bytes_saved": logical - physical,
            }
        )
