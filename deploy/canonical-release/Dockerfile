# This local tag MUST be verified against the dependency image ID in the manifest.
# No application source from that image survives in the final filesystem.
FROM valoria-canonical-runtime:22081087e836
USER root
RUN rm -rf /app && mkdir -p /app
WORKDIR /app
COPY app/ /app/
ARG RELEASE_COMMIT
ENV VALORIA_RELEASE_COMMIT=$RELEASE_COMMIT \
    VALORIA_ENFORCE_RELEASE_MANIFEST=1 \
    PYTHONDONTWRITEBYTECODE=1
LABEL org.opencontainers.image.revision=$RELEASE_COMMIT
RUN python -c "from pathlib import Path; from services.release_guard import verify_release_tree; print(verify_release_tree(Path('/app')))"
# Preserve the dependency image's existing command and entrypoint.
