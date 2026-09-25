FROM debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
       bc bison flex gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu \
       make libssl-dev libelf-dev python3 \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install --yes --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

ENV ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
WORKDIR /build
