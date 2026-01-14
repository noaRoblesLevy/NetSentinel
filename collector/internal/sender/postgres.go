// Package sender provides output backends for sending flow records.
package sender

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/netsentinel/collector/internal/config"
	"github.com/netsentinel/collector/pkg/flow"
	log "github.com/sirupsen/logrus"
)

// PostgresSender sends flow records directly to PostgreSQL/TimescaleDB.
type PostgresSender struct {
	pool *pgxpool.Pool
}

// NewPostgresSender creates a new PostgreSQL sender.
func NewPostgresSender(cfg *config.Config) (*PostgresSender, error) {
	poolConfig, err := pgxpool.ParseConfig(cfg.PostgresURL)
	if err != nil {
		return nil, fmt.Errorf("parse postgres url: %w", err)
	}

	// Configure pool
	poolConfig.MaxConns = 10
	poolConfig.MinConns = 2

	pool, err := pgxpool.NewWithConfig(context.Background(), poolConfig)
	if err != nil {
		return nil, fmt.Errorf("create pool: %w", err)
	}

	// Test connection
	if err := pool.Ping(context.Background()); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping database: %w", err)
	}

	log.Info("Connected to PostgreSQL")
	return &PostgresSender{pool: pool}, nil
}

// Send inserts a batch of flow records into the database.
func (p *PostgresSender) Send(ctx context.Context, batch *flow.Batch) error {
	if len(batch.Flows) == 0 {
		return nil
	}

	// Build batch insert using COPY for best performance
	rows := make([][]interface{}, 0, len(batch.Flows))

	for _, rec := range batch.Flows {
		rows = append(rows, []interface{}{
			rec.TimestampStart,
			rec.TimestampEnd,
			batch.SiteID,
			rec.ExporterID,
			rec.SrcIP.String(),
			rec.DstIP.String(),
			rec.SrcPort,
			rec.DstPort,
			rec.Protocol,
			rec.Bytes,
			rec.Packets,
			rec.DurationMs,
			rec.TCPFlags,
			rec.IsInternalSrc,
			rec.IsInternalDst,
		})
	}

	// Use CopyFrom for efficient bulk insert
	copyCount, err := p.pool.CopyFrom(
		ctx,
		pgx.Identifier{"flows_raw"},
		[]string{
			"ts_start", "ts_end", "site_id", "exporter_id",
			"src_ip", "dst_ip", "src_port", "dst_port",
			"protocol", "bytes", "packets", "duration_ms",
			"tcp_flags", "is_internal_src", "is_internal_dst",
		},
		pgx.CopyFromRows(rows),
	)

	if err != nil {
		// Fall back to regular INSERT if COPY fails
		return p.insertFallback(ctx, batch)
	}

	log.WithFields(log.Fields{
		"batch_id":   batch.BatchID,
		"rows":       copyCount,
	}).Debug("Inserted flows via COPY")

	return nil
}

// insertFallback uses a regular INSERT statement as a fallback.
func (p *PostgresSender) insertFallback(ctx context.Context, batch *flow.Batch) error {
	// Build multi-value INSERT
	var sb strings.Builder
	sb.WriteString(`INSERT INTO flows_raw (
		ts_start, ts_end, site_id, exporter_id,
		src_ip, dst_ip, src_port, dst_port,
		protocol, bytes, packets, duration_ms,
		tcp_flags, is_internal_src, is_internal_dst
	) VALUES `)

	args := make([]interface{}, 0, len(batch.Flows)*15)
	paramIdx := 1

	for i, rec := range batch.Flows {
		if i > 0 {
			sb.WriteString(",")
		}
		sb.WriteString(fmt.Sprintf("($%d,$%d,$%d,$%d,$%d,$%d,$%d,$%d,$%d,$%d,$%d,$%d,$%d,$%d,$%d)",
			paramIdx, paramIdx+1, paramIdx+2, paramIdx+3, paramIdx+4,
			paramIdx+5, paramIdx+6, paramIdx+7, paramIdx+8, paramIdx+9,
			paramIdx+10, paramIdx+11, paramIdx+12, paramIdx+13, paramIdx+14,
		))
		paramIdx += 15

		args = append(args,
			rec.TimestampStart,
			rec.TimestampEnd,
			batch.SiteID,
			rec.ExporterID,
			rec.SrcIP.String(),
			rec.DstIP.String(),
			rec.SrcPort,
			rec.DstPort,
			rec.Protocol,
			rec.Bytes,
			rec.Packets,
			rec.DurationMs,
			rec.TCPFlags,
			rec.IsInternalSrc,
			rec.IsInternalDst,
		)
	}

	_, err := p.pool.Exec(ctx, sb.String(), args...)
	if err != nil {
		return fmt.Errorf("insert flows: %w", err)
	}

	return nil
}

// Close closes the database connection pool.
func (p *PostgresSender) Close() error {
	p.pool.Close()
	return nil
}

// Name returns the sender name.
func (p *PostgresSender) Name() string {
	return "postgres"
}

// Ping tests the database connection.
func (p *PostgresSender) Ping(ctx context.Context) error {
	return p.pool.Ping(ctx)
}
