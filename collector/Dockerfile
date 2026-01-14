# NetSentinel Flow Collector
# Multi-stage build for minimal production image

# ============================================================================
# BUILD STAGE
# ============================================================================
FROM golang:1.22-alpine AS builder

WORKDIR /build

# Install build dependencies
RUN apk add --no-cache git ca-certificates

# Copy go mod files first for layer caching
COPY go.mod go.sum* ./
RUN go mod download

# Copy source code
COPY . .

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags="-w -s -X main.Version=$(git describe --tags --always --dirty 2>/dev/null || echo 'dev')" \
    -o /collector \
    ./cmd/collector

# ============================================================================
# PRODUCTION STAGE
# ============================================================================
FROM alpine:3.19

# Security: run as non-root user
RUN addgroup -g 1000 collector && \
    adduser -u 1000 -G collector -s /bin/sh -D collector

# Install runtime dependencies
RUN apk add --no-cache ca-certificates tzdata wget

WORKDIR /app

# Copy binary from builder
COPY --from=builder /collector /app/collector

# Set ownership
RUN chown -R collector:collector /app

USER collector

# Expose ports
EXPOSE 2055/udp
EXPOSE 8080/tcp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:8080/health || exit 1

# Run the collector
ENTRYPOINT ["/app/collector"]
