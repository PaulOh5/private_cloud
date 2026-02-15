FROM golang:1.23-bookworm AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/vm-manager ./cmd/vm-manager

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    iproute2 \
    iptables \
    qemu-system-x86 \
    qemu-utils \
    cloud-image-utils \
    genisoimage \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /out/vm-manager /usr/local/bin/vm-manager
CMD ["vm-manager"]
