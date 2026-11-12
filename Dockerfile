# Lore Solo container images.
#
#   mcp  — the stdio MCP server: installed wheel + map dependencies under the
#          packaged constraints. No Node, no npm, no compilers, no source.
#   full — the same runtime plus Node 22 and the prebuilt setup site; can run
#          `setup`, `map`, or `mcp` inside the container.
#
# No official image is published; build local versioned tags explicitly:
#   docker build --target mcp  -t lore-solo:0.2.0-mcp .
#   docker build --target full -t lore-solo:0.2.0-full .
#
# A default build always compiles the wheel and the frontend from this
# checkout's source and ignores anything under dist/.
#
# Release flow (CI only): place the verified release artifacts under dist/
# — exactly one dist/lore_solo-*.whl, dist/release_constraints.txt, and
# dist/site/lore-site-<version>-linux-amd64.zip — then build with
#   docker build --build-arg LORE_RELEASE_ARTIFACTS=1 ...
# Release mode fails closed: the external constraints must match the
# wheel's embedded copy, and the site archive must satisfy the pinned
# linux-amd64 entry inside the wheel's own manifest (hash, build id,
# version, platform) via lore.site_bundle safe extraction.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:22-bookworm-slim
ARG LORE_RELEASE_ARTIFACTS=0

# Frontend: build the Next.js standalone output from source. In release
# mode this stage stays empty; the validated pinned archive is used instead.
FROM ${NODE_IMAGE} AS site
ARG LORE_RELEASE_ARTIFACTS
WORKDIR /ctx
COPY . /ctx
RUN set -e; \
    mkdir -p /site; \
    if [ "$LORE_RELEASE_ARTIFACTS" = "1" ]; then \
        echo "release artifacts mode: frontend comes from dist/site"; \
    else \
        cd /ctx/web && npm ci && npm run build && \
        cp -a .next/standalone/. /site/ && \
        mkdir -p /site/.next && \
        cp -a .next/static /site/.next/static && \
        if [ -d public ]; then cp -a public /site/public; fi; \
    fi

# Wheels + constraints. Source mode builds from the checkout; release mode
# stages the verified dist/ artifacts and the extracted pinned site bundle.
FROM ${PYTHON_IMAGE} AS wheels
ARG LORE_RELEASE_ARTIFACTS
WORKDIR /src
COPY . /src
RUN set -e; \
    mkdir -p /wheels /site-release; \
    if [ "$LORE_RELEASE_ARTIFACTS" = "1" ]; then \
        python /src/scripts/release_image_assets.py \
            --dist /src/dist --wheels /wheels --site /site-release; \
    else \
        pip install --no-cache-dir "setuptools>=77" && \
        pip wheel --no-deps --no-build-isolation --wheel-dir /wheels . && \
        cp lore/release_constraints.txt /wheels/constraints.txt; \
    fi

FROM ${NODE_IMAGE} AS node

FROM ${PYTHON_IMAGE} AS mcp
COPY --from=wheels /wheels /tmp/wheels
RUN set -e; \
    wheel=$(ls /tmp/wheels/lore_solo-*.whl | head -n 1); \
    pip install --no-cache-dir --only-binary=:all: \
        --constraint /tmp/wheels/constraints.txt "${wheel}[map]"; \
    rm -rf /tmp/wheels; \
    groupadd --gid 1000 lore; \
    useradd --uid 1000 --gid lore --no-create-home --shell /usr/sbin/nologin lore; \
    mkdir -p /workspace /library /tmp/lore-home; \
    chown 1000:1000 /workspace /library /tmp/lore-home
ENV HOME=/tmp/lore-home \
    LORE_CONTAINER=1 \
    LORE_WORKSPACE=/workspace \
    LORE_LIBRARY=/library
USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["lore-solo"]
CMD ["mcp"]

FROM mcp AS full
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends libstdc++6 ca-certificates && \
    rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=site /site /opt/site-src
COPY --from=wheels /site-release /opt/site-rel
RUN if [ -f /opt/site-rel/server.js ]; then \
        mv /opt/site-rel /opt/lore-site; \
        rm -rf /opt/site-src; \
    else \
        mv /opt/site-src /opt/lore-site; \
        rm -rf /opt/site-rel; \
    fi; \
    chown -R 1000:1000 /opt/lore-site
ENV LORE_WEB_DIR=/opt/lore-site
USER 1000:1000
